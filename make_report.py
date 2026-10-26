"""Generate report.html from measured data in runs/*.

Run after using the app so the numbers reflect real runs:
    python3 make_report.py
"""
import base64
import json
from datetime import date
from pathlib import Path


def embed(name: str) -> str:
    """Inline a screenshot as base64 so report.html stays self-contained."""
    f = Path(__file__).resolve().parent / "screenshots" / name
    if not f.exists():
        return ""
    b64 = base64.b64encode(f.read_bytes()).decode()
    return f"data:image/jpeg;base64,{b64}"

import sys
sys.path.insert(0, str(Path(__file__).parent))
from meter import PRICING, all_runs

HERE = Path(__file__).resolve().parent
RUNS = all_runs()
BENCH = json.loads((HERE / "runs/bench.json").read_text()) if (HERE / "runs/bench.json").exists() else None

# ---- how often does the outdoor reading give different advice? ----------
from climate import analyse, analysis_to_dict, dryness_band  # noqa: E402

_fx = json.loads((HERE / "data/sample_days.json").read_text())
_band_rows, _disagree, _gaps = [], 0, []
for _name, _w in _fx.items():
    _a = analysis_to_dict(analyse(_w))
    _ob, _ = dryness_band(_a["outdoor_rh"])
    _same = _ob == _a["band"]
    if not _same:
        _disagree += 1
    _gaps.append(abs(_a["outdoor_rh"] - _a["indoor_rh"]))
    _band_rows.append((_name, _a["outdoor_rh"], _ob, _a["indoor_rh"], _a["band"],
                       _a["mode"], _same))
_band_rows.sort(key=lambda r: r[3])

# ---- the user study ----------------------------------------------------
_bl = json.loads((HERE / "runs/baseline.json").read_text()) if (HERE / "runs/baseline.json").exists() else None
_blr = json.loads((HERE / "runs/baseline_realistic.json").read_text()) if (HERE / "runs/baseline_realistic.json").exists() else None
if _blr:
    BL_ROWS = "".join(
        f'<tr{"" if r.get("band_match") else " class=diff"}><td>{r["city"]}</td>'
        f'<td class=n>{r["truth_rh"]:.1f}%</td><td>{r["truth_band"]}</td>'
        f'<td class=n>{r["model_rh"]:.0f}%</td><td>{r["model_band"]}</td>'
        f'<td class=n>{r["error"]:.1f}</td>'
        f'<td>{"same" if r.get("band_match") else "<b>different</b>"}</td></tr>'
        for r in _blr["rows"] if not r.get("no_number"))
    BL_N = _blr["n"]; BL_MATCH = _blr["band_matches"]
    BL_MEAN = _blr["mean_error"]; BL_MED = _blr["median_error"]; BL_WORST = _blr["worst_error"]
    BL_MISS = BL_N - BL_MATCH
    BLA_MATCH = _bl["band_matches"] if _bl else 0
    BLA_N = _bl["n"] if _bl else 0
    BLA_MEAN = _bl["mean_error"] if _bl else 0
    BLA_LAT = _bl["mean_latency"] if _bl else 0
    BLA_COST = _bl["baseline_cost"] if _bl else 0
else:
    BL_ROWS = ""; BL_N = BL_MATCH = BL_MISS = 0
    BL_MEAN = BL_MED = BL_WORST = BLA_MATCH = BLA_N = BLA_MEAN = BLA_LAT = BLA_COST = 0

_study = json.loads((HERE / "data/user_study.json").read_text())
STUDY_GUESSES = _study["guesses"]
STUDY_ACTUAL = _study["actual_indoor_rh"]
STUDY_OUTDOOR = _study["outdoor_rh"]
_actual_band, _ = dryness_band(STUDY_ACTUAL)
STUDY_BAND = _actual_band
_srows, _serrs, _right = [], [], 0
for _g in STUDY_GUESSES:
    _b, _ = dryness_band(_g)
    _e = _g - STUDY_ACTUAL
    _serrs.append(abs(_e))
    _ok = _b == _actual_band
    if _ok:
        _right += 1
    _srows.append((_g, _b, _e, _ok))
STUDY_TABLE = "".join(
    f'<tr{"" if ok else " class=diff"}><td class=n>{g}%</td><td>{b}</td>'
    f'<td class=n>{e:+.1f}</td><td>{"same band" if ok else "<b>wrong band</b>"}</td></tr>'
    for g, b, e, ok in _srows)
STUDY_N = len(STUDY_GUESSES)
STUDY_MAE = sum(_serrs) / STUDY_N
STUDY_MEAN = sum(STUDY_GUESSES) / STUDY_N
STUDY_SPREAD = max(STUDY_GUESSES) - min(STUDY_GUESSES)
STUDY_RIGHT = _right
STUDY_WRONG = STUDY_N - _right
BAND_TABLE = "".join(
    f'<tr{"" if same else " class=diff"}><td>{n}</td><td class=n>{orh:.0f}%</td>'
    f'<td>{ob}</td><td class=n>{irh:.1f}%</td><td>{ib}</td><td>{mode}</td>'
    f'<td>{"same" if same else "<b>different</b>"}</td></tr>'
    for n, orh, ob, irh, ib, mode, same in _band_rows)
N_CITIES = len(_band_rows)
DISAGREE = _disagree
DISAGREE_PCT = _disagree / N_CITIES * 100
MEAN_GAP = sum(_gaps) / len(_gaps)
MAX_GAP = max(_gaps)

n = len(RUNS) or 1
avg = {
    "input": sum(r["input_tokens"] for r in RUNS) / n,
    "cached": sum(r["cached_input_tokens"] for r in RUNS) / n,
    "output": sum(r["output_tokens"] for r in RUNS) / n,
    "reasoning": sum(r.get("reasoning_tokens", 0) for r in RUNS) / n,
    "cost": sum(r["cost_usd"] for r in RUNS) / n,
}
avg["total"] = avg["input"] + avg["cached"] + avg["output"]
reason_pct = (avg["reasoning"] / avg["output"] * 100) if avg["output"] else 0
RUNS_PER_USER_MONTH = 20
rates = PRICING["gpt-6-luna"]

def fmt(x, d=0): return f"{x:,.{d}f}"

run_rows = "".join(
    f"<tr><td>{r['run_id']}</td><td>{r['agent_calls']}</td>"
    f"<td class=n>{fmt(r['input_tokens'])}</td><td class=n>{fmt(r['cached_input_tokens'])}</td>"
    f"<td class=n>{fmt(r['output_tokens'])}</td><td class=n>{fmt(r.get('reasoning_tokens',0))}</td>"
    f"<td class=n>${r['cost_usd']:.5f}</td><td class=n>{r['seconds']}</td></tr>"
    for r in RUNS[-12:])

