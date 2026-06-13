"""
Safely merge Style Learner suggestions into memory/style.yaml.

Critical safety properties:
  • Manually-edited rules are PRESERVED — we only ADD to a dedicated
    "learned_hints" section.
  • Each hint carries provenance (timestamp, confidence, evidence_runs)
    so a human can audit / remove anything that looks wrong.
  • Idempotent: re-running with the same proposals does NOT duplicate
    entries (we match by key).
  • A backup copy of the previous yaml is written before any change.
"""
import os
import shutil
import yaml
from datetime import datetime

from schemas.run_record import StyleUpdate
from config import STYLE_YAML, MEMORY_DIR


# Minimum confidence required to actually write a hint into the yaml
APPLY_CONFIDENCE_THRESHOLD = 0.7


def merge_style_update(update: StyleUpdate) -> list[str]:
    """
    Apply the learner's proposed hints to memory/style.yaml.

    Returns a list of human-readable change descriptions (empty if
    nothing was added).
    """
    if not update.new_hints:
        return []

    # ── load current yaml ─────────────────────────────────────────────────
    current: dict = {}
    if os.path.exists(STYLE_YAML):
        with open(STYLE_YAML, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}

    learned: list[dict] = current.get("learned_hints", []) or []
    existing_keys = {item.get("key") for item in learned if isinstance(item, dict)}

    changes: list[str] = []
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    for h in update.new_hints:
        if h.confidence < APPLY_CONFIDENCE_THRESHOLD:
            continue
        if h.key in existing_keys:
            # Update only if confidence climbed significantly
            existing = next((x for x in learned if x.get("key") == h.key), None)
            if existing and h.confidence > existing.get("confidence", 0) + 0.1:
                existing["value"]         = h.value
                existing["confidence"]    = round(h.confidence, 2)
                existing["evidence_runs"] = h.evidence_runs
                existing["rationale"]     = h.rationale
                existing["updated_at"]    = now_iso
                changes.append(f"updated hint '{h.key}' (conf → {h.confidence:.2f})")
            continue

        learned.append({
            "key":           h.key,
            "value":         h.value,
            "confidence":    round(h.confidence, 2),
            "evidence_runs": h.evidence_runs,
            "rationale":     h.rationale,
            "added_at":      now_iso,
        })
        existing_keys.add(h.key)
        changes.append(f"added hint '{h.key}'  ({h.value[:80]})")

    if not changes:
        return []

    # ── backup existing yaml then write merged version ────────────────────
    if os.path.exists(STYLE_YAML):
        backup_dir = os.path.join(MEMORY_DIR, "style_backups")
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(
            backup_dir,
            f"style_{now_iso.replace(':', '')}.yaml"
        )
        shutil.copy2(STYLE_YAML, backup_path)

    current["learned_hints"]     = learned
    current["last_learner_run"]  = now_iso

    with open(STYLE_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            current, f, sort_keys=False,
            allow_unicode=True, default_flow_style=False,
        )
    return changes


def write_learned_profiles(profiles: list) -> list[str]:
    """
    Persist Phase-4 structured per-profile calibration to memory/style.yaml
    under `learned_profiles`, leaving manual rules and `learned_hints` intact.

    `profiles` is a list of LearnedProfile. Returns a human-readable change log.
    Fully replaces the `learned_profiles` section each run (it is a pure,
    deterministic re-aggregation of recent runs — no need to merge incrementally).
    """
    if not profiles:
        return []

    current: dict = {}
    if os.path.exists(STYLE_YAML):
        with open(STYLE_YAML, "r", encoding="utf-8") as f:
            current = yaml.safe_load(f) or {}

    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    # backup before writing
    if os.path.exists(STYLE_YAML):
        backup_dir = os.path.join(MEMORY_DIR, "style_backups")
        os.makedirs(backup_dir, exist_ok=True)
        shutil.copy2(
            STYLE_YAML,
            os.path.join(backup_dir, f"style_{now_iso.replace(':', '')}.yaml"),
        )

    serialised = [
        p.model_dump() if hasattr(p, "model_dump") else dict(p)
        for p in profiles
    ]
    current["learned_profiles"]      = serialised
    current["last_profile_learn"]    = now_iso

    with open(STYLE_YAML, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            current, f, sort_keys=False,
            allow_unicode=True, default_flow_style=False,
        )
    return [f"calibrated '{p.key}' ({p.runs} runs)" for p in profiles]
