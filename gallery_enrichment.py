"""Gradually fill portal galleries for the static public site."""
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit
import json
import time

from model import TZ, atomic_json, valid_photos
from scraper import DATA, fetch, parse_detail_photos, source_robots_ok
from beach_distance import extract_coordinates, extract_detail_address, listing_description, add_beach_distance, enrich_coastal_locations

CACHE = DATA / 'photo-cache.json'


def enrich_galleries(modes=('coast', 'rent', 'sale'), limit=80):
    """Revisit missing coastal locations and sparse portal galleries each day."""
    try: cache=json.loads(CACHE.read_text())
    except (OSError, ValueError): cache={}
    now=datetime.now(TZ)
    inspected=updated=0
    errors=[]
    blocked_hosts=set()
    for mode in modes:
        if inspected>=limit: break
        try:
            status=json.loads((DATA/mode/'status.json').read_text())
            rows=json.loads((DATA/mode/'listings.json').read_text())
        except (OSError, ValueError): continue
        if status.get('state')=='source-error' and mode!='coast': continue
        active=[row for row in rows if not row.get('stale') and
                urlsplit(row.get('url') or '').scheme in ('http','https')]
        missing_location=[row for row in active if mode=='coast' and row.get('beachDistanceM') is None]
        sparse_gallery=[row for row in active if
                        (urlsplit(row.get('url') or '').hostname or '').endswith('immovlan.be') and
                        len(valid_photos(row.get('photos') or [], listing_url=row.get('url')))<2 and
                        not (mode=='coast' and row.get('beachDistanceM') is None)]
        # Rotate through large catalogues so failures and single-photo ads do not
        # prevent later listings from receiving a gallery.
        def rotated(group):
            if not group:return group
            offset=(now.date().toordinal()*limit)%len(group)
            return group[offset:]+group[:offset]
        candidates=rotated(missing_location)+rotated(sparse_gallery)
        for row in candidates:
            if inspected>=limit: break
            url=row['url'];parsed=urlsplit(url);key=mode+':'+str(row.get('id'))
            host=parsed.hostname or ''
            if host in blocked_hosts:continue
            saved=cache.get(key,{})
            try: checked=datetime.fromisoformat(saved.get('checkedAt',''))
            except (ValueError,TypeError): checked=None
            beach_missing=mode=='coast' and row.get('beachDistanceM') is None
            if checked and saved.get('photoVersion')==2:
                if beach_missing and saved.get('beachVersion')==2 and now-checked<timedelta(days=1):continue
                if not beach_missing and now-checked<timedelta(days=14):continue
            try:
                if not source_robots_ok(parsed.scheme+'://'+parsed.netloc,url):
                    errors.append('Accès aux annonces de '+host+' interdit par robots.txt')
                    blocked_hosts.add(host);continue
                time.sleep(1.2)
                page=fetch(url)
                photos=parse_detail_photos(page,url)
            except Exception as exc:
                errors.append(host+': '+str(exc)[:140])
                blocked_hosts.add(host);continue
            inspected+=1
            merged=valid_photos(list(row.get('photos') or [])+photos,listing_url=url)
            if len(merged)>len(valid_photos(row.get('photos') or [],listing_url=url)):
                row['photos']=merged;updated+=1
            if mode=='coast':
                description=listing_description(page)
                if len(description)>len(row.get('summary') or ''):row['summary']=description
                address=extract_detail_address(page)
                if address and not row.get('streetAddress'):row['streetAddress']=address
                coordinates=extract_coordinates(page)
                if coordinates:row['latitude'],row['longitude']=coordinates
                add_beach_distance(row)
            cache[key]={'checkedAt':now.isoformat(timespec='seconds'),'photoVersion':2,'beachVersion':2 if mode=='coast' else 0,'photos':photos}
        if mode=='coast':enrich_coastal_locations(rows)
        atomic_json(DATA/mode/'listings.json',rows)
    if inspected: atomic_json(CACHE,cache)
    return {'inspected':inspected,'updated':updated,'errors':errors[:2]}
