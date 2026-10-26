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

# Assumed indoor air temperature in C, by mode.
INDOOR_TEMP_C = 20.5          # heating season setpoint
INDOOR_TEMP_COOLED_C = 24.0   # cooling season setpoint -- people set AC higher
COOLING_THRESHOLD_C = 24.0    # above this outdoors, assume the building is cooled
AC_COIL_TEMP_C = 13.0         # typical evaporator coil; air leaves near saturated at this
AC_BYPASS_FACTOR = 0.25       # share of air that misses the coil, plus infiltration


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


def indoor_conditions(temp_c: float, dew_point_c: float) -> dict:
    """The headline number, and how the building got there.

    Two very different processes dry indoor air, and which one applies depends
    on whether the building is heating or cooling:

    HEATING (cold outside). Outdoor air is warmed to room temperature with no
    moisture added. Its capacity rises sharply, its water content does not, so
    relative humidity collapses. This is the classic winter-dry-skin mechanism.

    COOLING (hot outside). Air conditioning pulls air across a coil near 13 C,
    far below its dew point, so water condenses out and runs off as the
    condensate you see dripping from an AC unit. The air is then delivered at
    room temperature carrying much *less* water than it started with. This is
    why a room in Hanoi or Singapore can be drier than the 80% humidity
    outdoors -- and why tropical-city skin gets tight indoors, which is not
    something a weather app would ever suggest.

    Returns the indoor RH plus the mode and the effective dew point, so the
    interface can explain which mechanism is at work.
    """
    if temp_c >= COOLING_THRESHOLD_C:
        # Air crossing the coil leaves close to saturated at the coil
        # temperature. Not all of it touches the coil though -- some bypasses
        # it, and more leaks in around doors and windows -- so the delivered
        # dew point sits a little above the coil. Without this term every
        # tropical city returns an identical figure, which is tidier than the
        # truth.
        if dew_point_c > AC_COIL_TEMP_C:
            effective_dew = AC_COIL_TEMP_C + AC_BYPASS_FACTOR * (dew_point_c - AC_COIL_TEMP_C)
        else:
            effective_dew = dew_point_c
        indoor_temp = INDOOR_TEMP_COOLED_C
        mode = "cooled"
    else:
        effective_dew = dew_point_c
        indoor_temp = INDOOR_TEMP_C
        mode = "heated"

    e = actual_vapor_pressure(effective_dew)
    es_indoor = saturation_vapor_pressure(indoor_temp)
    rh = max(0.0, min(100.0, (e / es_indoor) * 100))
    return {"indoor_rh": rh, "mode": mode,
            "effective_dew_point_c": effective_dew, "indoor_temp_c": indoor_temp}


def indoor_relative_humidity(dew_point_c: float, indoor_temp_c: float = INDOOR_TEMP_C) -> float:
    """Heating-season form, kept for direct use and tests."""
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


# How much of a swing is worth dressing around. Below this, one outfit is fine
# and pretending otherwise is noise.
SWING_MATTERS_C = 6.0


def swing_plan(temp_min_c: float, temp_max_c: float) -> dict:
    """Separate guidance for the cold end and the warm end of the day.

    A single outfit is only honest when the day is flat. A 10 degree swing is
    two different sets of clothes, and the useful advice is what comes off and
    when -- which is computed here, not guessed by the model.
    """
    swing = temp_max_c - temp_min_c
    morning = fabric_for(temp_min_c)
    afternoon = fabric_for(temp_max_c)

    matters = swing >= SWING_MATTERS_C or morning["layers"] != afternoon["layers"]
    shed = max(0, morning["layers"] - afternoon["layers"])

    big = swing >= SWING_MATTERS_C

    if not matters:
        verdict = f"A {swing:.1f}° swing. One outfit covers the whole day."
    elif shed and big:
        verdict = (f"A {swing:.1f}° swing. Dress for {temp_min_c:.0f}° and plan to take "
                   f"{shed} layer{'s' if shed > 1 else ''} off by the afternoon — so the "
                   f"outer layer has to be one you can carry.")
    elif shed:
        # Small swing, but it straddles a threshold. Say so, rather than making
        # a 2 degree change sound like a wardrobe event.
        verdict = (f"Only a {swing:.1f}° swing, but it crosses a layering threshold at "
                   f"{temp_min_c:.0f}–{temp_max_c:.0f}°. Either layer works; take the lighter "
                   f"option if you will be walking.")
    else:
        verdict = (f"A {swing:.1f}° swing within one layer band. Same pieces, but choose "
                   f"a fabric that breathes rather than one that insulates.")

    return {
        "swing_c": round(swing, 1),
        "matters": matters,
        "layers_to_shed": shed,
        "verdict": verdict,
        "morning": {"temp_c": round(temp_min_c, 1), "layers": morning["layers"],
                    "fabrics": morning["fabrics"], "avoid": morning["avoid"],
                    "why": morning["why"]},
        "afternoon": {"temp_c": round(temp_max_c, 1), "layers": afternoon["layers"],
                      "fabrics": afternoon["fabrics"], "avoid": afternoon["avoid"],
                      "why": afternoon["why"]},
    }


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
    mode: str = "heated"
    effective_dew_point_c: float = 0.0
    indoor_temp_c: float = 0.0
    swing_c: float = 0.0
    skin: dict = field(default_factory=dict)
    fabric: dict = field(default_factory=dict)
    swing: dict = field(default_factory=dict)
    alerts: list = field(default_factory=list)


