#!/usr/bin/env python3
"""Twice-daily Europe/Brussels scheduler."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import time
from scraper import collect_all
from agency_discovery import verify_sites

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
TZ = ZoneInfo('Europe/Brussels')


def next_run(now):
    candidates = [now.replace(hour=hour, minute=0, second=0, microsecond=0)
                  for hour in (10, 17)]
    upcoming = [candidate for candidate in candidates if candidate > now]
    if upcoming:
        return min(upcoming)
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def daily_run():
    print('Starting scheduled collection at', datetime.now(TZ).isoformat(timespec='seconds'))
    # Recheck only websites with recorded terms permission. Discovery itself uses
    # a user-supplied licensed CBE Open Data archive and is run when that changes.
    try:
        # Recheck the complete bounded agency registry each run (currently <100
        # sites); public pages are still gated by recorded permission and robots.
        coverage=verify_sites(limit=500)
        print('Agency site checks:',json.dumps(coverage,ensure_ascii=False))
    except Exception as e:
        print('Agency discovery failed:',str(e)[:500])
    # Each transaction runs independently so a rent-source failure cannot skip sales.
    outcomes=collect_all()
    print('Collection outcomes:',json.dumps(outcomes,ensure_ascii=False))
    return outcomes


def main():
    # macOS launchd invokes this at 10:00 and 17:00 Europe/Brussels.
    outcomes = daily_run()
    if any(not outcome.get('ok') for outcome in outcomes.values()):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
