# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
KSEB Solar Watch
================
Monitors a watchlist of KSEB distribution transformers and sends a
Telegram alert when balance_kw crosses a threshold (default: 3 kW).

Data source: https://wss.kseb.in/selfservices/reCap (public, no auth)
Alerts on transition only — once notified, won't re-alert until value
drops below threshold and crosses again.

Designed for GitHub Actions. State persisted via Actions Cache.

ENV VARS (required):
    TELEGRAM_BOT_TOKEN     bot token from @BotFather
    TELEGRAM_CHAT_ID       your chat id (get from @userinfobot)

FILES:
    watchlist.json         which transformers to monitor (committed)
    state.json             last-known values per DTR (cached, not committed)
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = "https://wss.kseb.in/selfservices"
TIMEOUT = 30.0
HEADERS = {
    "User-Agent": "kseb-solar-watch/0.1 (+civic-tech personal monitor)",
    "Referer": f"{BASE}/reCap",
    "Origin": "https://wss.kseb.in",
    "Accept": "application/json, */*",
}

WATCHLIST_FILE = Path("watchlist.json")
STATE_FILE = Path("state.json")


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

@dataclass
class DTRState:
    dtr_id: str
    transformer_name: str
    section_id: int
    capacity_kva: float
    allowed_cap_kw: float
    feasibility_issued_kw: float
    grid_connected_kw: float
    balance_kw: float
    as_on: str


def fetch_section_dtrs(client: httpx.Client, section_id: int) -> list[dict]:
    """Return raw DTR records for a section."""
    r = client.post(
        f"{BASE}/getDTRAvailable",
        data={"sectionId": section_id},
        headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"},
    )
    r.raise_for_status()
    payload = r.json()
    if payload.get("err_flag") != 0:
        raise RuntimeError(f"KSEB API returned err_flag: {payload.get('disp_msg')}")
    return payload.get("list", []) or []


def parse_dtr(raw: dict, section_id: int) -> DTRState:
    allowed = float(raw["allowed_cap"].split()[0])
    feasible = float(raw.get("regi") or raw.get("feasible") or 0)
    connected = float(raw.get("comp_cap") or 0)
    return DTRState(
        dtr_id=str(raw["id"]),
        transformer_name=raw["transformer_name"],
        section_id=section_id,
        capacity_kva=float(raw["capacity"]),
        allowed_cap_kw=allowed,
        feasibility_issued_kw=feasible,
        grid_connected_kw=connected,
        balance_kw=round(allowed - feasible - connected, 3),
        as_on=raw.get("ason", ""),
    )


def fetch_watchlist_state(watchlist: list[dict]) -> dict[str, DTRState]:
    """Fetch current state for every DTR in watchlist. Keyed by dtr_id."""
    by_section: dict[int, list[dict]] = {}
    for entry in watchlist:
        by_section.setdefault(int(entry["section_id"]), []).append(entry)

    result: dict[str, DTRState] = {}
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as client:
        for section_id, entries in by_section.items():
            raw_list = fetch_section_dtrs(client, section_id)
            by_id = {str(r["id"]): r for r in raw_list}
            for entry in entries:
                dtr_id = str(entry["dtr_id"])
                raw = by_id.get(dtr_id)
                if raw is None:
                    print(f"  ⚠ DTR {dtr_id} not found in section {section_id}", file=sys.stderr)
                    continue
                result[dtr_id] = parse_dtr(raw, section_id)
    return result


# ---------------------------------------------------------------------------
# State (last-seen values)
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception as e:
        print(f"  ⚠ state file unreadable, treating as fresh: {e}", file=sys.stderr)
        return {}


def save_state(state: dict) -> None:
    state["_updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

def send_telegram(message: str) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("  ⚠ Telegram credentials missing — skipping alert", file=sys.stderr)
        print(f"  Would have sent:\n{message}")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    r = httpx.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        },
        timeout=15.0,
    )
    if r.status_code != 200:
        print(f"  ⚠ Telegram send failed: {r.status_code} {r.text}", file=sys.stderr)
    else:
        print("  ✓ Telegram alert sent")


def format_alert(dtr: DTRState, prev_balance: float | None, threshold: float) -> str:
    name = dtr.transformer_name
    return (
        f"🌞 *Solar Capacity Available!*\n\n"
        f"Transformer: *{name}*\n"
        f"Balance now: *{dtr.balance_kw} kW* "
        f"(was {prev_balance if prev_balance is not None else 'unknown'} kW)\n"
        f"Threshold: ≥ {threshold} kW\n\n"
        f"📊 *Details*\n"
        f"• Capacity: {dtr.capacity_kva} kVA ({dtr.allowed_cap_kw} kW allowed)\n"
        f"• Grid connected: {dtr.grid_connected_kw} kW\n"
        f"• Feasibility issued: {dtr.feasibility_issued_kw} kW\n"
        f"• KSEB as-on: {dtr.as_on}\n\n"
        f"👉 Apply now at ekiran.kseb.in before someone else does."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if not WATCHLIST_FILE.exists():
        print(f"ERROR: {WATCHLIST_FILE} not found.", file=sys.stderr)
        return 2

    watchlist_cfg = json.loads(WATCHLIST_FILE.read_text())
    global_threshold = float(watchlist_cfg.get("alert_threshold_kw", 3.0))
    entries = watchlist_cfg["watch"]
    # Build per-DTR threshold map (fall back to global if not overridden)
    threshold_by_dtr: dict[str, float] = {}
    for e in entries:
        override = e.get("alert_threshold_kw")
        threshold_by_dtr[str(e["dtr_id"])] = (
            float(override) if override is not None else global_threshold
        )
    print(f"Watchlist: {len(entries)} transformer(s), global threshold ≥ {global_threshold} kW")

    try:
        current = fetch_watchlist_state(entries)
    except Exception as e:
        # Silent retry tomorrow — don't alert on transient failures
        print(f"ERROR: fetch failed, will retry next run: {e}", file=sys.stderr)
        return 0

    prev_state = load_state()
    new_state: dict[str, dict] = {}
    alerts_sent = 0

    for dtr_id, dtr in current.items():
        threshold = threshold_by_dtr.get(dtr_id, global_threshold)
        prev = prev_state.get(dtr_id) or {}
        prev_balance = prev.get("balance_kw")
        prev_was_above = bool(prev.get("was_above_threshold", False))
        is_above = dtr.balance_kw >= threshold

        # Alert only on upward transition: below → at-or-above threshold.
        # First-ever run with is_above=True also alerts (you'd want to know).
        should_alert = is_above and not prev_was_above

        prev_b_str = f"{prev_balance} kW" if prev_balance is not None else "—"
        print(
            f"  {dtr.transformer_name:<25} "
            f"balance={dtr.balance_kw:>6.2f} kW  "
            f"threshold={threshold} kW  "
            f"(prev={prev_b_str:>10}, above={is_above}, prev_above={prev_was_above})"
        )

        if should_alert:
            msg = format_alert(dtr, prev_balance, threshold)
            send_telegram(msg)
            alerts_sent += 1

        new_state[dtr_id] = {
            "transformer_name": dtr.transformer_name,
            "balance_kw": dtr.balance_kw,
            "feasibility_issued_kw": dtr.feasibility_issued_kw,
            "grid_connected_kw": dtr.grid_connected_kw,
            "as_on": dtr.as_on,
            "was_above_threshold": is_above,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }

    save_state(new_state)
    print(f"\nDone. {alerts_sent} alert(s) sent. State saved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
