"""
Profile Learner  (Phase 4)

A DETERMINISTIC aggregator (no LLM) that turns accumulated run records into
structured, per-(subject, purpose, profile) calibration: how dense the deck
tended to be, how many bullets a theory slide actually carried, how many
slides per source page, and how often slides overflowed.

These `LearnedProfile`s are written to memory/style.yaml under `learned_profiles`
and fed back into the Profiler as a PRIOR — so each PDF a teacher processes
calibrates the system for their next, similar one. This closes the learning
loop that Phases 1-3 set up.

Why deterministic (not an LLM)? The work here is arithmetic over past runs —
averages and rates. Code does that exactly, cheaply, and reproducibly; an LLM
would only add cost and variance. The existing (LLM) Style Learner still runs
alongside this for qualitative free-text hints.
"""
from collections import defaultdict, Counter
from datetime import datetime
from statistics import mean

from schemas.run_record import RunRecord, LearnedProfile


# Need at least this many runs of a (subject,purpose,profile) before we trust
# an aggregate enough to feed it back as a prior.
MIN_RUNS_FOR_PROFILE = 2

# Baseline theory-bullet target by density, used when history is thin.
_DENSITY_BASELINE = {"terse": 4, "balanced": 5, "verbose": 7}

# Clamp the learned bullet target to a sane range.
_TARGET_MIN, _TARGET_MAX = 3, 8


def _group_key(r: RunRecord) -> str:
    return f"{r.subject.strip().lower()}|{r.purpose.strip().lower()}|{r.profile}"


def learn_profiles(runs: list[RunRecord]) -> list[LearnedProfile]:
    """
    Aggregate successful, profiled runs into per-group LearnedProfiles.
    Old records without a `profile` (pre-Phase-4) are skipped automatically.
    """
    groups: dict[str, list[RunRecord]] = defaultdict(list)
    for r in runs:
        if r.final_status != "success" or not r.profile:
            continue
        groups[_group_key(r)].append(r)

    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    out: list[LearnedProfile] = []

    for key, rs in groups.items():
        if len(rs) < MIN_RUNS_FOR_PROFILE:
            continue

        theory_avgs = [r.theory_bullet_avg for r in rs if r.theory_bullet_avg > 0]
        theory_avg = round(mean(theory_avgs), 2) if theory_avgs else 0.0

        spp = [r.slide_count / r.page_count for r in rs if r.page_count > 0]
        slides_per_page = round(mean(spp), 2) if spp else 0.0

        # overflow = the visual critic flagged a slide as not fitting (a real
        # defect), NOT mere pagination (which is the system working as intended).
        overflow_rate = round(
            mean([1.0 if r.visual_overflow_flags > 0 else 0.0 for r in rs]), 2
        )

        densities = Counter(r.density for r in rs if r.density)
        recommended_density = (
            densities.most_common(1)[0][0] if densities else "balanced"
        )

        # Target = what actually worked historically, falling back to the
        # density baseline; nudge DOWN if these decks frequently overflowed.
        if theory_avg > 0:
            target = round(theory_avg)
        else:
            target = _DENSITY_BASELINE.get(recommended_density, 5)
        if overflow_rate > 0.4:
            target -= 1
        target = max(_TARGET_MIN, min(_TARGET_MAX, int(target)))

        subject, purpose, profile = (key.split("|") + ["", "", ""])[:3]
        out.append(LearnedProfile(
            key=key,
            subject=subject,
            purpose=purpose,
            profile=profile,
            runs=len(rs),
            recommended_density=recommended_density,
            avg_bullets_per_theory_slide=theory_avg,
            avg_slides_per_page=slides_per_page,
            overflow_rate=overflow_rate,
            suggested_theory_bullet_target=target,
            updated_at=now,
        ))

    return out


def find_learned_profile(
    learned_profiles: list[dict] | None,
    subject: str,
    purpose: str,
) -> dict | None:
    """
    Best match for a (subject, purpose) from the stored learned_profiles list
    (dicts loaded from style.yaml). Profile component is ignored at lookup time
    because the Profiler hasn't classified the new PDF yet — we match on the
    instructor-supplied subject+purpose and let the LLM use it as a prior.
    Prefers the entry backed by the most runs.
    """
    if not learned_profiles:
        return None
    s, p = subject.strip().lower(), purpose.strip().lower()
    matches = [
        lp for lp in learned_profiles
        if isinstance(lp, dict)
        and lp.get("subject", "").strip().lower() == s
        and lp.get("purpose", "").strip().lower() == p
    ]
    if not matches:
        return None
    return max(matches, key=lambda lp: lp.get("runs", 0))


def render_profiles_report(profiles: list[LearnedProfile]) -> str:
    """Pretty-print for the pipeline log."""
    if not profiles:
        return (f"    No per-profile calibration learned yet "
                f"(need ≥ {MIN_RUNS_FOR_PROFILE} runs per subject/purpose).")
    lines = [f"    Learned {len(profiles)} profile calibration(s):"]
    for lp in profiles:
        lines.append(
            f"      • {lp.key}  ({lp.runs} runs) → density={lp.recommended_density}, "
            f"theory≈{lp.suggested_theory_bullet_target} bullets, "
            f"{lp.avg_slides_per_page} slides/page, overflow={lp.overflow_rate}"
        )
    return "\n".join(lines)
