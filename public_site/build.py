"""Export only public advert fields; never copy local criteria, logs, or overrides."""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import argparse
import hashlib
import json
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model import DEFAULT_RENT, DEFAULT_SALE, RENOVATION_RATES, RENOVATION_REFERENCE, valid_photos
from scraper import AREAS, NEARBY_AREAS
from gems import select_gems

COMMUNES = ['Anderlecht','Auderghem','Berchem-Sainte-Agathe','Bruxelles-Ville','Etterbeek','Evere','Forest','Ganshoren','Ixelles','Jette','Koekelberg','Molenbeek-Saint-Jean','Saint-Gilles','Saint-Josse-ten-Noode','Schaerbeek','Uccle','Watermael-Boitsfort','Woluwe-Saint-Lambert','Woluwe-Saint-Pierre']
FIELDS = set('id source sourceType agencyDomain url title summary location postalCode streetAddress price displayPrice priceLabel priceType saleType fees bedrooms bathrooms area floor propertyType subtype construction constructionYear condition occupancy availability available energyRating energyRegion publicationDate publicationDateUncertain publicationDateOrigin firstDiscovered lastObserved stale latitude longitude agencyName agencyLogo agencyWebsite'.split())
FEATURES = set('terrace balcony garden parking lift cellar accessible petsAllowed furnished'.split())


def read(path, default):
    try: return json.loads(Path(path).read_text())
    except (OSError, ValueError): return default


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def defaults():
    return {m: {**c, 'areas': ', '.join(COMMUNES), 'nearby': False} for m,c in [('rent',DEFAULT_RENT),('sale',DEFAULT_SALE)]}


def sanitize_row(row, cached=None):
    cached = cached or {}
    result = {k: v for k,v in row.items() if k in FIELDS and isinstance(v,(str,int,float,bool,type(None)))}
    for k in ('agencyName','agencyLogo','agencyWebsite'):
        if isinstance((cached.get('branding') or {}).get(k),str): result[k]=cached['branding'][k]
    result['features'] = {k: v for k,v in (row.get('features') or {}).items() if k in FEATURES and (v is True or v is False or v is None)}
    result['photos'] = valid_photos(list(row.get('photos') or []) + list(cached.get('photos') or []))[:12]
    return result


def sanitize_status(status):
    result = {k:status[k] for k in ('lastRun','lastAttempt','state','partial','transaction') if k in status}
    result['nextRun'] = '10 h et 17 h · heure belge (horaire indicatif)'
    result['sources'] = [{k:r[k] for k in ('source','ok','found','partial') if k in r} for r in status.get('sources',[]) if isinstance(r,dict)]
    if status.get('error'): result['error']='La dernière collecte n’a pas abouti.'
    return result


def build(output, data_dir=None, state_output=None):
    output=Path(output); data_dir=Path(data_dir or ROOT/'data'); output.mkdir(parents=True,exist_ok=True)
    config={'defaults':defaults(),'areaAliases':AREAS,'nearby':NEARBY_AREAS,'renovationRates':RENOVATION_RATES,'renovationReference':RENOVATION_REFERENCE}
    files={}; photo_cache=read(data_dir/'photo-cache.json',{})
    for mode in ('rent','sale'):
        seed=read(ROOT/'public-data'/(mode+'.json'),{})
        source=read(data_dir/mode/'listings.json',seed.get('items',[]))
        rows=[sanitize_row(r,photo_cache.get(mode+':'+str(r.get('id')),{})) for r in source]
        status=sanitize_status(read(data_dir/mode/'status.json',seed.get('status',{})))
        if state_output: write(Path(state_output)/(mode+'.json'),{'items':rows,'status':status})
        active=[r for r in rows if not r.get('stale')]
        gems=select_gems(active,config['defaults'][mode],mode,limit=len(active))
        notes={r['id']:r['gem'] for r in gems}
        for r in active:
            if r.get('id') in notes:
                r['gem']=notes[r['id']]
                r['gem']['reasons']=[reason for reason in r['gem']['reasons'] if reason!='Correspond à tes critères enregistrés']
        payload=json.dumps({'items':active,'status':status},ensure_ascii=False,separators=(',',':'))
        digest=hashlib.sha256(payload.encode()).hexdigest()[:16]
        files[mode]=f'{mode}-{digest}.json'
        (output/'data').mkdir(exist_ok=True)
        (output/'data'/files[mode]).write_text(payload+'\n')
    revision=hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()[:16]
    write(output/'data/manifest.json',{'revision':revision,'files':files,'config':config})
    # Public-only HTML remains a sibling variant of the local app.
    html=(ROOT/'index.html').read_text().replace('href="/app.css"','href="app.css"')
    html=html.replace('<script src="/app.js" defer></script>', '<script src="search.js" defer></script><script src="api.js" defer></script><script src="app.js" defer></script><script src="boot.js" defer></script>')
    html=html.replace('Collectes · 10 h et 17 h','Collectes · vers 10 h et 17 h')
    html=html.replace('⌕ Rechercher ici','Appliquer les filtres')
    html=html.replace('<p class="immoweb-note">','<p class="immoweb-note">Tes critères et favoris sont conservés uniquement dans ce navigateur. ')
    (output/'index.html').write_text(html)
    (output/'.nojekyll').touch()
    for file in ('app.css','app.js'):shutil.copy2(ROOT/file,output/file)
    for file in ('search.js','api.js','boot.js'):shutil.copy2(ROOT/'public_site'/file,output/file)
    return files


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',default=str(ROOT/'_site'));parser.add_argument('--state-output');args=parser.parse_args()
    build(args.output,state_output=args.state_output)
    print('Site statique généré :',args.output)
