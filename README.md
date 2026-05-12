# kseb-solar-watch

Daily check on KSEB distribution transformers — alerts via Telegram when solar capacity opens up.

## Why

KSEB caps rooftop solar at 90% of the distribution transformer's capacity (per KSERC RE Regulations 2020). If your neighbours got there first, your transformer is full and you can't install solar. Capacity opens up when feasibility approvals lapse or transformers get augmented. This bot watches for that moment.

Data source: <https://wss.kseb.in/selfservices/reCap> (KSEB's public portal).

## How it works

1. Daily GitHub Actions cron hits the KSEB API for each transformer in `watchlist.json`
2. Computes `balance_kw = allowed_cap - feasibility_issued - grid_connected`
3. Compares against last-seen state (persisted via Actions Cache)
4. Sends a Telegram alert the moment `balance_kw` crosses **upward** through the threshold (default 3 kW)
5. Doesn't re-alert until the value drops back below and crosses again — no spam

If the KSEB API is flaky, the run silently retries the next day. No alert noise.

## Setup

### 1. Fork or use this repo

Public repo recommended — GitHub Actions minutes are unlimited for public repos.

### 2. Find your transformer's `dtr_id`

You need two numbers from your KSEB bill:

- **Section ID** — visible at <https://wss.kseb.in/selfservices/reCap> after you pick District → Section (the number in the URL or section dropdown, e.g. `5567` for Aluva Town)
- **DTR ID** — KSEB's internal id for your transformer. Run the helper:

```bash
pip install -r requirements.txt
python find_dtr_id.py 5567 "CHOONDY"
```

Output:

```
Found 1 match(es) in section 5567:

  dtr_id    = 567XXX
  name      = CHOONDY
  feeder    = ...
  capacity  = 100 kVA  (81 KW allowed)
  connected = 72 kW
  issued    = 8 kW
  balance   = 1 kW
```

Copy the `dtr_id` into `watchlist.json`.

### 3. Edit `watchlist.json`

```json
{
  "alert_threshold_kw": 3.0,
  "watch": [
    {
      "dtr_id": "567XXX",
      "section_id": 5567,
      "name_hint": "CHOONDY",
      "notes": "Home transformer.",
      "alert_threshold_kw": null
    }
  ]
}
```

- `alert_threshold_kw` (top level): global default, e.g. `3.0` means "alert when ≥ 3 kW available"
- Per-DTR `alert_threshold_kw`: set to override the global for that one DTR, or `null` to use global

To monitor more transformers later, just add another object to the `watch` array.

### 4. Create a Telegram bot

1. On Telegram, open a chat with [@BotFather](https://t.me/BotFather)
2. Send `/newbot` and follow prompts → you'll get a **bot token** (like `123456:ABC-DEF...`)
3. Open [@userinfobot](https://t.me/userinfobot) to get your **chat id** (a number like `987654321`)
4. Send any message to your new bot first (Telegram won't deliver until you do)

### 5. Add GitHub secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name                  | Value                |
|-----------------------|----------------------|
| `TELEGRAM_BOT_TOKEN`  | from BotFather       |
| `TELEGRAM_CHAT_ID`    | from @userinfobot    |

### 6. Test it

Push to GitHub, then go to **Actions → kseb-solar-watch → Run workflow** (manual trigger).

Watch the logs. On first run with `balance_kw ≥ threshold`, you'll get a Telegram alert.

After that, the daily cron takes over at 09:00 IST.

## Running locally (optional)

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."
python watch.py
```

State is stored in `state.json` (gitignored). Delete it to force a fresh alert on next run.

## File map

```
watch.py            # main script
find_dtr_id.py      # one-time lookup helper
watchlist.json      # what to monitor (commit this)
state.json          # last-seen values (gitignored, cached in Actions)
requirements.txt    # httpx
.github/workflows/  # daily cron
```

## Alert example

```
🌞 Solar Capacity Available!

Transformer: CHOONDY
Balance now: 4.5 kW (was 1.0 kW)
Threshold: ≥ 3 kW

📊 Details
• Capacity: 100 kVA (81 kW allowed)
• Grid connected: 72 kW
• Feasibility issued: 4.5 kW
• KSEB as-on: 12-05-2026 09:32 am

👉 Apply now at ekiran.kseb.in before someone else does.
```

## License

MIT. Data is public per KSERC RE Regulation 14(2), 2020.
