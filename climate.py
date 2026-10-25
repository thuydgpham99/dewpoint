"""The climate engine.

Everything numeric in DewPoint is computed here, in plain Python. The language
model never calculates a humidity value, a dryness score, or a threshold -- it
only turns this structured output into readable advice. That split is the core
of the agent design: deterministic where correctness matters, generative where
tone matters.

The central idea: relative humidity outdoors tells you very little about what
your skin experiences. Outdoor air is heated indoors, and heating air without
adding moisture collapses its relative humidity. We therefore derive the
*indoor* relative humidity from the outdoor dew point, which is the number that
actually predicts transepidermal water loss.
"""
import math
from dataclasses import dataclass, field

# Assumed indoor air temperature in C. Heated buildings sit near this.
INDOOR_TEMP_C = 20.5


def saturation_vapor_pressure(temp_c: float) -> float:
    """Magnus-Tetens formula. Returns hPa."""
    return 6.112 * math.exp((17.67 * temp_c) / (temp_c + 243.5))


def actual_vapor_pressure(dew_point_c: float) -> float:
    """Air holds exactly its saturation pressure at the dew point."""
    return saturation_vapor_pressure(dew_point_c)


def absolute_humidity(temp_c: float, dew_point_c: float) -> float:
    """Grams of water per cubic metre of air."""
    e = actual_vapor_pressure(dew_point_c)
    return 2.1674 * (e * 100) / (273.15 + temp_c) / 100


def indoor_relative_humidity(dew_point_c: float, indoor_temp_c: float = INDOOR_TEMP_C) -> float:
    """The headline number.

    Take outdoor air at its measured dew point, heat it to room temperature
    without adding moisture, and ask what its relative humidity becomes.
    """
    e = actual_vapor_pressure(dew_point_c)
    es_indoor = saturation_vapor_pressure(indoor_temp_c)
    return max(0.0, min(100.0, (e / es_indoor) * 100))


# ---------------------------------------------------------------------------
# Dryness bands, keyed on indoor RH. Dermatology literature puts the comfort
# floor for skin barrier function near 40% RH; below 30% transepidermal water
# loss rises sharply.
# ---------------------------------------------------------------------------
DRYNESS_BANDS = [
    (0,  20, "severe",    "Desert-dry indoors. Your barrier will lose water faster than it rebuilds."),
    (20, 30, "high",      "Dry enough to cause tightness, flaking and stinging from actives."),
    (30, 40, "moderate",  "Below the comfort floor for skin. Noticeable on cheeks and around the nose."),
    (40, 60, "comfortable", "The sweet spot. Your usual routine should behave normally."),
    (60, 101, "humid",    "Moisture-rich. Heavy creams will sit on the surface and congest pores."),
]


def dryness_band(indoor_rh: float):
    for low, high, label, note in DRYNESS_BANDS:
        if low <= indoor_rh < high:
            return label, note
    return "comfortable", DRYNESS_BANDS[3][3]


# ---------------------------------------------------------------------------
# Skincare rules keyed on the computed conditions.
# ---------------------------------------------------------------------------
SKIN_RULES = {
    "severe": {
        "use": ["occlusive balm", "ceramide cream", "hyaluronic acid under cream", "cream cleanser"],
        "skip": ["foaming cleanser", "retinoid", "aha", "bha", "clay mask", "alcohol toner"],
        "why": "At this dryness a retinoid or acid will strip a barrier that cannot rebuild. "
               "Seal instead of exfoliate.",
        "occlusive": True,
    },
    "high": {
        "use": ["rich moisturizer", "hyaluronic acid on damp skin", "ceramide cream", "facial oil at night"],
        "skip": ["foaming cleanser", "aha", "bha", "clay mask", "retinoid"],
        "why": "Pause the retinoid and acids until the air recovers, and raise the "
               "moisturiser weight. A barrier losing water this fast cannot also rebuild "
               "from active-induced irritation.",
        "occlusive": True,
    },
    "moderate": {
        "use": ["ceramide cream", "niacinamide", "hyaluronic acid on damp skin"],
        "skip": ["clay mask", "alcohol toner"],
        "why": "Normal routine, but apply hydrators to damp skin so they draw from the product "
               "rather than from your skin.",
        "occlusive": False,
    },
    "comfortable": {
        "use": ["usual routine", "vitamin c", "retinoid at night", "spf"],
        "skip": [],
        "why": "Conditions are kind. This is the right window for actives.",
        "occlusive": False,
    },
    "humid": {
        "use": ["gel moisturizer", "niacinamide", "bha if congested", "gel cleanser"],
        "skip": ["occlusive balm", "facial oil", "heavy cream"],
        "why": "Heavy creams cannot absorb into already-saturated skin and will trap sweat "
               "and sebum.",
        "occlusive": False,
    },
}

# ---------------------------------------------------------------------------
# Fabric rules keyed on temperature, wet-bulb comfort and precipitation.
# ---------------------------------------------------------------------------
FABRIC_RULES = [
    {"max_temp": 4,  "layers": 3, "fabrics": ["merino wool", "down", "fleece-lined"],
     "avoid": ["cotton as a base layer"],
     "why": "Cotton holds sweat against the skin and then chills you."},
    {"max_temp": 12, "layers": 3, "fabrics": ["wool blend", "knit", "lined trousers"],
     "avoid": ["linen"], "why": "Layer for the swing between morning and afternoon."},
    {"max_temp": 19, "layers": 2, "fabrics": ["cotton", "light knit", "denim"],
     "avoid": [], "why": "Mild. A removable mid-layer covers the range."},
    {"max_temp": 26, "layers": 1, "fabrics": ["cotton", "linen", "tencel"],
     "avoid": ["polyester"], "why": "Natural fibres move moisture; synthetics hold odour."},
    {"max_temp": 99, "layers": 1, "fabrics": ["linen", "loose cotton"],
     "avoid": ["polyester", "tight synthetics", "dark colours"],
     "why": "Loose and pale keeps radiant heat off the skin."},
]


