"""Receipt parsing and the dated shelf inventory.

The user pastes an order-confirmation email. We extract line items, prices and
an order date with regexes -- deterministic, free, and not something a model
should be guessing at -- then persist them as a dated inventory.

Having a *date* on every product is what the rest of the app trades on:

  * Period-after-opening. An antioxidant serum bought seven months ago has
    oxidised; that is usually why it "stopped working".
  * Seasonal mismatch. A gel moisturiser bought in July is the wrong product in
    a January indoor-humidity collapse, and the user often already owns the
    right one.

Note for the report: receipt text is email content, i.e. attacker-controllable.
It is screened by guard.py before any of it reaches a model.
"""
import json
import re
from datetime import date, datetime
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
INVENTORY = DATA_DIR / "inventory.json"

# ---------------------------------------------------------------------------
# Period after opening, in months. Industry PAO symbols plus common guidance.
# ---------------------------------------------------------------------------
PAO_MONTHS = {
    "vitamin_c":    (3,  "L-ascorbic acid oxidises fast. Once it turns amber it is inert "
                         "and can stain fabric."),
    "retinoid":     (6,  "Retinoids degrade with light and air exposure."),
    "facial_oil":   (6,  "Plant oils go rancid; a crayon-like smell is the tell."),
    "sunscreen":    (12, "Filters lose efficacy. Never carry one over two summers."),
    "moisturizer":  (12, "Jars pick up bacteria faster than pumps."),
    "cleanser":     (12, "Generally stable."),
    "exfoliant":    (12, "Acids stay stable but lose potency slowly."),
    "other":        (12, "General guidance."),
}

CATEGORY_HINTS = {
    "vitamin_c":   ["vitamin c", "ascorbic", "c serum", "c15", "c e ferulic"],
    "retinoid":    ["retinol", "retinal", "tretinoin", "adapalene", "granactive"],
    "facial_oil":  ["oil", "squalane oil", "rosehip", "marula"],
    "sunscreen":   ["spf", "sunscreen", "sun cream", "uv"],
    "moisturizer": ["moisturizer", "moisturiser", "cream", "balm", "lotion", "gel-cream"],
    "cleanser":    ["cleanser", "wash", "foam", "cleansing"],
    "exfoliant":   ["aha", "bha", "glycolic", "salicylic", "lactic", "peel", "exfoliat"],
}

# Which categories suit which dryness band -- drives the seasonal-mismatch check.
BAND_FIT = {
    "severe":      {"good": ["moisturizer", "facial_oil", "cleanser", "sunscreen"],
                    "bad": ["exfoliant", "retinoid"]},
    "high":        {"good": ["moisturizer", "facial_oil", "sunscreen"],
                    "bad": ["exfoliant", "retinoid"]},
    "moderate":    {"good": ["moisturizer", "vitamin_c", "sunscreen"], "bad": []},
    "comfortable": {"good": ["vitamin_c", "retinoid", "sunscreen", "moisturizer"], "bad": []},
    "humid":       {"good": ["cleanser", "exfoliant", "sunscreen"],
                    "bad": ["facial_oil"]},
}

PRICE_RE = re.compile(r"(?:[$£€]\s?)(\d{1,4}(?:[.,]\d{2})?)")
DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{2})-(\d{2})"), "%Y-%m-%d"),
    (re.compile(r"(\w{3,9})\s+(\d{1,2}),?\s+(\d{4})"), "%B %d %Y"),
    (re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})"), "%m/%d/%Y"),
]
NOISE = re.compile(
    r"^\s*(subtotal|total|tax|shipping|discount|order\s*#|order\s+number|thank|free\s|"
    r"estimated|delivery|tracking|qty|quantity|payment|visa|mastercard|billing|"
    r"ship\s+to|sold\s+by|view\s+order|return|unsubscribe)", re.I)


def categorise(name: str) -> str:
    low = name.lower()
    for cat, hints in CATEGORY_HINTS.items():
        if any(h in low for h in hints):
            return cat
    return "other"


def parse_order_date(text: str) -> str:
    for rx, fmt in DATE_PATTERNS:
        m = rx.search(text)
        if not m:
            continue
        try:
            return datetime.strptime(" ".join(m.groups()), fmt.replace("-", " ").replace("/", " ")).date().isoformat()
        except ValueError:
            continue
    return date.today().isoformat()