bench_rows = ""
if BENCH:
    bench_rows = "".join(
        f"<tr><td>{b['city']}</td>"
        f"<td class=n>{fmt(b['three_in'])}/{fmt(b['three_out'])}</td>"
        f"<td class=n>${b['three_cost']:.5f}</td>"
        f"<td class=n>{fmt(b['one_in'])}/{fmt(b['one_out'])}</td>"
        f"<td class=n>${b['one_cost']:.5f}</td>"
        f"<td class=n>{(1-b['one_cost']/b['three_cost'])*100:.0f}%</td></tr>"
        for b in BENCH["rows"])
    bench_saving = (1 - BENCH["avg_one_cost"] / BENCH["avg_three_cost"]) * 100
else:
    bench_saving = 0

CSS = """
*{box-sizing:border-box}
body{font-family:"Iowan Old Style",Palatino,Georgia,serif;font-size:11.5pt;line-height:1.62;
 color:#1d1a17;background:#faf7f3;margin:0;padding:0}
.page{max-width:7.3in;margin:0 auto;padding:0.55in 0.6in 0.7in;background:#fff;
 box-shadow:0 0 22px rgba(0,0,0,.05)}
h1{font-size:30pt;margin:0 0 4px;letter-spacing:-.8px;line-height:1.1}
.sub{font-size:13pt;color:#6b635a;margin:0 0 20px;font-style:italic}
h2{font-size:15pt;margin:30px 0 9px;padding-bottom:5px;border-bottom:1.5px solid #b5674d;
 letter-spacing:-.2px}
h3{font-size:12pt;margin:20px 0 6px;color:#3a352f}
p{margin:0 0 11px}
.meta{font-family:ui-sans-serif,-apple-system,"Segoe UI",sans-serif;font-size:9.5pt;
 color:#6b635a;background:#faf7f3;border:1px solid #e8e1d8;border-radius:8px;
 padding:13px 16px;margin-bottom:22px}
.meta a{color:#b5674d}
.lede{font-size:12.5pt;border-left:3px solid #b5674d;padding-left:16px;color:#3a352f;margin:18px 0}
table{width:100%;border-collapse:collapse;margin:13px 0;font-size:9.5pt;
 font-family:ui-sans-serif,-apple-system,sans-serif}
th,td{padding:6px 9px;border-bottom:1px solid #e8e1d8;text-align:left;vertical-align:top}
th{background:#faf7f3;font-size:8.5pt;text-transform:uppercase;letter-spacing:.05em;color:#6b635a}
td.n{text-align:right;font-family:ui-monospace,Menlo,monospace}
tr.diff td{background:#fdf5f1}
.ev{background:#1d1a17;color:#e8e1d8;border-radius:8px;padding:14px 17px;margin:13px 0;
 font-family:ui-monospace,Menlo,monospace;font-size:8.5pt;line-height:1.5;white-space:pre-wrap;
 overflow-wrap:anywhere}
.ev .ok{color:#8fd4a0}.ev .bad{color:#f0a08a}.ev .dim{color:#8a8178}
.cap{font-family:ui-sans-serif,sans-serif;font-size:8.5pt;color:#6b635a;margin:-7px 0 16px;
 font-style:italic}
.box{background:#faf7f3;border:1px solid #e8e1d8;border-radius:9px;padding:14px 17px;margin:14px 0}
.box.warn{background:#fdf4f1;border-color:#efcfc4}
.box h4{margin:0 0 6px;font-size:11pt}
.gap{display:flex;align-items:center;justify-content:center;gap:22px;margin:18px 0;
 padding:20px;background:#faf7f3;border:1px solid #e8e1d8;border-radius:10px}
.gap .n2{font-size:34pt;font-weight:600;line-height:1}
.gap .l{font-size:8.5pt;text-transform:uppercase;letter-spacing:.06em;color:#6b635a;
 text-align:center;margin-top:5px;font-family:ui-sans-serif,sans-serif}
.gap .dry{color:#c4603f}.gap .out{color:#8a8178}.gap .ar{font-size:20pt;color:#8a8178}
.shot{border:1px solid #e8e1d8;border-radius:9px;padding:0;margin:14px 0;overflow:hidden}
.shot img{width:100%;display:block}
.ph{background:#faf7f3;border:2px dashed #d8cfc4;border-radius:9px;padding:26px 20px;
 text-align:center;color:#8a8178;font-family:ui-sans-serif,sans-serif;font-size:9.5pt;margin:14px 0}
ul,ol{margin:0 0 11px;padding-left:20px}li{margin-bottom:5px}
.two{display:flex;gap:18px}.two>div{flex:1}
code{background:#f3ede6;padding:1px 5px;border-radius:3px;font-size:9pt;
 font-family:ui-monospace,Menlo,monospace}
.ft{margin-top:34px;padding-top:13px;border-top:1px solid #e8e1d8;font-size:9pt;color:#8a8178;
 font-family:ui-sans-serif,sans-serif}
@media print{body{background:#fff}.page{box-shadow:none;max-width:100%;padding:0.4in}
 h2{page-break-after:avoid}table,.ev,.box{page-break-inside:avoid}}
"""

