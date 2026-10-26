# DewPoint

**Skincare and outfit, planned around the air you are actually in.**

Your weather app reports *outdoor* relative humidity. Your skin spends the day in
*indoor* air — outdoor air heated to room temperature, which collapses its relative
humidity. DewPoint derives the humidity your skin actually sits in from the dew point,
then plans your routine and your outfit around that one number.

On a New Haven winter day the weather app reads **80% humidity**. DewPoint computes
**23.6%** indoors. Those two numbers call for opposite routines.

---

## Run it in two minutes

```bash
git clone <this-repo>
cd dewpoint
python3 -m pip install -r requirements.txt
python3 app.py
```

Open <http://127.0.0.1:5001>.

Port 5001 is the default because macOS runs AirPlay Receiver on 5000.
Override with `PORT=8000 python3 app.py` if 5001 is busy too.

### The `.env`

The app looks for `.env` in this order:

1. the repo folder
2. **one level above the repo folder** ← where the teaching staff keep theirs
3. two levels above (local convenience only; never takes priority over 1 and 2)

Copy `.env.example` to `.env` and fill it in:

```
PORTKEY_API_KEY=your-key
PORTKEY_BASE_URL=https://api.portkey.ai/v1
PORTKEY_MODEL=gpt-5.6-luna
```

Only `PORTKEY_API_KEY` is required. The model name is read from `PORTKEY_MODEL`
so the app follows the course configuration rather than hardcoding it.

### It runs without a key, and without the internet

No key, or the API is down → the app falls back to its deterministic engine and
still returns a full plan, clearly labelled as degraded. The weather lookup falls
back to a bundled sample dataset the same way. **The app never fails to the user.**

To force offline mode (useful for grading with no network):

```bash
DEWPOINT_OFFLINE=1 python3 app.py
```

### If live weather falls back to samples

On a python.org macOS install, `urllib` ships an empty certificate store until
`Install Certificates.command` is run, so HTTPS fails even though `curl` works.
The app works around this by using `certifi`'s bundle, which arrives with the
`openai` dependency — so `pip install -r requirements.txt` is enough. If the UI
still says *bundled sample*, check your network: the app never fails to the user,
it just falls back.

---

## Try these

| What | How |
|---|---|
| The core result | Click **New Haven winter**, then **Plan my day** |
| A humid climate | Click **Miami summer** — opposite advice |
| Receipt parsing | Paste `data/sample_receipt.txt` into the Receipt box |
| **Prompt injection blocked** | Paste `data/sample_receipt_attack.txt` into the Receipt box |
| **Medical boundary** | Put `my tretinoin gave me blistering` in the shelf box |
| Measured token usage | Visit <http://127.0.0.1:5001/tokenomics> |
| Cost A/B experiment | `python3 bench.py` |

---

## Datasets

The repo ships a small test dataset so it runs with no network:

- `data/sample_days.json` — five climates (New Haven, London, Miami, Phoenix, San Francisco)
- `data/sample_receipt.txt` — a realistic six-item order confirmation
- `data/sample_receipt_attack.txt` — the same, carrying an injected instruction payload

### Switching between the test dataset and live data

| You want | Do this | What happens |
|---|---|---|
| **Live data** (default) | Type any city name and press **Plan my day** | Calls [Open-Meteo](https://open-meteo.com) — no API key needed. The UI footer shows `Open-Meteo (live)`. |
| **Test dataset only** | `DEWPOINT_OFFLINE=1 python3 app.py` | Every lookup is served from `data/sample_days.json`. No network needed at all. The UI shows `bundled sample (offline)`. |
| **Test a single city** | Click one of the region buttons (New Haven, Hanoi, Seoul …) | Loads that bundled sample day. |

If a live call fails for any reason, the app falls back to the bundled samples
automatically and says so in the UI rather than erroring.

---

## How it is built

```
weather.py     Open-Meteo lookup, no key, with offline fallback
climate.py     psychrometrics + all rules        ← every number is computed here
receipts.py    receipt parsing, dated inventory, expiry + seasonal mismatch
guard.py       prompt-injection screen, medical boundary, input ceiling
agents.py      three-agent pipeline + deterministic fallback
meter.py       token metering, cost model, scaling table
app.py         Flask routes
bench.py       cost experiment: 3 agents vs 1 merged call
```

**The models never do arithmetic.** Humidity, dryness bands, expiry dates,
thresholds and alerts all arrive pre-computed from `climate.py` and `receipts.py`.
The three agents only select and rewrite. This removes confident-wrong-number
failures by construction rather than by prompting.

### The agents

| Agent | Job |
|---|---|
| Shelf Reader | which of *your* products to use and skip tonight |
| Stylist | what to wear for the day's range and precipitation |
| Briefer | merges both into one short morning brief |

### Safety

Three defences, all visible in the UI:

1. **Prompt-injection screen** on untrusted text (the shelf box and pasted receipts —
   receipt text is email content, the most realistic injection vector there is).
   Matched instructions are stripped before the model sees them and the block is
   shown to the user.
2. **Medical boundary** — prescription dosing, suspected reactions, infections,
   pregnancy and oncological concerns are refused and routed to a clinician.
3. **Spend ceilings** — input length cap, per-run token cap, max agent calls.

Plus a **deterministic invariant check**: sunscreen is never skipped, whatever the
model says. On live runs this fired on 2 of 4 climates.

---

## Licence and disclaimer

Cosmetic guidance only. Not medical advice. Built for MGT 409.
