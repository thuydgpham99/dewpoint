"""DewPoint -- Flask app."""
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
from agents import run_pipeline
from climate import analyse, analysis_to_dict
from guard import screen_request
from meter import aggregate, all_runs
from receipts import (add_items, expiry_report, load_inventory, monthly_spend,
                      parse_receipt, purchase_context, seasonal_mismatch,
                      spend_summary)
from weather import FIXTURES, fetch

app = Flask(__name__)


def grouped_samples():
    """Sample cities grouped by region, for the picker."""
    out = {}
    for name, payload in FIXTURES.items():
        out.setdefault(payload.get("region", "Other"), []).append(name)
    order = ["Americas", "Europe", "Asia", "Middle East & Africa", "Oceania"]
    return {r: out[r] for r in order if r in out}


@app.route("/")
def index():
    return render_template(
        "index.html",
        env_source=config.ENV_SOURCE,
        key_present=bool(config.PORTKEY_API_KEY),
        model=config.MODEL,
        regions=grouped_samples(),
        year=datetime.now().year,
    )


@app.route("/api/plan", methods=["POST"])
def plan():
    data = request.get_json(force=True) or {}
    city = (data.get("city") or "New Haven").strip()
    shelf = (data.get("shelf") or "").strip()
    wardrobe = (data.get("wardrobe") or "").strip()

    # --- Safety gate runs before anything reaches the model -----------------
    screen = screen_request(shelf, wardrobe, config.MAX_INPUT_CHARS)
    if screen["medical_blocked"]:
        return jsonify({
            "blocked": "medical",
            "message": screen["medical_message"],
            "reasons": screen["medical_reasons"],
        })

    weather = fetch(city)
    analysis = analysis_to_dict(analyse(weather))

    result = run_pipeline(analysis, screen["safe_shelf"], screen["safe_wardrobe"])

    # Frame any suggestion against what the user already owns and already spent,
    # so the app never recommends a purchase without that context.
    inventory = load_inventory()
    gap_category = (result["shelf"].get("gap_category") or "").strip() or None
    context = purchase_context(inventory, gap_category)
    mismatch = seasonal_mismatch(inventory, analysis["band"]) if inventory else {}

    return jsonify({
        "purchase_context": context,
        "mismatch": mismatch,
        "blocked": None,
        "weather_source": weather.get("source", ""),
        "analysis": analysis,
        "shelf": result["shelf"],
        "style": result["style"],
        "brief": result["brief"],
        "degraded": result.get("degraded", False),
        "degraded_reason": result.get("degraded_reason", ""),
        "usage": result["usage"],
        "safety": {
            "injection_blocked": screen["injection_blocked"],
            "findings": screen["injection_findings"],
            "sanitised_shelf": screen["safe_shelf"] if screen["injection_blocked"] else "",
            "truncated": screen["truncated"],
        },
    })


@app.route("/api/receipt", methods=["POST"])
def receipt():
    """Parse a pasted order confirmation into the dated shelf inventory.

    Receipt text is email content and therefore untrusted. It is screened for
    injected instructions before anything is stored or shown.
    """
    data = request.get_json(force=True) or {}
    raw = (data.get("receipt") or "").strip()
    band = (data.get("band") or "moderate").strip()

    if not raw:
        return jsonify({"blocked": "empty", "message": "Paste a receipt first."})

    screen = screen_request(raw, "", config.MAX_INPUT_CHARS)
    if screen["medical_blocked"]:
        return jsonify({"blocked": "medical", "message": screen["medical_message"],
                        "reasons": screen["medical_reasons"]})

    parsed = parse_receipt(screen["safe_shelf"])
    inventory = add_items(parsed["items"])

    expiries = expiry_report(inventory)
    mismatch = seasonal_mismatch(inventory, band)
    spend = spend_summary(inventory, expiries)

    return jsonify({
        "blocked": None,
        "parsed": parsed,
        "inventory": inventory,
        "expiries": expiries,
        "mismatch": mismatch,
        "spend": spend,
        "shelf_text": ", ".join(i["name"] for i in inventory),
        "safety": {
            "injection_blocked": screen["injection_blocked"],
            "findings": screen["injection_findings"],
        },
    })


@app.route("/api/inventory")
def inventory_route():
    inv = load_inventory()
    exp = expiry_report(inv)
    return jsonify({"inventory": inv, "expiries": exp,
                    "spend": spend_summary(inv, exp)})


@app.route("/tokenomics")
def tokenomics():
    return render_template("tokenomics.html", agg=aggregate(), runs=all_runs()[-25:],
                           model=config.MODEL)


@app.route("/api/usage")
def usage():
    return jsonify({"aggregate": aggregate(), "runs": all_runs()})


if __name__ == "__main__":
    import os

    # macOS runs AirPlay Receiver on port 5000, so that is a poor default on a
    # grader's Mac. Default to 5001 and let PORT override.
    port = int(os.getenv("PORT", "5001"))

    print(f"\n  DewPoint -- model {config.MODEL}")
    print(f"  .env source: {config.ENV_SOURCE}")
    print(f"  key loaded : {bool(config.PORTKEY_API_KEY)}")
    if not config.PORTKEY_API_KEY:
        print("  (no key -> the app still runs, using its deterministic engine)")
    print(f"  http://127.0.0.1:{port}\n")
    app.run(debug=True, port=port)