def fabric_for(temp_c: float):
    for rule in FABRIC_RULES:
        if temp_c <= rule["max_temp"]:
            return rule
    return FABRIC_RULES[-1]


# ---------------------------------------------------------------------------
# The cross-domain conflicts. This is the whole reason skincare and outfit
# belong in one product: the day's protocol on your skin changes what the
# fabric against it should be.
# ---------------------------------------------------------------------------
def cross_domain_alerts(band: str, uv: float, precip_mm: float, wind_kph: float,
                        temp_c: float) -> list:
    alerts = []
    rule = SKIN_RULES[band]

    if rule["occlusive"]:
        alerts.append({
            "title": "Balm and collars",
            "body": "Today's protocol puts an occlusive balm on your face and neck. Petrolatum "
                    "and heavy oils leave a permanent darkened ring on silk and satin. Wear a "
                    "cotton or wool collar, and keep a scarf off the lower face.",
            "severity": "high",
        })

    if uv >= 3:
        alerts.append({
            "title": "Sunscreen and white fabric",
            "body": "UV index is {:.0f}, so sunscreen is non-negotiable. Chemical filters "
                    "(avobenzone, octocrylene) react with sweat and leave yellow-orange stains "
                    "on white cotton that do not wash out. Wear a mineral filter with white, or "
                    "wear a colour.".format(uv),
            "severity": "high" if uv >= 6 else "medium",
        })

    if uv >= 6:
        alerts.append({
            "title": "Mineral cast on dark clothing",
            "body": "A high-UV day pushes you toward zinc oxide, which leaves a white cast that "
                    "transfers onto black and navy collars. Set it with powder, or choose a "
                    "mid-tone top.",
            "severity": "medium",
        })

    if precip_mm >= 1:
        alerts.append({
            "title": "Rain and water spotting",
            "body": "Rain is forecast. Silk, satin and untreated leather water-spot permanently. "
                    "Switch to wool, denim or a treated synthetic shell, and use a water-resistant "
                    "sunscreen since the film breaks down when wet.",
            "severity": "high",
        })

    if wind_kph >= 25 and temp_c <= 12:
        alerts.append({
            "title": "Windburn",
            "body": "Cold wind strips the lipid layer faster than low humidity alone. Apply a "
                    "barrier balm before you leave, and choose a high collar. Avoid wool directly "
                    "against a compromised cheek -- the fibres abrade it.",
            "severity": "high",
        })

    if band == "humid" and temp_c >= 24:
        alerts.append({
            "title": "Synthetics and congestion",
            "body": "In saturated air, polyester traps sweat against the chest and back and feeds "
                    "the bacteria behind body acne. Wear loose cotton or linen, and shower within "
                    "an hour of getting home.",
            "severity": "medium",
        })

    return alerts


@dataclass
class DayAnalysis:
    location: str = ""
    temp_c: float = 0.0
    temp_min_c: float = 0.0
    temp_max_c: float = 0.0
    dew_point_c: float = 0.0
    outdoor_rh: float = 0.0
    indoor_rh: float = 0.0
    absolute_humidity: float = 0.0
    uv_index: float = 0.0
    precip_mm: float = 0.0
    wind_kph: float = 0.0
    band: str = ""
    band_note: str = ""
    swing_c: float = 0.0
    skin: dict = field(default_factory=dict)
    fabric: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)


def analyse(weather: dict) -> DayAnalysis:
    """Turn a raw forecast into every number the rest of the app needs."""
    temp = weather["temp_c"]
    dew = weather["dew_point_c"]

    indoor_rh = indoor_relative_humidity(dew)
    band, band_note = dryness_band(indoor_rh)

    a = DayAnalysis(
        location=weather.get("location", ""),
        temp_c=round(temp, 1),
        temp_min_c=round(weather.get("temp_min_c", temp), 1),
        temp_max_c=round(weather.get("temp_max_c", temp), 1),
        dew_point_c=round(dew, 1),
        outdoor_rh=round(weather.get("outdoor_rh", 0.0), 1),
        indoor_rh=round(indoor_rh, 1),
        absolute_humidity=round(absolute_humidity(temp, dew), 2),
        uv_index=round(weather.get("uv_index", 0.0), 1),
        precip_mm=round(weather.get("precip_mm", 0.0), 1),
        wind_kph=round(weather.get("wind_kph", 0.0), 1),
        band=band,
        band_note=band_note,
    )
    a.swing_c = round(a.temp_max_c - a.temp_min_c, 1)
    a.skin = SKIN_RULES[band]
    a.fabric = fabric_for(a.temp_max_c)
    a.alerts = cross_domain_alerts(band, a.uv_index, a.precip_mm, a.wind_kph, a.temp_c)
    return a


def analysis_to_dict(a: DayAnalysis) -> dict:
    return {
        "location": a.location,
        "temp_c": a.temp_c, "temp_min_c": a.temp_min_c, "temp_max_c": a.temp_max_c,
        "swing_c": a.swing_c,
        "dew_point_c": a.dew_point_c,
        "outdoor_rh": a.outdoor_rh,
        "indoor_rh": a.indoor_rh,
        "absolute_humidity": a.absolute_humidity,
        "uv_index": a.uv_index, "precip_mm": a.precip_mm, "wind_kph": a.wind_kph,
        "band": a.band, "band_note": a.band_note,
        "skin": a.skin, "fabric": a.fabric, "alerts": a.alerts,
    }
