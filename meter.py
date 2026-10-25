"""Token meter.

Every model call is recorded here so the tokenomics section of the report is
built from measured numbers, not estimates. Runs append to runs/usage.jsonl.
"""
import json
import time
from pathlib import Path
from threading import Lock

RUNS_DIR = Path(__file__).resolve().parent / "runs"
RUNS_DIR.mkdir(exist_ok=True)
USAGE_LOG = RUNS_DIR / "usage.jsonl"

_lock = Lock()

# Rates in dollars per 1M tokens. UPDATE THESE from the course pricing page
# before generating the final cost table.
PRICING = {
    "gpt-6-luna": {
        "input": 0.15,
        "cached_input": 0.075,
        "output": 0.60,
    }
}


class RunMeter:
    """Accumulates token usage across the agents in a single run."""

    def __init__(self, run_id: str, model: str):
        self.run_id = run_id
        self.model = model
        self.started = time.time()
        self.calls = []

    def record(self, agent: str, usage) -> None:
        """Pull measured counts off an OpenAI-compatible usage object."""
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        completion = getattr(usage, "completion_tokens", 0) or 0

        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        cached = cached or 0

        # This model reasons before answering. Reasoning tokens are billed as
        # output but never shown to the user, so they are tracked separately --
        # they turn out to dominate the bill. See the tokenomics section.
        out_details = getattr(usage, "completion_tokens_details", None)
        reasoning = getattr(out_details, "reasoning_tokens", 0) if out_details else 0
        reasoning = reasoning or 0

        self.calls.append({
            "agent": agent,
            "input_tokens": prompt - cached,
            "cached_input_tokens": cached,
            "output_tokens": completion,
            "reasoning_tokens": reasoning,
        })

    @property
    def totals(self) -> dict:
        t = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0,
             "reasoning_tokens": 0}
        for c in self.calls:
            for k in t:
                t[k] += c.get(k, 0)
        return t

    def cost(self) -> float:
        rates = PRICING.get(self.model, PRICING["gpt-6-luna"])
        t = self.totals
        return (
            t["input_tokens"] / 1_000_000 * rates["input"]
            + t["cached_input_tokens"] / 1_000_000 * rates["cached_input"]
            + t["output_tokens"] / 1_000_000 * rates["output"]
        )

    def summary(self) -> dict:
        t = self.totals
        return {
            "run_id": self.run_id,
            "model": self.model,
            "seconds": round(time.time() - self.started, 2),
            "agent_calls": len(self.calls),
            "per_agent": self.calls,
            **t,
            "total_tokens": t["input_tokens"] + t["cached_input_tokens"] + t["output_tokens"],
            "cost_usd": round(self.cost(), 6),
        }

    def flush(self) -> dict:
        s = self.summary()
        with _lock:
            with USAGE_LOG.open("a") as f:
                f.write(json.dumps(s) + "\n")
        return s


def all_runs() -> list:
    if not USAGE_LOG.exists():
        return []
    out = []
    for line in USAGE_LOG.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def aggregate() -> dict:
    """Averages across all recorded runs — this feeds the report's cost table."""
    runs = all_runs()
    if not runs:
        return {"runs": 0}

    n = len(runs)
    avg = {
        "runs": n,
        "avg_input": round(sum(r["input_tokens"] for r in runs) / n),
        "avg_cached": round(sum(r["cached_input_tokens"] for r in runs) / n),
        "avg_output": round(sum(r["output_tokens"] for r in runs) / n),
        "avg_reasoning": round(sum(r.get("reasoning_tokens", 0) for r in runs) / n),
        "avg_cost": sum(r["cost_usd"] for r in runs) / n,
        "avg_seconds": round(sum(r["seconds"] for r in runs) / n, 2),
    }
    avg["avg_total_tokens"] = avg["avg_input"] + avg["avg_cached"] + avg["avg_output"]

    # Scaling assumption stated plainly in the report: 4 planned events a year
    # per user, so a third of a run per month.
    runs_per_user_month = 4 / 12
    avg["cost_per_user_month"] = avg["avg_cost"] * runs_per_user_month
    avg["cost_100_users_month"] = avg["cost_per_user_month"] * 100
    avg["cost_10k_users_month"] = avg["cost_per_user_month"] * 10_000
    return avg
