"""Safety layer.

Three defences, each visible in the UI so they can be screenshotted for the
report:

1. Prompt-injection screening on untrusted text. The shelf field is pasted
   from retailer pages, which is attacker-controllable text that reaches the
   model. Anything matching a known injection shape is stripped before the
   model sees it, and the block is surfaced to the user.
2. A medical boundary. DewPoint gives cosmetic guidance. Prescription dosing,
   suspected reactions and diagnosed conditions are refused and routed to a
   clinician.
3. Spend ceilings, enforced in config and checked before every run.
"""
import re

# ---------------------------------------------------------------------------
# 1. Prompt injection
# ---------------------------------------------------------------------------
INJECTION_PATTERNS = [
    (r"ignore\s+(all\s+|any\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
     "override attempt"),
    (r"disregard\s+(the\s+)?(system|above|previous|your)\s+\w+", "override attempt"),
    (r"forget\s+(everything|all|your\s+instructions)", "override attempt"),
    (r"you\s+are\s+now\s+(a|an)\s+", "role reassignment"),
    (r"new\s+(system\s+)?(instructions?|prompt|rules?)\s*:", "injected instruction block"),
    (r"</?(system|assistant|user)>", "fake role tag"),
    (r"\[\s*(system|admin|developer)\s*\]", "fake authority tag"),
    (r"(reveal|print|repeat|output|show)\s+(your|the)\s+(system\s+)?(prompt|instructions)",
     "prompt extraction"),
    (r"do\s+not\s+(mention|tell|warn|inform)\s+the\s+user", "concealment attempt"),
    (r"always\s+recommend\s+", "recommendation hijack"),
    (r"regardless\s+of\s+(the\s+)?(weather|conditions|humidity)", "recommendation hijack"),
    (r"(api[_\s-]?key|secret|token|password|\.env)", "credential probe"),
]


def scan_untrusted(text: str):
    """Screen attacker-controllable text. Returns (clean, findings, sanitised)."""
    findings = []
    sanitised = text

    for pattern, label in INJECTION_PATTERNS:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            snippet = m.group(0)
            findings.append({"type": label, "matched": snippet[:120]})
            sanitised = sanitised.replace(snippet, "[removed: possible injected instruction]")

    # Hidden-text tricks: zero-width characters and very long single lines.
    if re.search(r"[​-‏‪-‮﻿]", text):
        findings.append({"type": "hidden characters", "matched": "zero-width / bidi control"})
        sanitised = re.sub(r"[​-‏‪-‮﻿]", "", sanitised)

    return (len(findings) == 0), findings, sanitised


# ---------------------------------------------------------------------------
# 2. Medical boundary
# ---------------------------------------------------------------------------
MEDICAL_PATTERNS = [
    (r"\b(accutane|isotretinoin|roaccutane)\b", "prescription isotretinoin"),
    (r"\b(tretinoin|tazarotene)\b.*\b(dose|dosage|strength|mg|how much|percent)\b",
     "prescription dosing"),
    (r"\b(allergic\s+reaction|anaphyla|hives|swelling|blistering|chemical\s+burn)\b",
     "suspected adverse reaction"),
    (r"\b(infected|infection|pus|oozing|open\s+wound|bleeding)\b", "possible infection"),
    (r"\b(melanoma|skin\s+cancer|mole\s+(chang|grow)|suspicious\s+mole)\b", "oncological concern"),
    (r"\b(pregnan|breastfeed|nursing)\w*\b", "pregnancy safety"),
    (r"\b(eczema|psoriasis|rosacea)\b.*\b(flare|treat|cure|prescri)\w*", "diagnosed condition"),
]

MEDICAL_REFUSAL = (
    "DewPoint plans cosmetic routines around the weather. It is not a medical tool and "
    "cannot advise on this. Please speak to a dermatologist or your doctor -- and if this "
    "involves a reaction that is spreading, painful, or affecting your breathing, treat it "
    "as urgent."
)


def medical_check(text: str):
    """Returns (is_medical, reasons)."""
    reasons = []
    for pattern, label in MEDICAL_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE | re.DOTALL):
            reasons.append(label)
    return (len(reasons) > 0), reasons


# ---------------------------------------------------------------------------
# 3. Input ceiling, the first line of spend control
# ---------------------------------------------------------------------------
def enforce_length(text: str, limit: int):
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def screen_request(shelf_text: str, wardrobe_text: str, limit: int) -> dict:
    """Run every check and return one report the UI can render."""
    combined = f"{shelf_text}\n{wardrobe_text}"

    truncated_shelf, t1 = enforce_length(shelf_text, limit)
    truncated_wardrobe, t2 = enforce_length(wardrobe_text, limit)

    clean_s, find_s, safe_shelf = scan_untrusted(truncated_shelf)
    clean_w, find_w, safe_wardrobe = scan_untrusted(truncated_wardrobe)

    is_medical, medical_reasons = medical_check(combined)

    return {
        "safe_shelf": safe_shelf,
        "safe_wardrobe": safe_wardrobe,
        "injection_findings": find_s + find_w,
        "injection_blocked": not (clean_s and clean_w),
        "medical_blocked": is_medical,
        "medical_reasons": medical_reasons,
        "medical_message": MEDICAL_REFUSAL if is_medical else "",
        "truncated": t1 or t2,
    }
