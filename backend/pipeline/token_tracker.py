"""
Token & cost tracker for one pipeline run.

All Gemini calls across the pipeline (extractor, planner, writer, critics)
call `record_usage()` after every response. The orchestrator calls `summary()`
at the end to print a detailed breakdown to the terminal.

Usage pattern (in any agent — no import of the tracker needed):
    from pipeline.token_tracker import record_usage
    response = client.models.generate_content(...)
    record_usage("writing", response.usage_metadata, model=WRITING_MODEL)

Pricing is model-aware. If you change e.g. EXTRACTION_MODEL to
`gemini-3.5-flash`, the next run's cost summary uses that model's row.
"""

import threading
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

# ── Pricing constants (USD per 1M tokens) ───────────────────────────────────
# Paid-tier Gemini API prices, output includes thinking tokens.
# Keep this table in one place so model changes in config.py are reflected in
# the cost summary as soon as call sites pass the configured model name.
_MODEL_PRICING_PER_1M = {
    "gemini-3.5-flash":      {"input": 1.50, "output": 9.00},
    "gemini-3-flash":        {"input": 0.50, "output": 3.00},
    "gemini-3-flash-preview": {"input": 0.50, "output": 3.00},
    "gemini-3.1-flash-lite": {"input": 0.25, "output": 1.50},
    "gemini-2.5-flash":      {"input": 0.30, "output": 2.50},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
}

_FALLBACK_PRICING_PER_1M = {"input": 0.30, "output": 2.50}

# Per-model Pro pricing (USD/1M tokens). Gemini 3.x Pro and 2.5 Pro have
# different base rates; both double above 200k context.
_PRO_PRICING: dict[str, dict[str, float]] = {
    "gemini-3.1-pro": {"input": 2.00, "output": 12.00},   # matches both "gemini-3.1-pro" and "gemini-3.1-pro-preview"
    "gemini-3-pro":   {"input": 2.00, "output": 12.00},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
}
_PRO_MODEL_PREFIXES = tuple(_PRO_PRICING.keys())


def _pricing_for_model(model: str | None, prompt_tokens: int) -> dict[str, float]:
    """Return USD-per-1M pricing for the model, handling Pro tier thresholds."""
    m = (model or "unknown").strip()
    for prefix, base_rates in _PRO_PRICING.items():
        if m.startswith(prefix):
            if prompt_tokens > 200_000:
                # Long-context doubles input; output also increases
                return {"input": base_rates["input"] * 2, "output": base_rates["output"] * 1.5}
            return base_rates
    return _MODEL_PRICING_PER_1M.get(m, _FALLBACK_PRICING_PER_1M)


@dataclass
class _StageUsage:
    name:            str
    model:           str = "unknown"
    prompt_tokens:   int = 0
    output_tokens:   int = 0
    thinking_tokens: int = 0
    calls:           int = 0          # responses with/without usage metadata
    attempted_calls: int = 0          # every generate_content request attempted
    failed_calls:    int = 0          # requests that raised before a response

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens + self.thinking_tokens

    @property
    def cost_usd(self) -> float:
        pricing = _pricing_for_model(self.model, self.prompt_tokens)
        return (
            self.prompt_tokens / 1_000_000 * pricing["input"]
            + self.output_tokens / 1_000_000 * pricing["output"]
            + self.thinking_tokens / 1_000_000 * pricing["output"]
        )


@dataclass
class _Totals:
    prompt_tokens:   int
    output_tokens:   int
    thinking_tokens: int
    calls:           int
    attempted_calls: int
    failed_calls:    int
    cost_usd:        float


# ── Module-level context variable ────────────────────────────────────────────
# Set by the orchestrator at the start of each pipeline run via `activate()`.
# Any agent in the same async context can call `record_usage()` directly
# without receiving the tracker as a parameter.
_current_tracker: ContextVar[Optional["TokenTracker"]] = ContextVar(
    "_current_tracker", default=None
)


def record_usage(stage: str, usage_metadata, model: str | None = None) -> None:
    """
    Convenience function — record usage into the active tracker for this run.
    Call this in any agent right after a `generate_content` call.
    No-op if no tracker is active (e.g. during tests).
    """
    tracker = _current_tracker.get()
    if tracker is not None:
        tracker.record(stage, usage_metadata, model)


def record_api_attempt(stage: str, model: str | None = None) -> None:
    """Count a Gemini API request attempt, even if it later fails."""
    tracker = _current_tracker.get()
    if tracker is not None:
        tracker.record_attempt(stage, model)


def record_api_failure(stage: str, model: str | None = None) -> None:
    """Count a Gemini API request that raised before returning a response."""
    tracker = _current_tracker.get()
    if tracker is not None:
        tracker.record_failure(stage, model)


