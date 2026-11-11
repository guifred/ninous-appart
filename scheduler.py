#!/usr/bin/env python3
"""Twice-daily Europe/Brussels scheduler."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
import json
import time
from scraper import collect_all
from agency_discovery import verify_sites
from gallery_enrichment import enrich_galleries

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
TZ = ZoneInfo('Europe/Brussels')


def next_run(now):
    candidates = [now.replace(hour=hour, minute=0, second=0, microsecond=0)
                  for hour in (10, 17)]
    upcoming = [candidate for candidate in candidates if candidate > now]
    if upcoming:
        return min(upcoming)
    return (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)


def daily_run():
    print('Starting scheduled collection at', datetime.now(TZ).isoformat(timespec='seconds'))
    # Prioritize coastal catalogues so their daily refresh completes even if
    # broader Brussels collection or agency discovery takes longer.
    outcomes=collect_all(order=('coast','rent','sale'))
    print('Collection outcomes:',json.dumps(outcomes,ensure_ascii=False),flush=True)
    try:
        galleries=enrich_galleries(limit=80)
        print('Photo galleries:',json.dumps(galleries,ensure_ascii=False),flush=True)
    except Exception as e:
        print('Photo gallery enrichment failed:',str(e)[:300],flush=True)
    # Recheck discovered agencies after the time-sensitive collections.
    try:
        coverage=verify_sites(limit=500)
        print('Agency site checks:',json.dumps(coverage,ensure_ascii=False))
    except Exception as e:
        print('Agency discovery failed:',str(e)[:500])
    return outcomes


def main():
    # macOS launchd invokes this at 10:00 and 17:00 Europe/Brussels.
    outcomes = daily_run()
    if any(not outcome.get('ok') for outcome in outcomes.values()):
        raise SystemExit(1)

if __name__ == '__main__':
    main()
