# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx>=0.27.0"]
# ///
"""
One-time helper: look up a transformer's `dtr_id` by name within a section.

Usage:
    python find_dtr_id.py 5567 "SAHALA POLYMER"

Outputs the matching dtr_id(s) — paste into watchlist.json.
"""

import sys
import httpx

BASE = "https://wss.kseb.in/selfservices"
HEADERS = {
    "User-Agent": "kseb-solar-watch/0.1 (one-time lookup)",
    "Referer": f"{BASE}/reCap",
    "Origin": "https://wss.kseb.in",
}


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python find_dtr_id.py <section_id> <name_substring>")
        return 2
    section_id = int(sys.argv[1])
    needle = sys.argv[2].upper()

    r = httpx.post(
        f"{BASE}/getDTRAvailable",
        data={"sectionId": section_id},
        headers={
            **HEADERS,
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        },
        timeout=30.0,
    )
    r.raise_for_status()
    payload = r.json()
    matches = [d for d in payload["list"] if needle in d["transformer_name"].upper()]

    if not matches:
        print(f"No DTRs in section {section_id} match '{needle}'")
        print("Sample names from this section:")
        for d in payload["list"][:10]:
            print(f"  - {d['transformer_name']}")
        return 1

    print(f"Found {len(matches)} match(es) in section {section_id}:\n")
    for d in matches:
        allowed = float(d["allowed_cap"].split()[0])
        feasible = float(d.get("regi") or d.get("feasible") or 0)
        connected = float(d.get("comp_cap") or 0)
        balance = round(allowed - feasible - connected, 2)
        print(f"  dtr_id    = {d['id']}")
        print(f"  name      = {d['transformer_name']}")
        print(f"  feeder    = {d.get('feeder_name', '')}")
        print(f"  capacity  = {d['capacity']} kVA  ({allowed} kW allowed)")
        print(f"  connected = {connected} kW")
        print(f"  issued    = {feasible} kW")
        print(f"  balance   = {balance} kW")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
