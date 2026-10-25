"""DewPoint -- Flask app."""
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
from agents import run_pipeline
from climate import analyse, analysis_to_dict
from guard import screen_request
from meter import aggregate, all_runs
from receipts import (add_items, expiry_report, load_inventory, parse_receipt,
                      seasonal_mismatch, spend_summary)
from weather import FIXTURES, fetch

app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        env_source=config.ENV_SOURCE,
        key_present=bool(config.PORTKEY_API_KEY),
        model=config.MODEL,
        samples=list(FIXTURES.keys()),
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

    return jsonify({
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
    print(f"\n  DewPoint -- model {config.MODEL}")
    print(f"  .env source: {config.ENV_SOURCE}")
    print(f"  key loaded : {bool(config.PORTKEY_API_KEY)}")
    print("  http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000)