class TokenTracker:
    """
    Thread-safe accumulator. One instance per pipeline run.
    Stages: extraction, planning, writing, critics.
    """

    _STAGES = ("extraction", "planning", "writing", "critics")

    def __init__(self):
        self._lock   = threading.RLock()
        self._buckets: dict[tuple[str, str], _StageUsage] = {}

    def activate(self) -> None:
        """Register this tracker as the active one for the current async context."""
        _current_tracker.set(self)

    # ── Public API ────────────────────────────────────────────────────────────

    def _bucket_for(self, stage: str, model: str | None) -> _StageUsage:
        stage_name = stage if stage in self._STAGES else "other"
        model_name = (model or "unknown").strip() or "unknown"
        key = (stage_name, model_name)
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _StageUsage(name=stage_name, model=model_name)
                self._buckets[key] = bucket
            return bucket

    def record(self, stage: str, usage_metadata, model: str | None = None) -> None:
        """
        Record token counts from one Gemini response.

        `usage_metadata` is the `response.usage_metadata` object from the
        google-genai SDK. Missing fields default to 0.
        """
        prompt   = getattr(usage_metadata, "prompt_token_count",      0) or 0
        output   = getattr(usage_metadata, "candidates_token_count",  0) or 0
        thinking = getattr(usage_metadata, "thoughts_token_count",    0) or 0

        bucket = self._bucket_for(stage, model)
        with self._lock:
            bucket.prompt_tokens   += prompt
            bucket.output_tokens   += output
            bucket.thinking_tokens += thinking
            bucket.calls           += 1

    def record_attempt(self, stage: str, model: str | None = None) -> None:
        """Record that a Gemini request was attempted."""
        bucket = self._bucket_for(stage, model)
        with self._lock:
            bucket.attempted_calls += 1

    def record_failure(self, stage: str, model: str | None = None) -> None:
        """Record that a Gemini request raised before returning usage metadata."""
        bucket = self._bucket_for(stage, model)
        with self._lock:
            bucket.failed_calls += 1

    def summary(self, elapsed_seconds: float) -> str:
        """Return a formatted multi-line summary string."""
        with self._lock:
            all_stages = sorted(
                self._buckets.values(),
                key=lambda s: (self._STAGES.index(s.name) if s.name in self._STAGES else 99, s.model),
            )

        totals = self._collect_totals(all_stages)

        mins, secs = divmod(int(elapsed_seconds), 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        lines = [
            "",
            "╔════════════════════════════════════════════════════════════════════════════════════════╗",
            "║                         Token Usage & Cost Report                                    ║",
            "╠════════════════════════════════════════════════════════════════════════════════════════╣",
            f"║  Total time        : {time_str:<65}║",
            f"║  API attempts      : {totals.attempted_calls:<65}║",
            f"║  API responses     : {totals.calls:<65}║",
            f"║  API failures      : {totals.failed_calls:<65}║",
            "╠════════════════════════════════════════════════════════════════════════════════════════╣",
            f"║  {'Stage':<10} {'Model':<23} {'Try':>4} {'Resp':>4} {'Fail':>4} {'Input':>8} {'Output':>8} {'Think':>7} {'Cost':>8} ║",
            f"║  {'-'*10} {'-'*23} {'-'*4} {'-'*4} {'-'*4} {'-'*8} {'-'*8} {'-'*7} {'-'*8} ║",
        ]

        for s in all_stages:
            if s.calls == 0 and s.attempted_calls == 0 and s.failed_calls == 0:
                continue
            cost_str = f"${s.cost_usd:.4f}"
            model = s.model[:23]
            lines.append(
                f"║  {s.name:<10} {model:<23} {s.attempted_calls:>4} {s.calls:>4} {s.failed_calls:>4} "
                f"{s.prompt_tokens:>8,} {s.output_tokens:>8,} "
                f"{s.thinking_tokens:>7,} {cost_str:>8} ║"
            )

        lines += [
            f"╠════════════════════════════════════════════════════════════════════════════════════════╣",
            f"║  {'TOTAL':<10} {'':<23} {totals.attempted_calls:>4} {totals.calls:>4} {totals.failed_calls:>4} "
            f"{totals.prompt_tokens:>8,} {totals.output_tokens:>8,} "
            f"{totals.thinking_tokens:>7,} ${totals.cost_usd:>7.4f} ║",
            f"║                                                                                        ║",
            f"║  Pricing is model-aware; output includes thinking tokens. Unknown models use fallback. ║",
            f"║  TOTAL COST for this PPT  :  ${totals.cost_usd:.4f} USD{'':>53}║",
            f"╚════════════════════════════════════════════════════════════════════════════════════════╝",
            "",
        ]
        return "\n".join(lines)

    def report_dict(self, elapsed_seconds: float) -> dict:
        """
        Structured version of `summary()` for the API/frontend.

        Returns a JSON-serialisable dict with per-(stage, model) rows and the
        run totals, so the UI can render charts identical to the terminal report.
        """
        with self._lock:
            all_stages = sorted(
                self._buckets.values(),
                key=lambda s: (
                    self._STAGES.index(s.name) if s.name in self._STAGES else 99,
                    s.model,
                ),
            )
        totals = self._collect_totals(all_stages)

        rows = []
        for s in all_stages:
            if s.calls == 0 and s.attempted_calls == 0 and s.failed_calls == 0:
                continue
            rows.append({
                "stage":           s.name,
                "model":           s.model,
                "attempts":        s.attempted_calls,
                "responses":       s.calls,
                "failures":        s.failed_calls,
                "input_tokens":    s.prompt_tokens,
                "output_tokens":   s.output_tokens,
                "thinking_tokens": s.thinking_tokens,
                "total_tokens":    s.total_tokens,
                "cost_usd":        round(s.cost_usd, 6),
            })

        return {
            "elapsed_seconds": round(elapsed_seconds, 2),
            "pricing_note": (
                "Pricing is model-aware; output cost includes thinking tokens. "
                "Unknown models fall back to Gemini 2.5 Flash rates."
            ),
            "totals": {
                "attempts":        totals.attempted_calls,
                "responses":       totals.calls,
                "failures":        totals.failed_calls,
                "input_tokens":    totals.prompt_tokens,
                "output_tokens":   totals.output_tokens,
                "thinking_tokens": totals.thinking_tokens,
                "total_tokens": (
                    totals.prompt_tokens
                    + totals.output_tokens
                    + totals.thinking_tokens
                ),
                "cost_usd":        round(totals.cost_usd, 6),
            },
            "rows": rows,
        }

    def snapshot(self) -> _Totals:
        """Return a totals snapshot for delta comparisons."""
        with self._lock:
            all_stages = list(self._buckets.values())
        return self._collect_totals(all_stages)

    def summary_delta(self, before: _Totals, elapsed_seconds: float) -> str:
        """Return a compact summary string for usage since a snapshot."""
        with self._lock:
            all_stages = list(self._buckets.values())
        after = self._collect_totals(all_stages)

        delta_prompt = max(after.prompt_tokens - before.prompt_tokens, 0)
        delta_output = max(after.output_tokens - before.output_tokens, 0)
        delta_think  = max(after.thinking_tokens - before.thinking_tokens, 0)
        delta_calls  = max(after.calls - before.calls, 0)
        delta_attempts = max(after.attempted_calls - before.attempted_calls, 0)
        delta_failures = max(after.failed_calls - before.failed_calls, 0)
        delta_cost   = max(after.cost_usd - before.cost_usd, 0.0)

        mins, secs = divmod(int(elapsed_seconds), 60)
        time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

        lines = [
            "",
            "╔══════════════════════════════════════════════════════╗",
            "║      Background LLM Usage (telemetry)                ║",
            "╠══════════════════════════════════════════════════════╣",
            f"║  Total time        : {time_str:<33}║",
            f"║  API attempts      : {delta_attempts:<33}║",
            f"║  API responses     : {delta_calls:<33}║",
            f"║  API failures      : {delta_failures:<33}║",
            "╠══════════════════════════════════════════════════════╣",
            f"║  Input  {delta_prompt:>10,} | Output {delta_output:>10,} | Think {delta_think:>8,} ║",
            f"║  Cost  ${delta_cost:>10.4f} USD{'':>20}║",
            "╚══════════════════════════════════════════════════════╝",
            "",
        ]
        return "\n".join(lines)

    @staticmethod
    def _collect_totals(stages: list[_StageUsage]) -> _Totals:
        total_prompt   = sum(s.prompt_tokens   for s in stages)
        total_output   = sum(s.output_tokens   for s in stages)
        total_thinking = sum(s.thinking_tokens for s in stages)
        total_calls    = sum(s.calls           for s in stages)
        total_attempts = sum(s.attempted_calls for s in stages)
        total_failures = sum(s.failed_calls    for s in stages)
        total_cost     = sum(s.cost_usd        for s in stages)
        return _Totals(
            prompt_tokens=total_prompt,
            output_tokens=total_output,
            thinking_tokens=total_thinking,
            calls=total_calls,
            attempted_calls=total_attempts,
            failed_calls=total_failures,
            cost_usd=total_cost,
        )
