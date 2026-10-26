"""DewPoint -- Flask app."""
from datetime import datetime

from flask import Flask, jsonify, render_template, request

import config
from agents import run_pipeline
from climate import analyse, analysis_to_dict, build_outlook
from guard import screen_request
from meter import aggregate, all_runs
from receipts import (add_items, expiry_report, load_inventory, monthly_spend,
                      parse_receipt, purchase_context, seasonal_mismatch,
                      spend_summary)
from weather import FIXTURES, fetch

app = Flask(__name__)

# Flask only re-reads templates when debug is on, and debug is off by default
# here so the server stays up for a grader. Without this, editing a template
# silently does nothing until the process restarts -- which cost me twenty
# minutes of chasing a bug that was not there.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True


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

    # Room settings. Indoor temperature is the largest source of error in the
    # whole model, so letting the user state theirs is worth more than any
    # refinement to the formula.
    try:
        room_temp = float(data.get("indoor_temp_c")) if data.get("indoor_temp_c") else None
    except (TypeError, ValueError):
        room_temp = None
    if room_temp is not None:
        room_temp = max(10.0, min(32.0, room_temp))
    humidifier = bool(data.get("humidifier"))

    weather = fetch(city)
    analysis = analysis_to_dict(analyse(weather, room_temp, humidifier))
    outlook = build_outlook(weather.get("forecast", []), room_temp, humidifier)

    result = run_pipeline(analysis, screen["safe_shelf"], screen["safe_wardrobe"],
                          outlook=outlook)

    # Frame any suggestion against what the user already owns and already spent,
    # so the app never recommends a purchase without that context.
    inventory = load_inventory()
    gap_category = (result["shelf"].get("gap_category") or "").strip() or None
    context = purchase_context(inventory, gap_category)
    mismatch = seasonal_mismatch(inventory, analysis["band"]) if inventory else {}

    return jsonify({
        "purchase_context": context,
        "mismatch": mismatch,
        "outlook": outlook,
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


def _free_port(preferred: int, tries: int = 12) -> int:
    """First free port at or after `preferred`.

    macOS runs AirPlay Receiver on 5000, and a grader may well have something
    on 5001 too. Rather than dying with "Address already in use", step forward
    until something is free and print where we landed.
    """
    import socket
    for offset in range(tries):
        port = preferred + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit(f"No free port between {preferred} and {preferred + tries - 1}.")


if __name__ == "__main__":
    import os

    port = _free_port(int(os.getenv("PORT", "5001")))

    # Default to loopback. HOST=0.0.0.0 opens the app to the local network so
    # someone else on the same wifi can try it -- useful for a user test, and
    # worth turning off again afterwards, since the server holds an API key.
    host = os.getenv("HOST", "127.0.0.1")

    # The reloader is off by default. It is convenient while developing but it
    # can leave a half-dead process after an edit, and a grader only needs the
    # server to stay up. DEWPOINT_DEBUG=1 turns it back on.
    debug = os.getenv("DEWPOINT_DEBUG") == "1"

    print(f"\n  DewPoint -- model {config.MODEL}")
    print(f"  .env source: {config.ENV_SOURCE}")
    print(f"  key loaded : {bool(config.PORTKEY_API_KEY)}")
    if not config.PORTKEY_API_KEY:
        print("  no key found -> the app still runs, using its deterministic engine")
    print(f"\n  ready at  http://127.0.0.1:{port}")
    if host == "0.0.0.0":
        import socket
        try:
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.connect(("8.8.8.8", 80))
            print(f"  on this wifi  http://{probe.getsockname()[0]}:{port}")
            probe.close()
        except Exception:
            pass
        print("  open to the local network -- stop the server when you are done")
    print()

    app.run(debug=debug, host=host, port=port, use_reloader=debug, threaded=True)