def analyse(weather: dict) -> DayAnalysis:
    """Turn a raw forecast into every number the rest of the app needs."""
    temp = weather["temp_c"]
    dew = weather["dew_point_c"]

    cond = indoor_conditions(temp, dew)
    indoor_rh = cond["indoor_rh"]
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
        mode=cond["mode"],
        effective_dew_point_c=round(cond["effective_dew_point_c"], 1),
        indoor_temp_c=cond["indoor_temp_c"],
    )
    a.swing_c = round(a.temp_max_c - a.temp_min_c, 1)
    a.skin = SKIN_RULES[band]
    a.fabric = fabric_for(a.temp_max_c)
    a.swing = swing_plan(a.temp_min_c, a.temp_max_c)
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
        "mode": a.mode, "effective_dew_point_c": a.effective_dew_point_c,
        "indoor_temp_c": a.indoor_temp_c,
        "skin": a.skin, "fabric": a.fabric, "swing": a.swing, "alerts": a.alerts,
    }


# ---------------------------------------------------------------------------
# Outlook
#
# Barrier care is slow. Switching to an occlusive the morning your skin already
# hurts is too late -- it takes a day or two of consistent use to matter. So the
# useful question is not "what is the air doing" but "what is it about to do,
# and do I need to start now".
# ---------------------------------------------------------------------------
BAND_ORDER = ["severe", "high", "moderate", "comfortable", "humid"]


def band_rank(band: str) -> int:
    """Lower is drier."""
    return BAND_ORDER.index(band) if band in BAND_ORDER else 2


def build_outlook(series: list) -> dict:
    """Indoor conditions for each forecast day, plus any warning worth giving."""
    if not series:
        return {"days": [], "warning": None}

    days = []
    for i, day in enumerate(series):
        cond = indoor_conditions(day["temp_c"], day["dew_point_c"])
        band, _note = dryness_band(cond["indoor_rh"])
        days.append({
            "date": day["date"],
            "indoor_rh": round(cond["indoor_rh"], 1),
            "band": band,
            "mode": cond["mode"],
            "temp_min_c": round(day["temp_min_c"], 1),
            "temp_max_c": round(day["temp_max_c"], 1),
            "offset": i,
        })

    today = days[0]
    warning = None

    # The driest day ahead, if it is meaningfully drier than today.
    ahead = days[1:]
    if ahead:
        driest = min(ahead, key=lambda d: d["indoor_rh"])
        drop = today["indoor_rh"] - driest["indoor_rh"]
        worsens = band_rank(driest["band"]) < band_rank(today["band"])

        if worsens and drop >= 5:
            when = {1: "tomorrow", 2: "in two days", 3: "in three days"}.get(
                driest["offset"], f"in {driest['offset']} days")
            warning = {
                "kind": "drying",
                "when": when,
                "offset": driest["offset"],
                "from_rh": today["indoor_rh"],
                "to_rh": driest["indoor_rh"],
                "from_band": today["band"],
                "to_band": driest["band"],
                "text": (
                    f"The air dries out {when}: indoor humidity falls from "
                    f"{today['indoor_rh']}% to {driest['indoor_rh']}%, moving from "
                    f"{today['band']} to {driest['band']}. Barrier care takes a day or two "
                    f"to build up, so start tonight rather than when it bites."
                ),
            }
        elif ahead:
            wettest = max(ahead, key=lambda d: d["indoor_rh"])
            rise = wettest["indoor_rh"] - today["indoor_rh"]
            if band_rank(wettest["band"]) > band_rank(today["band"]) and rise >= 8:
                when = {1: "tomorrow", 2: "in two days", 3: "in three days"}.get(
                    wettest["offset"], f"in {wettest['offset']} days")
                warning = {
                    "kind": "easing",
                    "when": when,
                    "offset": wettest["offset"],
                    "from_rh": today["indoor_rh"],
                    "to_rh": wettest["indoor_rh"],
                    "from_band": today["band"],
                    "to_band": wettest["band"],
                    "text": (
                        f"Conditions ease {when}, up to {wettest['indoor_rh']}%. If you have "
                        f"been holding off on actives, that is the window to restart them."
                    ),
                }

    return {"days": days, "warning": warning}