def parse_receipt(text: str) -> dict:
    """Pull line items out of pasted order-confirmation text."""
    order_date = parse_order_date(text)
    items = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if len(line) < 4 or NOISE.match(line):
            continue

        price_match = PRICE_RE.search(line)
        name = PRICE_RE.sub("", line).strip(" -–—\t|·,")
        name = re.sub(r"\s{2,}", " ", name)
        name = re.sub(r"^\d+\s*[xX]\s*", "", name).strip()

        # A product line needs a name with letters; price is a strong signal but
        # not required, since some receipts put the price on the next line.
        if not re.search(r"[A-Za-z]{3}", name) or len(name) > 110:
            continue
        if not price_match and len(items) > 0 and len(name.split()) < 2:
            continue

        price = None
        if price_match:
            price = float(price_match.group(1).replace(",", "."))

        items.append({
            "name": name[:110],
            "price": price,
            "category": categorise(name),
            "purchased": order_date,
        })

    # Drop lines with no price when the receipt clearly has prices elsewhere.
    if any(i["price"] is not None for i in items):
        items = [i for i in items if i["price"] is not None]

    total = sum(i["price"] for i in items if i["price"])
    return {"order_date": order_date, "items": items, "total": round(total, 2)}


# ---------------------------------------------------------------------------
# Inventory persistence
# ---------------------------------------------------------------------------
def load_inventory() -> list:
    if not INVENTORY.exists():
        return []
    try:
        return json.loads(INVENTORY.read_text())
    except json.JSONDecodeError:
        return []


def save_inventory(items: list) -> None:
    INVENTORY.write_text(json.dumps(items, indent=2))


def add_items(new_items: list) -> list:
    inv = load_inventory()
    seen = {(i["name"].lower(), i["purchased"]) for i in inv}
    for item in new_items:
        key = (item["name"].lower(), item["purchased"])
        if key not in seen:
            inv.append(item)
            seen.add(key)
    save_inventory(inv)
    return inv


def clear_inventory() -> None:
    save_inventory([])


# ---------------------------------------------------------------------------
# The two checks that make a dated shelf worth having
# ---------------------------------------------------------------------------
def months_between(iso: str, today: date = None) -> float:
    today = today or date.today()
    try:
        then = datetime.fromisoformat(iso).date()
    except ValueError:
        return 0.0
    return (today - then).days / 30.44


def expiry_report(inventory: list, today: date = None) -> list:
    """Which products are past their period after opening."""
    out = []
    for item in inventory:
        age = months_between(item["purchased"], today)
        limit, note = PAO_MONTHS.get(item["category"], PAO_MONTHS["other"])
        if age >= limit:
            out.append({
                "name": item["name"], "category": item["category"],
                "age_months": round(age, 1), "limit_months": limit,
                "price": item.get("price"), "note": note,
                "status": "expired",
            })
        elif age >= limit * 0.75:
            out.append({
                "name": item["name"], "category": item["category"],
                "age_months": round(age, 1), "limit_months": limit,
                "price": item.get("price"), "note": note,
                "status": "expiring",
            })
    out.sort(key=lambda r: -r["age_months"])
    return out


def seasonal_mismatch(inventory: list, band: str, today: date = None) -> dict:
    """Products bought for different air than today's.

    This is the cross-season catch: you bought it in another climate and kept
    using it out of habit.
    """
    fit = BAND_FIT.get(band, BAND_FIT["moderate"])
    wrong, right = [], []

    for item in inventory:
        cat = item["category"]
        age = months_between(item["purchased"], today)
        if cat in fit["bad"]:
            wrong.append({
                "name": item["name"], "category": cat,
                "bought_months_ago": round(age, 1), "price": item.get("price"),
            })
        elif cat in fit["good"]:
            right.append({"name": item["name"], "category": cat})

    return {"wrong_for_today": wrong, "right_for_today": right}


def spend_summary(inventory: list, expiries: list) -> dict:
    total = sum(i["price"] for i in inventory if i.get("price"))
    wasted = sum(e["price"] for e in expiries
                 if e["status"] == "expired" and e.get("price"))
    return {
        "items": len(inventory),
        "total_spend": round(total, 2),
        "expired_value": round(wasted, 2),
        "expired_count": sum(1 for e in expiries if e["status"] == "expired"),
    }
