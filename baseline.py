"""Head-to-head against the current method.

The honest competitor for DewPoint is not another app -- it is asking a capable
language model directly, which is what most people would actually do. This
script runs that comparison across every sample city:

  BASELINE   the model is asked, with the same live weather data, what the
             indoor humidity is and what the routine should be. No tools, no
             psychrometrics, the way a person would ask it.
  DEWPOINT   the deterministic engine computes the figure.

Both are scored against the engine's computed value, which is the physically
derived answer. The question is whether asking a model directly gets you the
same number, and if not, by how much it misses and whether the resulting
advice band differs.

    python3 baseline.py
"""
import json
import re
import statistics
import sys
import time
import uuid
from pathlib import Path

import config
from agents import _client
from climate import analyse, analysis_to_dict, dryness_band
from meter import RunMeter

HERE = Path(__file__).resolve().parent
FIXTURES = json.loads((HERE / "data/sample_days.json").read_text())

# Two framings. The first hands the model the dew point, which is generous --
# it presupposes the user already knows that dew point is the quantity that
# matters, which is the whole insight. The second is what a person would
# actually type, having looked at a weather app.
PROMPT_ASSISTED = """It is {temp}C outside with a dew point of {dew}C and {rh}% relative \
humidity in {city}. I am indoors.

What is the relative humidity of the air indoors, where I actually am? Give the figure as \
a number. Then say in one line whether my skin needs richer moisturising or whether I can \
carry on with acids and retinoids as usual."""

PROMPT_REALISTIC = """I'm in {city}. My weather app says it's {temp}C and {rh}% humidity \
today. I'm indoors most of the day.

What humidity is my skin actually dealing with? Give a number. Then tell me in one line \
whether I need a richer moisturiser or whether I can carry on with my acids and retinoid."""

PROMPT = PROMPT_ASSISTED


def ask_baseline(client, meter, city, w, template=None):
    prompt = (template or PROMPT).format(city=city, temp=w["temp_c"],
                                         dew=w["dew_point_c"], rh=w["outdoor_rh"])
    t0 = time.time()
    resp = client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_completion_tokens=1200,
    )
    elapsed = time.time() - t0
    if getattr(resp, "usage", None):
        meter.record("baseline", resp.usage)
    text = (resp.choices[0].message.content or "").strip()

    # first percentage-looking number in the reply
    m = re.search(r"(\d{1,3}(?:\.\d)?)\s*%", text)
    guess = float(m.group(1)) if m else None
    return guess, text, elapsed


def main():
    client = _client()
    meter = RunMeter(uuid.uuid4().hex[:8], config.MODEL)
    rows = []

    for city, w in FIXTURES.items():
        truth = analysis_to_dict(analyse(w))
        guess, text, elapsed = ask_baseline(client, meter, city, w)
        if guess is None:
            print(f"  {city:16} no number returned")
            continue
        gband, _ = dryness_band(guess)
        rows.append({
            "city": city,
            "truth_rh": truth["indoor_rh"], "truth_band": truth["band"],
            "model_rh": guess, "model_band": gband,
            "error": abs(guess - truth["indoor_rh"]),
            "band_match": gband == truth["band"],
            "seconds": round(elapsed, 2),
            "mode": truth["mode"],
        })
        print(f"  {city:16} engine {truth['indoor_rh']:>5.1f}% {truth['band']:<12} "
              f"model {guess:>5.1f}% {gband:<12} "
              f"{'match' if gband == truth['band'] else 'MISS'}")
        time.sleep(0.4)

    n = len(rows)
    errs = [r["error"] for r in rows]
    matches = sum(1 for r in rows if r["band_match"])
    print(f"\n  cities tested            : {n}")
    print(f"  mean absolute error      : {statistics.mean(errs):.1f} points")
    print(f"  median absolute error    : {statistics.median(errs):.1f} points")
    print(f"  worst miss               : {max(errs):.1f} points")
    print(f"  same advice band         : {matches} of {n} ({matches/n*100:.0f}%)")
    print(f"  mean model latency       : {statistics.mean([r['seconds'] for r in rows]):.1f}s")
    print(f"  engine latency           : <0.001s (no network, no model)")
    usage = meter.flush()
    print(f"  baseline cost for {n} asks : ${usage['cost_usd']:.5f}")
    print(f"  engine cost              : $0.00000")

    out = {"rows": rows, "n": n,
           "mean_error": statistics.mean(errs),
           "median_error": statistics.median(errs),
           "worst_error": max(errs),
           "band_matches": matches,
           "mean_latency": statistics.mean([r["seconds"] for r in rows]),
           "baseline_cost": usage["cost_usd"]}
    (HERE / "runs/baseline.json").write_text(json.dumps(out, indent=2))
    print("\n  written to runs/baseline.json")


if __name__ == "__main__":
    sys.exit(main())
