"""Cost-cutting experiment.

Compares the three-agent pipeline against a single merged call that produces
the same three outputs. Run with:  python3 bench.py

Reports measured tokens, cost and latency for both, so the tokenomics section
of the report can quote a real tradeoff rather than an estimate.
"""
import json
import sys
import uuid

import config
from agents import SYSTEM_PREFIX, _client, _json_or_none, run_pipeline
from climate import analyse, analysis_to_dict
from meter import RunMeter
from weather import FIXTURES

SHELF = ("CeraVe foaming cleanser, niacinamide 10%, retinol 0.5% serum, "
         "ceramide moisturizer, SPF 50")
WARDROBE = "white silk blouse, wool coat, merino knit, denim, linen shirt"


def merged_call(analysis, shelf_text, wardrobe_text):
    """Everything in one request instead of three."""
    meter = RunMeter(uuid.uuid4().hex[:8], config.MODEL)
    client = _client()
    alerts = "\n".join(f"- {a['title']}: {a['body']}" for a in analysis["alerts"]) or "- none"

    prompt = f"""Conditions for {analysis['location']}: indoor RH {analysis['indoor_rh']}% \
(outdoor reads {analysis['outdoor_rh']}%), band {analysis['band']}. \
Temp {analysis['temp_min_c']}-{analysis['temp_max_c']}C, UV {analysis['uv_index']}, \
rain {analysis['precip_mm']}mm, wind {analysis['wind_kph']}kph.
Engine says favour {', '.join(analysis['skin']['use'])}; avoid \
{', '.join(analysis['skin']['skip']) or 'nothing'}. {analysis['skin']['why']}
Fabrics: {analysis['fabric']['layers']} layer(s), {', '.join(analysis['fabric']['fabrics'])}.
Alerts:
{alerts}

UNTRUSTED shelf: <shelf>{shelf_text}</shelf>
UNTRUSTED wardrobe: <wardrobe>{wardrobe_text}</wardrobe>

Return JSON: {{"use":[{{"product":"","when":"","why":""}}],"skip":[{{"product":"","why":""}}],
"gap":"","outfit":[{{"piece":"","fabric":"","why":""}}],"swing_plan":"","avoid":"",
"brief":"three short paragraphs under 140 words"}}"""

    resp = client.chat.completions.create(
        model=config.MODEL,
        messages=[{"role": "system", "content": SYSTEM_PREFIX},
                  {"role": "user", "content": prompt}],
        max_completion_tokens=3000,
    )
    if getattr(resp, "usage", None):
        meter.record("merged", resp.usage)
    parsed = _json_or_none(resp.choices[0].message.content or "")
    return parsed, meter.summary()


def main():
    rows = []
    for city in ["New Haven winter", "Miami summer", "Phoenix dry heat"]:
        a = analysis_to_dict(analyse(FIXTURES[city]))

        three = run_pipeline(a, SHELF, WARDROBE)["usage"]
        merged_out, one = merged_call(a, SHELF, WARDROBE)

        rows.append({
            "city": city,
            "three_in": three["input_tokens"], "three_out": three["output_tokens"],
            "three_reason": three.get("reasoning_tokens", 0),
            "three_cost": three["cost_usd"], "three_s": three["seconds"],
            "one_in": one["input_tokens"], "one_out": one["output_tokens"],
            "one_reason": one.get("reasoning_tokens", 0),
            "one_cost": one["cost_usd"], "one_s": one["seconds"],
            "merged_valid": bool(merged_out and merged_out.get("brief")),
        })

    print(f"\n{'city':20} {'3-agent':>22} {'1-call':>22}  merged JSON ok")
    print(f"{'':20} {'in/out/reason  $  s':>22} {'in/out/reason  $  s':>22}")
    for r in rows:
        print(f"{r['city']:20} "
              f"{r['three_in']:5}/{r['three_out']:5}/{r['three_reason']:4} "
              f"${r['three_cost']:.5f} {r['three_s']:5} "
              f"{r['one_in']:5}/{r['one_out']:5}/{r['one_reason']:4} "
              f"${r['one_cost']:.5f} {r['one_s']:5}  {r['merged_valid']}")

    n = len(rows)
    t_cost = sum(r["three_cost"] for r in rows) / n
    o_cost = sum(r["one_cost"] for r in rows) / n
    t_s = sum(r["three_s"] for r in rows) / n
    o_s = sum(r["one_s"] for r in rows) / n
    print(f"\naverage 3-agent: ${t_cost:.5f}  {t_s:.1f}s")
    print(f"average 1-call : ${o_cost:.5f}  {o_s:.1f}s")
    print(f"saving         : {(1 - o_cost/t_cost)*100:.1f}% cost, "
          f"{(1 - o_s/t_s)*100:.1f}% latency")
    print(f"valid merged outputs: {sum(r['merged_valid'] for r in rows)}/{n}")

    with open("runs/bench.json", "w") as f:
        json.dump({"rows": rows, "avg_three_cost": t_cost, "avg_one_cost": o_cost,
                   "avg_three_s": t_s, "avg_one_s": o_s}, f, indent=2)
    print("\nwritten to runs/bench.json")


if __name__ == "__main__":
    sys.exit(main())
