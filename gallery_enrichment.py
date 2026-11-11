"""Gradually fill portal galleries for the static public site."""
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import json
import time

from model import TZ, atomic_json, valid_photos
from scraper import DATA, fetch, parse_detail_photos, source_robots_ok
from beach_distance import extract_coordinates, listing_description, add_beach_distance

CACHE = DATA / 'photo-cache.json'


def enrich_galleries(modes=('coast', 'rent', 'sale'), limit=80):
    """Fetch at most `limit` one-photo Immovlan ads, obeying robots and a delay."""
    try: cache=json.loads(CACHE.read_text())
    except (OSError, ValueError): cache={}
    now=datetime.now(TZ)
    inspected=updated=0
    errors=[]
    stop_host=False
    for mode in modes:
        if inspected>=limit or stop_host: break
        try:
            status=json.loads((DATA/mode/'status.json').read_text())
            rows=json.loads((DATA/mode/'listings.json').read_text())
        except (OSError, ValueError): continue
        if status.get('state')=='source-error': continue
        candidates=[row for row in rows if not row.get('stale') and
                    (urlsplit(row.get('url') or '').hostname or '').endswith('immovlan.be') and
                    (len(valid_photos(row.get('photos') or [], listing_url=row.get('url')))<2 or
                     (mode=='coast' and row.get('beachDistanceM') is None and row.get('beachWalkMinutes') is None))]
        # Rotate through large catalogues so failures and single-photo ads do not
        # prevent later listings from receiving a gallery.
        if candidates:
            offset=(now.date().toordinal()*limit)%len(candidates)
            candidates=candidates[offset:]+candidates[:offset]
        for row in candidates:
            if inspected>=limit or stop_host: break
            url=row['url'];parsed=urlsplit(url);key=mode+':'+str(row.get('id'))
            saved=cache.get(key,{})
            try: checked=datetime.fromisoformat(saved.get('checkedAt',''))
            except (ValueError,TypeError): checked=None
            beach_missing=mode=='coast' and row.get('beachDistanceM') is None and row.get('beachWalkMinutes') is None
            if checked and now-checked<timedelta(days=14) and saved.get('photoVersion')==2 and (not beach_missing or saved.get('beachVersion')==1): continue
            try:
                if not source_robots_ok(parsed.scheme+'://'+parsed.netloc,url):
                    errors.append('Accès aux annonces Immovlan interdit par robots.txt')
                    stop_host=True;break
                time.sleep(1.2)
                page=fetch(url)
                photos=parse_detail_photos(page,url)
            except Exception as exc:
                errors.append(str(exc)[:160])
                stop_host=True;break
            inspected+=1
            merged=valid_photos(list(row.get('photos') or [])+photos,listing_url=url)
            if len(merged)>len(valid_photos(row.get('photos') or [],listing_url=url)):
                row['photos']=merged;updated+=1
            if mode=='coast':
                description=listing_description(page)
                if len(description)>len(row.get('summary') or ''):row['summary']=description
                coordinates=extract_coordinates(page)
                if coordinates:row['latitude'],row['longitude']=coordinates
                add_beach_distance(row)
            cache[key]={'checkedAt':now.isoformat(timespec='seconds'),'photoVersion':2,'beachVersion':1 if mode=='coast' else 0,'photos':photos}
        atomic_json(DATA/mode/'listings.json',rows)
    if inspected: atomic_json(CACHE,cache)
    return {'inspected':inspected,'updated':updated,'errors':errors[:2]}