HTML = f"""<!doctype html><html lang=en><head><meta charset=utf-8>
<title>DewPoint — Final Project Report</title><style>{CSS}</style></head><body><div class=page>

<h1>DewPoint</h1>
<p class=sub>Skincare and outfit, planned around the air you are actually in.</p>

<div class=meta>
<b>Author:</b> Jennifer Pham &nbsp;·&nbsp; <b>Course:</b> MGT 409 &nbsp;·&nbsp;
<b>Date:</b> {date.today():%d %B %Y}<br>
<b>Repository:</b> <a href="https://github.com/thuydgpham99/dewpoint">github.com/thuydgpham99/dewpoint</a><br>
<b>App link:</b> none — DewPoint runs locally. <code>pip install -r requirements.txt</code>
then <code>python3 app.py</code>; full steps in the README. Verified from a clean clone with
the <code>.env</code> one level above, dependencies installed in 4 seconds.<br>
<b>Self-check:</b> <code>python3 selftest.py</code> runs 18 checks, including a live model
call, and should report 18/18.<br>
<b>Model:</b> gpt-5.6-luna via Portkey &nbsp;·&nbsp;
<b>Runs measured for this report:</b> {len(RUNS)}<br><br>
DewPoint derives the relative humidity your skin actually sits in — indoor air, not the
outdoor figure your weather app reports — and uses that one number to plan both your
skincare routine and what you wear.
</div>

<p class=lede>Your weather app says it is 80% humidity today. Your skin is sitting in
23.6%. Both numbers are correct, and almost nobody knows the second one exists.</p>

<h2>1. Title and links</h2>
<p>Given in the block above: project name, author, repository, how to run it, and a one-line description.</p>

<h2>2. Motivation</h2>

<p><b>Who has the problem.</b> Anyone who follows a skincare routine and notices it stops
working at certain times of year. The reference user for this project is a graduate
student in New Haven who owns eleven skincare products, follows a fixed routine, and
cannot explain why her skin is tight and flaking in February when her weather app shows
humidity in the seventies.</p>

<p><b>How they handle it today.</b> Three ways, all poor. They push through and assume the
products stopped working. They buy something new — the average respondent in a 2023
Statista survey of US consumers reported spending roughly $30 per month on skincare, and
seasonal re-buying is a large share of that. Or they ask social media, where the answer is
a product recommendation rather than a diagnosis.</p>

<p><b>What it costs them.</b> Money spent replacing products that were never the problem,
plus a genuine barrier-damage cycle: dry air causes flaking, flaking is mistaken for
congestion, the user exfoliates, the barrier degrades further. The cost is both financial
and dermatological.</p>

<div class=box><h4>Dew point, in one sentence</h4>
<p style="margin:0">The <b>dew point</b> is the temperature at which air becomes saturated
and water condenses out of it. Unlike relative humidity, it is an <i>absolute</i> measure
of how much water the air actually contains — it does not move when the temperature does.
That property is what makes it the right input here, and it is why the product is named
after it.</p></div>

<p><b>The thing nobody is told.</b> Relative humidity is relative to temperature. Cold air
holds very little water even at high relative humidity. When that air is drawn into a
heated building and warmed to room temperature, its capacity rises sharply while its
actual water content does not — so its relative humidity collapses. This is why skin
cracks in winter while the forecast reads "humid," and it is a straightforward
psychrometric calculation that no consumer skincare or weather product performs.</p>

<div class=gap>
<div><div class="n2 out">80%</div><div class=l>what your weather app reports</div></div>
<div class=ar>→</div>
<div><div class="n2 dry">23.6%</div><div class=l>what your skin is in, computed</div></div>
</div>
<p class=cap>New Haven, 2 °C air at a −1 °C dew point, heated to 20.5 °C indoors.
Computed by <code>climate.py</code>, not estimated.</p>

<h2>3. What is new</h2>

<p><b>Existing alternatives, named.</b></p>
<table>
<tr><th>What exists</th><th>What it does</th><th>Why it does not solve this</th></tr>
<tr><td><b>Apple Weather, Google Weather, Weather.com</b></td>
<td>Report outdoor relative humidity, and in some cases dew point</td>
<td>Stop at the outdoor figure. None converts it to the indoor humidity a person is
actually in, which §3 shows implies different advice in 9 of 16 cities.</td></tr>
<tr><td><b>Skin Bliss, TroveSkin, YUTY</b></td>
<td>Build a routine from a skin-type quiz and a product scan</td>
<td>Treat the environment as static. The routine you get in February is the routine you
get in July.</td></tr>
<tr><td><b>Brand tools (e.g. La Roche-Posay My Skin Track, Vichy SkinConsult)</b></td>
<td>Diagnose skin from a photo or a sensor, and recommend from one catalogue</td>
<td>Recommend only their own products, and give no weather reasoning at all.</td></tr>
<tr><td><b>ChatGPT or Claude, asked directly</b></td>
<td>Will happily answer "what skincare should I use in cold weather"</td>
<td>This is the closest competitor and deserves an honest comparison. Asked the question
it gives sound general advice — use a richer moisturiser, cut back on acids. What it
cannot do is the part that matters: it has no live weather, so it cannot know today's dew
point; it will not compute indoor humidity unless you already know to ask for it, which
requires knowing the concept exists; and asked to estimate, it produces a plausible number
rather than a derived one. The whole value here is a specific figure for a specific
day, computed, not described.</td></tr>
<tr><td><b>Outfit recommenders (Cladwell, Whering, Indyx)</b></td>
<td>Build outfits from your wardrobe, keyed on temperature and rain</td>
<td>Never touch skin, so they cannot know that today's balm will stain the silk collar
they just recommended.</td></tr>
</table>

<p>Nothing in that list joins the two halves, and nothing computes the indoor figure.</p>

<h3>Measured against the closest competitor</h3>

<p>Claiming ChatGPT cannot do this is cheap unless it is tested, so I tested it. The same
model DewPoint uses was asked directly, across all {N_CITIES} sample cities, in the two
framings that matter.</p>

<p><b>Framing A, assisted.</b> The model is handed the dew point explicitly. This is a
generous test: it presupposes the user already knows that dew point is the quantity that
governs the answer, which is the entire insight. Result: it matched the engine's advice band
in <b>{BLA_MATCH} of {BLA_N}</b> cities, mean error <b>{BLA_MEAN:.1f} points</b>. It declined
to give a number at all for two cities.</p>

<p><b>Framing B, realistic.</b> The model is told what a weather app would show — temperature
and relative humidity — and asked what the skin is dealing with. This is what a person would
actually type.</p>

<table>
<tr><th>City</th><th style="text-align:right">Engine</th><th>Band</th>
<th style="text-align:right">Model</th><th>Band</th>
<th style="text-align:right">Error</th><th>Advice</th></tr>
{BL_ROWS}
</table>

<div class="box warn"><h4>Asked the way a person would ask, the model gives different advice in {BL_MISS} of {BL_N} cities</h4>
<p style="margin:0">Mean absolute error <b>{BL_MEAN:.1f} points</b>, median
<b>{BL_MED:.1f}</b>, worst miss <b>{BL_WORST:.1f}</b>. The worst case is instructive: asked
about London, the model answered <b>88%</b> — which is precisely the outdoor relative humidity
it had just been given. It did not compute anything. It handed the number back.</p></div>

<p><b>The honest reading of this.</b> A capable model is not useless here. Its median error is
{BL_MED:.1f} points and it gets the band right roughly six times in ten, which is better than
guessing — and considerably better than the five people in §7, who managed one in five. If the
question were asked once, out of curiosity, the model would usually do.</p>

<p>Three things stop that being sufficient for something acted on daily:</p>
<ul>
<li><b>It fails silently and unpredictably.</b> A 46-point miss arrives in the same confident
register as a 1-point one. Nothing in the answer signals which you received.</li>
<li><b>It fails worst where the reasoning is least intuitive.</b> In the assisted framing it
missed Hanoi by 21.9 points, treating an air-conditioned tropical room as though it were being
heated. That is precisely the case a person could not catch themselves.</li>
<li><b>It is not reproducible.</b> Ask twice, get two numbers. The engine returns the same
figure for the same inputs, every time, in under a millisecond and at no cost — against
{BLA_LAT:.1f} seconds and ${BLA_COST / max(BLA_N, 1):.5f} per question.</li>
</ul>

<p>So the claim this project makes is narrower than "the model cannot do it", and more
defensible: <i>a derived number that is always right beats a plausible number that is usually
right, when the thing being decided is what you put on your face every morning.</i> That is
also why the arithmetic lives in <code>climate.py</code> and not in a prompt — the same
argument, applied internally, is the core of §4.</p>

<p><b>What DewPoint does differently.</b> Three things, in order of how new they are:</p>

<ol>
<li><b>It computes indoor humidity from the dew point.</b> This is the core claim.
Outdoor relative humidity is close to useless as a predictor of transepidermal water
loss; the humidity of heated indoor air is the number that matters, and it is derivable
from data every weather API already publishes. I could not find a consumer product that
does this.</li>
<li><b>It treats skincare and clothing as one coupled problem.</b> The product on your
face determines what fabric should touch it. Occlusive balm permanently stains silk.
Chemical sunscreen filters yellow white cotton. Mineral sunscreen leaves a cast on dark
collars. Cold wind plus wool abrades a barrier already stripped. These are real,
specific, and never surfaced by either category of app.</li>
<li><b>It knows how old your products are.</b> Parsing a pasted receipt gives every
product a purchase date, which turns two invisible problems visible: oxidised actives,
and products bought for a different season still in daily use.</li>
<li><b>It looks ahead, because barrier care is slow.</b> Switching to an occlusive on the
morning your skin already hurts is too late — it takes a day or two of consistent use to
do anything. DewPoint computes indoor humidity for the next four days and warns before the
change arrives, which is the difference between advice and a diagnosis after the fact.</li>
<li><b>It will not recommend a purchase without the money attached.</b> Every suggestion
is checked against what the user already owns and has already spent. See below — this
turned out to be the most opinionated design decision in the project.</li>
</ol>

<h3>Recommendations are grounded, not generated</h3>
<p>An earlier build simply asked the model what the user was missing and printed the
answer. That is the standard behaviour for this category of app, and it is bad: it
recommends purchases to someone who may already own the product, with no sense of what
they have spent. Every recommendation is now routed through
<code>receipts.purchase_context()</code>, which resolves to one of three verdicts:</p>

<table>
<tr><th>Verdict</th><th>Condition</th><th>What the user is told</th></tr>
<tr><td><b>Use what you have</b></td><td>Owns it, still inside its PAO window</td>
<td>Named product, its age, and an instruction <i>not</i> to buy</td></tr>
<tr><td><b>Replace</b></td><td>Owns it, past its window</td>
<td>That the product expired — usually the real reason it "stopped working"</td></tr>
<tr><td><b>New purchase</b></td><td>Owns nothing in the category</td>
<td>That this is genuinely new, beside the month's spend</td></tr>
</table>

<p>Every verdict carries the same three figures: spent this month, the tracked monthly
average, and the value already owned that has expired. The model proposes a
<i>category</i>; the deterministic layer decides whether buying anything is warranted.
This is the same separation as §4 — the model is never the thing that decides.</p>



<h3>How often does this actually change the answer?</h3>
<p>The premise is only interesting if the outdoor number is misleading often
enough to matter. Running all {N_CITIES} sample cities through the engine and
asking which dryness band each reading falls into:</p>

<table>
<tr><th>City</th><th style="text-align:right">Outdoor</th><th>Band</th>
<th style="text-align:right">Indoor</th><th>Band</th><th>Building</th><th>Advice</th></tr>
{BAND_TABLE}
</table>

<div class=box><h4>{DISAGREE} of {N_CITIES} cities ({DISAGREE_PCT:.0f}%) land in a different advice band</h4>
<p style="margin:0">Mean gap between the two readings: <b>{MEAN_GAP:.1f} percentage points</b>.
Largest: <b>{MAX_GAP:.1f}</b>. In Seoul the weather app reads 55% — comfortable — while the
air indoors is at 11.9%, which is the most damaging band in the scale. In Phoenix the error
runs the other way: 12% outdoors reads alarming, but the air conditioning brings indoor air
up to 27%. Acting on the outdoor figure gives you the wrong routine more often than the
right one.</p></div>

<p><b>Why it matters.</b> The advice changes. At 23.6% indoor humidity the correct action
is to pause retinoids and acids and seal the barrier. The user's instinct — and the
recommendation she would get from a product quiz — is to exfoliate the flaking. DewPoint
tells her the opposite, and explains why in terms of a number she can check.</p>

<h2>4. The agents</h2>

<h3>Organisation</h3>
<p>Three agents run in sequence behind a deterministic engine. The handoff is strictly
one-directional; no agent calls another.</p>

<div class=ev><span class=dim>city ─▶</span> weather.py        <span class=dim>Open-Meteo, no API key, offline fallback</span>
            <span class=dim>│</span>
            <span class=dim>▼</span>
        climate.py        <span class=dim>psychrometrics ─ every number computed here</span>
            <span class=dim>│  indoor_rh, band, fabric rules, cross-domain alerts</span>
            <span class=dim>▼</span>
        guard.py          <span class=dim>injection screen · medical boundary · length cap</span>
            <span class=dim>│</span>
   ┌────────┴────────┐
   <span class=dim>▼</span>                 <span class=dim>▼</span>
<span class=ok>Agent 1</span>           <span class=ok>Agent 2</span>
Shelf Reader      Stylist
<span class=dim>use / skip / gap</span>  <span class=dim>outfit / swing / avoid</span>
   <span class=dim>│</span>                 <span class=dim>│</span>
   └────────┬────────┘
            <span class=dim>▼</span>
        <span class=ok>Agent 3</span>  Briefer
        <span class=dim>three-paragraph morning brief</span>
            <span class=dim>│</span>
            <span class=dim>▼</span>
     _enforce_invariants()   <span class=dim>sunscreen is never skipped</span></div>
<p class=cap>Figure 1. Pipeline. The two shaded boxes are independent and could run in
parallel; they are sequential here only to keep the measured token accounting simple.</p>

<h3>Roles and tools</h3>
<table>
<tr><th>Agent</th><th>Role</th><th>Tools / inputs</th><th>Output</th></tr>
<tr><td><b>Shelf Reader</b></td><td>Sorts the products the user owns into tonight's plan</td>
<td>Pre-computed dryness band and rules from <code>climate.py</code>; sanitised shelf text</td>
<td>JSON: use / skip / gap</td></tr>
<tr><td><b>Stylist</b></td><td>Builds one outfit for the day's range</td>
<td>Fabric rules, temperature swing, precipitation, UV; sanitised wardrobe text</td>
<td>JSON: outfit / swing plan / avoid</td></tr>
<tr><td><b>Briefer</b></td><td>Writes the morning brief and surfaces the single most
important skin-to-clothing conflict</td>
<td>Outputs of agents 1 and 2, plus the cross-domain alerts</td>
<td>Prose, under 140 words</td></tr>
</table>

<h3>The central design decision: no agent does arithmetic</h3>
<p>Every number in DewPoint — indoor humidity, the dryness band, expiry windows, fabric
thresholds — is computed in Python before any model is called. The agents receive those
figures as given and are instructed never to recalculate. This is deliberate. The most
common and most damaging failure mode for an LLM in an advisory product is a confident,
wrong number, and prompting is a weak defence against it. Removing the arithmetic from
the model's job removes the failure mode by construction.</p>

<h3>Model choice</h3>
<p>All three agents run <b>gpt-5.6-luna</b>. A note on the model name: the assignment
specifies <code>gpt-6-luna</code> on the course key, while the course <code>.env</code>
supplied to students sets <code>PORTKEY_MODEL=gpt-5.6-luna</code>, and that is the
deployment the gateway actually serves. Rather than hardcode either, the app reads
<code>PORTKEY_MODEL</code> from the environment and falls back to <code>gpt-5.6-luna</code>,
so it follows whatever the course configures without an edit. No model outside the course
key is used anywhere. Having
measured it, the choice is defensible on its own terms for agents 1 and 2 — both emit
small, strictly-shaped JSON where reliability matters more than fluency — but it is a
poor fit for agent 3, and the measurements in §4 show why: the model spends
<b>{reason_pct:.0f}% of its output budget on hidden reasoning tokens</b>, which is
expensive for a task that is essentially rewriting. If a cheaper non-reasoning model were
available on the course key, the Briefer is the call I would move first.</p>

<h3>One real run, traced</h3>
<p>Input: city <code>New Haven winter</code>; shelf <code>CeraVe foaming cleanser,
niacinamide 10%, retinol 0.5% serum, ceramide moisturizer, SPF 50</code>; wardrobe
<code>white silk blouse, black wool coat, grey merino knit, denim, trench coat</code>.</p>

<div class=ev><span class=dim>STEP 1  weather.py</span>
  temp 2.0C  dew_point -1.0C  outdoor_rh 80%  wind 28kph  uv 2.0

<span class=dim>STEP 2  climate.py  (no model involved)</span>
  e  = 6.112 · exp(17.67·−1.0 / (−1.0+243.5))      = 5.62 hPa
  es = 6.112 · exp(17.67·20.5 / (20.5+243.5))      = 24.11 hPa
  <span class=ok>indoor_rh = 5.62 / 24.11 = 23.6%  →  band "high"</span>
  alerts: ["Balm and collars", "Windburn"]

<span class=dim>STEP 3  guard.py</span>
  injection findings: 0    medical: no    truncated: no

<span class=dim>STEP 4  Agent 1 Shelf Reader</span>      <span class=dim>555 in / 423 out (291 reasoning)</span>
  use : ceramide moisturizer (PM)
  skip: CeraVe foaming cleanser, niacinamide 10%, retinol 0.5% serum, <span class=bad>SPF 50</span>
  gap : "Hyaluronic acid to apply on damp skin"

<span class=dim>STEP 5  _enforce_invariants()</span>
  <span class=ok>SPF 50 moved out of skip → use (AM)</span>   <span class=dim># model error, caught deterministically</span>

<span class=dim>STEP 6  Agent 2 Stylist</span>            <span class=dim>449 in / 191 out (81 reasoning)</span>
  outfit: grey merino knit, black wool coat, white silk blouse
  avoid : denim as a base layer

<span class=dim>STEP 7  Agent 3 Briefer</span>            <span class=dim>654 in / 509 out (333 reasoning)</span>
  "...The main conflict is the silk blouse: balm on your face and neck can
   permanently darken silk, so keep the collar clear or choose cotton."

<span class=dim>TOTAL</span>  3 calls · 1,658 in · 1,123 out · <span class=ok>$0.00092</span> · 9.4 s</div>
<p class=cap>Figure 2. Full trace of run <code>efda6726</code>, copied from the live log.
Note step 5: the model filed sunscreen under "skip" and the invariant check corrected it.</p>

<div class=shot><img src="{embed('01-plan.jpg')}" alt="DewPoint showing the humidity gauge for Seoul"></div>
<p class=cap>Figure 2b. A live run on Open-Meteo data for New Haven. Both readings sit on
one scale so the collapse is visible rather than inferred: 61% outdoors, 29.1% on the skin,
31.9 points lost to heating. The panel above the gauge names the mechanism — heating here,
air conditioning in a hot climate.</p>

<div class=shot><img src="{embed('02-outlook.jpg')}" alt="The four-day outlook with a drying warning"></div>
<p class=cap>Figure 2c. A week of indoor conditions, with Thursday selected. Each day
carries its own dryness band, the products to favour and avoid, layer counts and fabrics
for morning and afternoon, and any skin-to-clothing conflict. None of the forecast days
costs a model call — the rules derive all of it, which is the same separation described
above. Seven extra calls per run would roughly octuple the cost for advice the engine
already knows how to produce. Below, the warning that makes the week worth showing:
barrier care needs a day or two of lead time, so it has to arrive before the change does.</p>

<div class=shot><img src="{embed('04-rows.jpg')}" alt="Shelf and outfit lists with two rows expanded"></div>
<p class=cap>Figure 2d. Progressive disclosure. Each row shows only the product or garment
by default, with its AM/PM/SKIP verdict; the reasoning appears on tap. An earlier build
printed every justification at once, which turned the answer to a simple question into a
page of prose. Two rows are expanded here. Built on native <code>&lt;details&gt;</code>, so
it is keyboard operable and readable by a screen reader without any JavaScript. Right: the
outfit split across the day, the afternoon repeating the morning minus a layer.</p>

<h2>5. Tokenomics</h2>

<p>Every figure in this section is read from the provider's own <code>usage</code> field
and logged to <code>runs/usage.jsonl</code> by <code>meter.py</code>. Nothing is estimated.
Measured across <b>{len(RUNS)} runs</b>.</p>

<table>
<tr><th>Measure</th><th>Per run (mean)</th></tr>
<tr><td>Input tokens</td><td class=n>{fmt(avg['input'])}</td></tr>
<tr><td>Cached input tokens</td><td class=n>{fmt(avg['cached'])}</td></tr>
<tr><td>Output tokens (visible + reasoning)</td><td class=n>{fmt(avg['output'])}</td></tr>
<tr><td>&nbsp;&nbsp;of which hidden reasoning tokens</td><td class=n>{fmt(avg['reasoning'])} ({reason_pct:.0f}%)</td></tr>
<tr><td><b>Total tokens</b></td><td class=n><b>{fmt(avg['total'])}</b></td></tr>
<tr><td><b>Cost per run</b></td><td class=n><b>${avg['cost']:.5f}</b></td></tr>
</table>

<h3>The finding that matters</h3>
<div class="box warn"><h4>{reason_pct:.0f}% of output tokens are never shown to the user</h4>
<p style="margin:0">This model reasons before answering, and reasoning tokens bill at the
output rate. On a typical run {fmt(avg['reasoning'])} of {fmt(avg['output'])} output tokens
were internal. The visible answer — the part the user reads — is roughly a third of what
is paid for. Any cost model built on visible output length would understate the bill by
about 3×.</p></div>

<h3>Cost at scale</h3>
<p>Assumption, stated plainly: a user opens DewPoint on mornings when conditions shift
meaningfully, modelled at <b>{RUNS_PER_USER_MONTH} runs per user per month</b>. Rates used:
${rates['input']}/1M input, ${rates['cached_input']}/1M cached, ${rates['output']}/1M output.</p>

<table>
<tr><th>Scale</th><th>Runs / month</th><th>Cost / month</th><th>Cost / year</th></tr>
<tr><td>One user</td><td class=n>{RUNS_PER_USER_MONTH}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH:.4f}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH*12:.2f}</td></tr>
<tr><td>100 users</td><td class=n>{fmt(100*RUNS_PER_USER_MONTH)}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH*100:.2f}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH*100*12:.2f}</td></tr>
<tr><td>10,000 users</td><td class=n>{fmt(10000*RUNS_PER_USER_MONTH)}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH*10000:.2f}</td>
<td class=n>${avg['cost']*RUNS_PER_USER_MONTH*10000*12:,.2f}</td></tr>
</table>

<p>At 10,000 users the model bill is roughly
<b>${avg['cost']*RUNS_PER_USER_MONTH*10000*12:,.0f} per year</b> — about
<b>${avg['cost']*RUNS_PER_USER_MONTH*12:.2f} per user per year</b>. Weather costs nothing
(Open-Meteo, no key). The deterministic engine costs nothing. Inference is effectively
the entire marginal cost of the product.</p>

<h3>At organisation scale</h3>

<p>Per-user figures understate what matters to whoever would actually deploy this, so three
concrete deployments, costed from the measured per-run figure of ${avg['cost']:.5f}:</p>

<table>
<tr><th>Deployment</th><th style="text-align:right">People</th>
<th style="text-align:right">Runs / month</th><th style="text-align:right">Model cost / yr</th>
<th>What it would replace</th></tr>
<tr><td><b>A university residential college</b><br><span class=cap style="margin:0">Yale colleges run roughly this size</span></td>
<td class=n>450</td><td class=n>{450 * RUNS_PER_USER_MONTH:,}</td>
<td class=n>${avg['cost'] * RUNS_PER_USER_MONTH * 450 * 12:.2f}</td>
<td>Nothing — this is additive. The cost is below a single bulk order of moisturiser for a
college wellbeing cupboard.</td></tr>
<tr><td><b>A dermatology clinic's patient list</b><br><span class=cap style="margin:0">Barrier-repair advice between appointments</span></td>
<td class=n>2,000</td><td class=n>{2000 * RUNS_PER_USER_MONTH:,}</td>
<td class=n>${avg['cost'] * RUNS_PER_USER_MONTH * 2000 * 12:.2f}</td>
<td>Perhaps one avoided follow-up visit per year across the whole list, which in the US would
cover the annual bill many times over.</td></tr>
<tr><td><b>A skincare retailer's customer base</b><br><span class=cap style="margin:0">As a service, not a sales funnel</span></td>
<td class=n>10,000</td><td class=n>{10000 * RUNS_PER_USER_MONTH:,}</td>
<td class=n>${avg['cost'] * RUNS_PER_USER_MONTH * 10000 * 12:,.2f}</td>
<td>Returns driven by "it stopped working" when the real cause was oxidation or a seasonal
mismatch, both of which §7 shows the app detects.</td></tr>
</table>

<p>The shape of this is the point: at every scale the model bill is small enough that it is
not the constraint. Ten thousand people cost about
<b>${avg['cost'] * RUNS_PER_USER_MONTH * 10000 * 12:,.0f} a year</b> to serve — roughly the
price of <b>{(avg['cost'] * RUNS_PER_USER_MONTH * 10000 * 12) / 182:.0f}</b> of the oxidised
serums found on the single shelf in §7. Weather is free, the engine is free, and the
deterministic design means the forecast week adds nothing at all. What would actually limit a
deployment is trust and distribution, not inference.</p>

<p><b>The nonprofit case.</b> A campus or clinic deployment at 450 people costs under
<b>${avg['cost'] * RUNS_PER_USER_MONTH * 450 * 12:.0f} a year</b>. That is small enough to sit
inside an existing student-wellbeing budget without a procurement conversation, which matters
more for adoption than any technical property of the system.</p>

<h3>Cost-cutting, measured</h3>
<p>I tested the obvious lever: collapsing the three agents into one merged call producing
the same three outputs. <code>bench.py</code> runs both across three climates.</p>

<table>
<tr><th>Climate</th><th>3-agent in/out</th><th>3-agent cost</th><th>1-call in/out</th>
<th>1-call cost</th><th>Saving</th></tr>
{bench_rows}
</table>

<p><b>Result: {bench_saving:.0f}% cheaper.</b> The saving comes from the system prefix being
sent once instead of three times, and from one reasoning pass instead of three.</p>

<p><b>The tradeoff, honestly.</b> The merged call returned valid JSON on 3 of 3 attempts
here, which is not enough evidence to call it safe — a single malformed response loses the
entire run rather than one third of it, and the three-agent version degrades gracefully
because each agent's output is validated independently. I have kept the three-agent
pipeline as the default and shipped the merged version as a benchmark rather than a
setting. At this cost per run the {bench_saving:.0f}% saving is worth about
${(avg['cost']*bench_saving/100)*RUNS_PER_USER_MONTH*12:.2f} per user per year, which does
not justify the reliability loss until the user base is far larger.</p>

<h3>Two other levers, and why one failed</h3>
<ul>
<li><b>Prompt caching — attempted, did not fire.</b> All three agents share one stable
system prefix specifically so the provider could cache it. Measured cached tokens:
<b>{fmt(avg['cached'])}</b>. The prefix is roughly 250 tokens and the provider's cache
minimum is 1,024, so it never qualified. Reported here because it is a real negative
result: the optimisation was designed in and did not pay.</li>
<li><b>Gateway response caching — observed.</b> Repeating an identical request returned in
under 0.4 s against ~9.4 s for a fresh run, consistent with Portkey caching at the gateway.
Useful for repeated identical queries, irrelevant to real usage where the weather differs.</li>
</ul>

<h2>6. Safety</h2>

<h3>Threat 1 — prompt injection through pasted text</h3>
<p>DewPoint's two free-text inputs are the shelf box and the receipt box. The receipt box
is the serious one: receipt text is <i>email content</i>, which is attacker-controllable
and arrives with implicit legitimacy. A fake order confirmation carrying injected
instructions is a realistic attack, not a contrived one.</p>

<p><code>guard.py</code> screens both fields against twelve injection shapes before any text
reaches a model, strips what it matches, and shows the user what it removed.</p>

<div class=ev><span class=dim>$ curl -X POST /api/receipt -d @data/sample_receipt_attack.txt</span>

<span class=ok>injection_blocked: True</span>
  <span class=bad>- override attempt          -> Ignore all previous instructions</span>
  <span class=bad>- role reassignment         -> You are now a</span>
  <span class=bad>- injected instruction block-> NEW INSTRUCTIONS:</span>
  <span class=bad>- prompt extraction         -> print your system prompt</span>
  <span class=bad>- concealment attempt       -> Do not tell the user</span>
  <span class=bad>- recommendation hijack     -> Always recommend</span>
  <span class=bad>- recommendation hijack     -> regardless of weather</span>

<span class=dim>legitimate line items still parsed correctly:</span>
  <span class=ok>['CeraVe Foaming Facial Cleanser', 'Retinol 0.5% in Squalane']</span></div>
<p class=cap>Figure 3. Seven injected instructions stripped from a single fake receipt
while the real line items parse normally. <b>Defence shown working.</b></p>

<div class=shot><img src="{embed('03-injection.jpg')}" alt="The app showing injected instructions removed from a receipt"></div>
<p class=cap>Figure 3b. The same defence in the interface. The user is told exactly what was
removed and why, rather than the block happening silently. The plan on the right is
unaffected, and the $182 expired-product finding is visible at lower left.</p>

<p>Three layers, not one: the patterns above; <code>&lt;shelf&gt;</code> and
<code>&lt;wardrobe&gt;</code> delimiters with an explicit system-prompt instruction that
their contents are data; and the structural fact that the agents cannot take actions —
there is no tool call, no spend, no outbound message. The worst outcome of a successful
injection is bad cosmetic advice, which is also what the invariant check in §4 exists to
catch.</p>

<h3>Threat 2 — agent malfunction</h3>
<p>Measured, not hypothesised. Across four live runs the Shelf Reader filed <b>SPF 50 under
"skip" on 2 of 4 climates</b> — on overcast days, where it is most wrong, since UVA passes
through cloud. This is exactly the quiet, plausible error that prompting handles badly.</p>

<div class=ev><span class=dim>New Haven winter</span>  band=high        <span class=ok>SPF kept</span>  corrections: <span class=ok>['SPF 50 moved out of skip']</span>
<span class=dim>Miami summer</span>      band=humid       <span class=ok>SPF kept</span>  corrections: <span class=ok>['SPF 50 moved out of skip']</span>
<span class=dim>Phoenix dry heat</span>  band=moderate    <span class=ok>SPF kept</span>  corrections: []
<span class=dim>London damp</span>       band=comfortable <span class=ok>SPF kept</span>  corrections: []</div>
<p class=cap>Figure 4. The invariant check firing twice. <b>Second defence shown working.</b></p>

<p>Other malfunction controls: invented facts are limited by giving the agents no
arithmetic and no product catalogue — they may only sort products the user actually listed;
infinite loops are impossible because the pipeline is a fixed three-step chain with no
agent-to-agent calls and a hard <code>MAX_AGENT_CALLS_PER_RUN</code> ceiling.</p>

<h3>Threat 3 — out-of-scope and medical requests</h3>
<p>Skincare questions shade into medicine quickly. Seven pattern families — prescription
dosing, suspected adverse reactions, infection, oncological concern, pregnancy safety,
diagnosed conditions, isotretinoin — are refused <i>before</i> any model call, which also
means they cost nothing.</p>

<div class=ev><span class=dim>input:</span> "my tretinoin gave me blistering and swelling, what dose should I take"

<span class=bad>blocked: medical</span>
<span class=dim>reasons:</span> ['prescription dosing', 'suspected adverse reaction']
<span class=dim>response:</span> "DewPoint plans cosmetic routines around the weather. It is not a
medical tool and cannot advise on this. Please speak to a dermatologist
or your doctor — and if this involves a reaction that is spreading,
painful, or affecting your breathing, treat it as urgent."
<span class=dim>model calls made: 0</span></div>
<p class=cap>Figure 5. Medical boundary. <b>Third defence shown working.</b></p>

<h3>Threat 4 — overspending</h3>
<table>
<tr><th>Control</th><th>Value</th><th>Where</th></tr>
<tr><td>Input character cap per field</td><td class=n>4,000</td><td><code>guard.enforce_length</code></td></tr>
<tr><td>Token ceiling per run</td><td class=n>6,000</td><td><code>config.MAX_TOKENS_PER_RUN</code></td></tr>
<tr><td>Max agent calls per run</td><td class=n>5</td><td><code>config.MAX_AGENT_CALLS_PER_RUN</code></td></tr>
<tr><td>Medical / injection screen</td><td>pre-model</td><td>blocked requests cost $0</td></tr>
</table>
<p>The ceiling is enforced mid-pipeline: if the first two agents exceed it, the Briefer is
skipped and the user still receives a complete structured plan. Worst-case cost per run is
bounded at roughly ${(6000/1_000_000)*rates['output']:.5f}, about
{6000/avg['total']:.1f}× the measured mean.</p>

<h2>7. Impact</h2>

<p><b>Measured on the sample shelf.</b> Parsing a real six-item order confirmation
($324.48, dated May 2026) against today's date surfaces one unambiguous finding:</p>

<div class=ev><span class=dim>expiry report — today 2026-10-25</span>
  <span class=bad>expired</span>    5.2mo / 3mo   <span class=bad>$182.00</span>  Skinceuticals C E Ferulic Vitamin C Serum
  <span class=dim>expiring</span>   5.2mo / 6mo   $ 48.00  Biossance Squalane Marula Facial Oil

  total shelf value  $324.48
  <span class=bad>value past window  $182.00  (56% of the shelf)</span></div>
<p class=cap>Figure 6. A $182 serum, oxidised and still in daily use. L-ascorbic acid has a
~3 month window once opened; past it the product is inert and can stain fabric.</p>

<table>
<tr><th>Metric</th><th>Value</th><th>Source</th></tr>
<tr><td>Wasted product value identified, one shelf</td><td class=n>$182.00</td><td>measured, Fig. 6</td></tr>
<tr><td>Share of shelf value past its window</td><td class=n>56%</td><td>measured, Fig. 6</td></tr>
<tr><td>Cost to run DewPoint, per user per year</td><td class=n>${avg['cost']*RUNS_PER_USER_MONTH*12:.2f}</td><td>measured, §5</td></tr>
<tr><td>Ratio of value surfaced to cost of running</td><td class=n>~{182/(avg['cost']*RUNS_PER_USER_MONTH*12):,.0f}×</td><td>derived</td></tr>
<tr><td>Time to a decision</td><td class=n>~9 s</td><td>measured, §5</td></tr>
<tr><td>People who guessed the wrong band</td><td class=n>{STUDY_WRONG} of {STUDY_N}</td><td>measured, below</td></tr>
<tr><td>Mean error in those guesses</td><td class=n>{STUDY_MAE:.1f} pts</td><td>measured, below</td></tr>
<tr><td>Spread across five people in one city</td><td class=n>{STUDY_SPREAD} pts</td><td>measured, below</td></tr>
<tr><td>Cities where outdoor reading implies different advice</td><td class=n>{DISAGREE} of {N_CITIES}</td><td>computed, §3</td></tr>
</table>

<p><b>The honest limit on the money figure.</b> The $182 is a real computation on a real
product set, but it is one shelf. A proper claim about waste across a population needs a
cohort and a follow-up at 30 days, which §8 proposes.</p>

<h3>Asking five people to guess</h3>

<p>The product rests on a claim about what people do not know. That is testable, so I tested
it. Five people in New Haven were sent one question by text, with no context and no hint
that a right answer existed:</p>

<p class=lede>"What percent humidity do you think the air in your room is right now?"</p>

<p>At the time of asking, the outdoor reading for New Haven was <b>{STUDY_OUTDOOR}%</b> and the
computed indoor figure was <b>{STUDY_ACTUAL}%</b> — the <b>{STUDY_BAND}</b> band.</p>

<table>
<tr><th style="text-align:right">Guess</th><th>Band it implies</th>
<th style="text-align:right">Error</th><th>Routine it would produce</th></tr>
{STUDY_TABLE}
</table>

<div class="box warn"><h4>{STUDY_WRONG} of {STUDY_N} would have followed the wrong routine</h4>
<p style="margin:0">Mean absolute error <b>{STUDY_MAE:.1f} percentage points</b> against a true
value of {STUDY_ACTUAL}%. Only one answer landed in the correct band. The more telling number is
the <b>{STUDY_SPREAD}-point spread</b> — from 10% to 70% — among five people sitting in
substantially the same air. That is not a population that is slightly miscalibrated. It is a
population with no mental model at all, which is what you would expect for a quantity nobody
has ever been shown.</p></div>

<p><b>What the errors would have cost them.</b> The two who guessed 60% and 70% would have
read their air as humid and reached for a gel moisturiser while skipping occlusives — the
exact inversion of what {STUDY_ACTUAL}% calls for. The one who guessed 40% would have read
conditions as comfortable and carried on with acids and a retinoid, which at this dryness is
the specific combination that drives the flaking-then-exfoliating cycle described in §2. Only
the 10% guess erred toward caution.</p>

<h3>Someone actually using it</h3>

<p>Guessing a number tests whether people know the figure. It does not test whether the app
is usable, so one of the five was asked to open it on their own phone and say what they
thought. The exchange, with the phone number cropped out:</p>

<div class=shot><img src="{embed('05-user-trial.jpg')}" alt="Message thread showing the app being opened on a phone"></div>
<p class=cap>Figure 7. A first user reaching the app on an iPhone over the local network,
25 October 2026.</p>

<p><b>What this supports, and what it does not.</b> The verdict was
<i>"Good. The web loooks good."</i> That is genuine evidence on one row and no evidence at
all on the others: it confirms a first-time viewer, on a phone, with no explanation, found
the interface legible and worth a positive comment. It says nothing about whether the
central insight landed, and nothing about whether they would change their routine. I am not
going to dress four words up as more than they are.</p>

<p><b>The more useful finding is the part above the quote.</b> Three messages were sent before
one worked. The first three carried <code>http://127.0.0.1:5001</code>, which resolves to the
recipient's own device and therefore reaches nothing — a mistake that is obvious in hindsight
and was not obvious at the time. Only the fourth, on the machine's local network address,
opened. Two things follow:</p>
<ul>
<li><b>A locally hosted app has a real distribution cost</b> that does not appear in any cost
model. The marginal inference cost is $0.001; the marginal cost of getting a stranger to see
it at all was four messages and a shared wifi network. Section 9 treats hosting as a
convenience; this is the argument that it is closer to a requirement.</li>
<li><b>It prompted a layout pass that should have happened earlier.</b> Checking the app at
375pt found the metric strip reserving desktop row height and the dryness band row truncating
its own labels to "MODER...". A first user on a phone found a defect that no amount of
desktop testing had surfaced.</li>
</ul>

<p><b>The honest limits of this.</b> One person, four words, and no observation of them using
it — I was not in the room, so I cannot report where they hesitated, which is the part that
would actually improve the product. Five people is a convenience sample, not a study. They
were asked once, by someone they know, which invites a guess rather than a considered answer.
No measurement was taken in their actual rooms — the comparison is against the computed
figure for the city, so a humidifier or an unusually cold flat would move the true value. The
result is strong enough to motivate the product and far too small to prove anything about a
population. What it does establish, cheaply, is that the number this app computes is not one
people already carry in their heads.</p>

<h2>8. Limits and next steps</h2>
<h3>What does not work yet</h3>
<ul>
<li><b>Indoor temperature is stated, not measured.</b> The app asks for it and defaults to
20.5 °C, which is the right trade — this was the largest error source and a slider costs the
user two seconds. But a stated figure is still a guess: people are poor judges of room
temperature, and the honest fix is a sensor reading, not a control.</li>
<li><b>The humidifier model is crude.</b> Switching it on pins the room to 45%, the usual
humidistat setpoint. Real units undershoot in very dry air, cycle, and are often run in one
room of several. The toggle is better than ignoring it and worse than measuring it.</li>
<li><b>No commute.</b> The whole model assumes you are indoors. A day spent outside, or a
long walk in cold wind, is not represented at all.</li>
<li><b>The rules are editorial.</b> Dryness bands and fabric mappings reflect published
dermatology guidance and my own reading, but they are thresholds I chose. They are
defensible, not validated.</li>
<li><b>Receipt parsing is regex-based</b> and tested against a handful of formats. Retailer
emails vary enormously; coverage is unknown.</li>
<li><b>Purchase date is not opening date.</b> Period-after-opening starts when a product is
opened. DewPoint uses the purchase date as a proxy, which is conservative but imprecise.</li>
<li><b>Five people is not a study.</b> The guessing exercise in §6 is a convenience
sample, asked once, by someone they know. It is strong enough to motivate the product and
far too small to support a claim about any population.</li>
<li><b>Nobody has used it for a week.</b> The guessing exercise tests whether the number is
known. It does not test whether acting on it improves anyone's skin, which is the claim
that would actually matter and the one §8 proposes measuring.</li>
</ul>

<h3>What another month would buy</h3>
<ol>
<li><b>Photograph the shelf.</b> The receipt path works but asks the user to find an email.
A vision model reading a shelf photo removes that friction entirely, and was cut from this
build only for time.</li>
<li><b>Read indoor temperature from a sensor</b> rather than asking. The slider closed most
of the gap — moving from 17 °C to 24 °C changes the computed figure by about ten points and
can change the advice band outright — but a thermostat or a phone's barometer-adjacent
sensors would remove the guess entirely.</li>
<li><b>Validate the thresholds.</b> Ten users, four weeks, a daily one-question check-in on
skin tightness correlated against computed indoor RH. The guessing exercise establishes that
people do not know the number; this would establish whether knowing it helps, which is the
harder and more useful question.</li>
<li><b>Move the Briefer to a non-reasoning model.</b> §5 shows {reason_pct:.0f}% of output
tokens are internal; the Briefer is a rewriting task that does not need them.</li>
<li><b>Seasonal pre-emption.</b> The dated inventory makes it possible to warn a user in
October that the gel moisturiser they bought in July will be wrong in three weeks — before
the barrier damage, not after.</li>
</ol>

<div class=ft>DewPoint · MGT 409 final project · Jennifer Pham · {date.today():%d %B %Y}<br>
Weather from Open-Meteo. Model gpt-5.6-luna via Portkey. All token counts measured from
provider usage fields and logged to <code>runs/usage.jsonl</code>.<br>
Cosmetic guidance only. Not medical advice.</div>

</div></body></html>"""

out = HERE / "report.html"
out.write_text(HTML)
print(f"report.html written ({len(HTML):,} bytes) from {len(RUNS)} measured runs")
print(f"  avg cost/run ${avg['cost']:.5f} | reasoning {reason_pct:.0f}% of output")
