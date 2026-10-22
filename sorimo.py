"""Sorimo's public Webulous catalogue and listing pages."""
import html
import json
import re
import time
from urllib.parse import urljoin, urlsplit
from model import number_or_none, valid_photos, extract_features

HOST = 'https://www.sorimo.be'
CATALOGUES = {'rent': HOST+'/fr/7/chercher-bien/a-louer', 'sale': HOST+'/fr/2/chercher-bien/a-vendre'}
LOGO = 'https://cdn.webulous.io/sites/31UG0RNJZA/images/logo_main.png?170720260337'

def text(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', value or '')).split())

def field(fragment, classname):
    match = re.search(r'<[^>]+class=["\']'+re.escape(classname)+r'["\'][^>]*>(.*?)</(?:div|span)>', fragment, re.S)
    return text(match[1]) if match else ''

def next_page(page):
    for href in re.findall(r'href=["\']([^"\']+)["\']', page):
        url = urljoin(HOST, html.unescape(href)); parsed = urlsplit(url)
        if parsed.scheme == 'https' and parsed.netloc == 'www.sorimo.be' and parsed.path == '/fr/List/InfiniteScroll':
            return url
    return None

def parse_cards(page, mode):
    route = 'a-louer' if mode == 'rent' else 'a-vendre'
    rows = []
    for href, card in re.findall(r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*class=["\']estate-card["\'][^>]*>(.*?)</a>', page, re.S):
        match = re.fullmatch(r'/fr/bien/'+route+r'/(appartement|maison)/([^/]+)/(\d+)', href)
        if not match: continue
        flag = field(card, 'estate-flag__text')
        # Status classes can carry modifiers; inspect their text separately.
        flags = ' '.join(text(v) for v in re.findall(r'<div[^>]*class=["\'][^"\']*estate-flag__text[^"\']*["\'][^>]*>(.*?)</div>',card,re.S)).lower()
        if re.search(r'option|loué|vendu|sous offre', flags): continue
        kind, locality, ident = match.groups()
        photo = re.search(r'<img[^>]*src=["\']([^"\']+)["\'][^>]*alt=["\']([^"\']*)', card)
        title = html.unescape(photo[2]).split(' - ')[0] if photo else ('Appartement' if kind == 'appartement' else 'Maison')
        def fact(icon):
            found = re.search(r'<i[^>]*\b'+icon+r'\b[^>]*></i>\s*([\d.,]+)', card)
            return number_or_none(found[1]) if found else None
        price = number_or_none(re.sub(r'[^\d,.]', '', field(card, 'estate-card__text-details-price')))
        city = field(card, 'estate-card__text')
        postal = locality.split('-')[0]
        energy = re.search(r'alt=["\']((?:PEB|EPC)\s*:[^"\']+)',card)
        rows.append({'id':'sorimo-'+ident,'source':'Sorimo','sourceType':'agency-site','agencyName':'Sorimo','agencyWebsite':HOST,'agencyDomain':'sorimo.be','agencyLogo':LOGO,
            'url':HOST+href,'title':title,'propertyType':'Apartment' if kind=='appartement' else 'House','location':postal+' '+city,'postalCode':postal,
            'price':price,'fees':None,'bedrooms':fact('fa-bed'),'bathrooms':fact('fa-bath'),'area':fact('fa-arrows-alt'),
            'photos':valid_photos([html.unescape(photo[1])]) if photo else [],'summary':title,'energyText':html.unescape(energy[1]) if energy else '', 'publicationDate':None})
    return rows

def enrich(row, page):
    row = dict(row)
    match = re.search(r'\bvar estate\s*=\s*',page)
    if not match: raise ValueError('Sorimo listing metadata missing')
    data = json.JSONDecoder().raw_decode(page[match.end():])[0]
    if str(data.get('id')) != row['id'].removeprefix('sorimo-'): raise ValueError('Sorimo listing identity mismatch')
    description = text(data.get('short_description') or data.get('sms_description'))
    row.update({'summary':description[:1800], 'features':extract_features(description)})
    for target, source in [('price','price'),('area','surface_livable'),('bedrooms','number_of_bedrooms')]:
        value = number_or_none(data.get(source))
        if value is not None: row[target] = value
    row['streetAddress'] = data.get('address_street') or None
    row['energyText'] += ' '+description
    # Table labels are explicit yes/no declarations, not guesses from photographs.
    features={'Meublé':'furnished','Garage':'parking','Terrasse':'terrace','Jardin':'garden','Ascenseur':'lift','Cave':'cellar'}
    for fragment in re.findall(r'<tr\b[^>]*>.*?</tr>',page,re.S):
        cells = re.findall(r'<t[hd]\b[^>]*>(.*?)</t[hd]>',fragment,re.S)
        if len(cells)<2: continue
        label, value = text(cells[0]), text(cells[1])
        if label in features and value.lower() in ('oui','non'): row['features'][features[label]] = value.lower()=='oui'
        if label == 'Charges locataire (montant)': row['fees']=number_or_none(re.sub(r'[^\d,.]','',value))
    # Restrict images to this property's ID; related cards never enter its gallery.
    ident = row['id'].removeprefix('sorimo-'); photos=[]; seen=set()
    for url in re.findall(r'https://r2\.storagewhise\.eu/sorimo/Pictures/'+ident+r'/[^\s"\'<>\\]+',html.unescape(page)):
        key=urlsplit(url).path.rsplit('/',1)[-1]
        if key not in seen: seen.add(key); photos.append(url)
    row['photos']=valid_photos(photos or row['photos'])[:12]
    return row

def collect_sorimo(mode, criteria, fetch, robots_ok, area_matches, pause=time.sleep, max_pages=30):
    if mode not in CATALOGUES: raise ValueError('Unknown transaction mode')
    result={'source':'Sorimo','transaction':mode,'ok':False,'found':0,'pages':0,'partial':False}
    rows={}; visited=set(); errors=[]; url=CATALOGUES[mode]
    def read(url):
        if not robots_ok(HOST,url): raise PermissionError('Sorimo robots.txt disallows this page')
        pause(1.2)
        return fetch(url)
    try:
        page=read(url); url=next_page(page)
        if not url: raise ValueError('Sorimo catalogue pagination link missing')
        while url and result['pages']<max_pages:
            if url in visited: raise ValueError('Sorimo pagination repeated a page')
            visited.add(url); page=read(url); result['pages']+=1
            cards=parse_cards(page,mode)
            wanted=(criteria.get('property') or 'Apartment').lower()
            for row in cards:
                if row['propertyType'].lower() not in wanted or not area_matches(criteria,row['location']): continue
                rows[row['id']]=row
            following=next_page(page)
            if not cards and not re.search(r'class=["\']estate-card["\']',page) and following:
                raise ValueError('Sorimo returned unrecognized catalogue markup')
            url=following
        if url: result['partial']=True; errors.append('Catalogue limité à '+str(max_pages)+' pages.')
        for ident,row in list(rows.items()):
            try: rows[ident]=enrich(row,read(row['url']))
            except Exception as exc: result['partial']=True; errors.append(str(exc)[:150])
        result['ok']=True
    except Exception as exc:
        errors.append(str(exc)[:200]); result['partial']=True
        result['ok']=bool(rows)
    result['found']=len(rows)
    if errors: result['reason']='; '.join(dict.fromkeys(errors))[:600]
    return list(rows.values()),result

def refresh_modes(modes=('rent','sale')):
    # Targeted refresh preserves all other source records and uses the normal lock.
    import sys, fcntl
    from datetime import datetime
    from scraper import fetch, source_robots_ok, source_area_matches, mode_file, TZ
    from model import atomic_json, normalize_listing, evaluate_listing, best_rows
    for mode in modes:
        with mode_file(mode,'.collection.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            criteria=json.loads(mode_file(mode,'criteria.json').read_text())
            old=json.loads(mode_file(mode,'listings.json').read_text()); previous={r['id']:r for r in old}
            rows,result=collect_sorimo(mode,criteria,fetch,source_robots_ok,source_area_matches)
            now=datetime.now(TZ); result['lastRun']=now.isoformat(timespec='seconds')
            normalized=[]
            for row in rows:
                row=normalize_listing(row,mode,now.date().isoformat(),previous)
                evaluate_listing(row,criteria,mode,row.get('renovationOverride')); normalized.append(row)
            ids={r['id'] for r in normalized}
            keep=[r for r in old if r.get('source')!='Sorimo']
            if not result['ok'] or result['partial']:
                keep.extend({**r,'stale':True} for r in old if r.get('source')=='Sorimo' and r['id'] not in ids)
            merged=best_rows(keep+normalized,criteria)
            atomic_json(mode_file(mode,'listings.json'),merged)
            status=json.loads(mode_file(mode,'status.json').read_text())
            status['sources']=[r for r in status.get('sources',[]) if r.get('source')!='Sorimo']+[result]
            if result['ok']:status['activeSources']=sorted(set(status.get('activeSources',[])+['Sorimo']))
            status['partial']=any(not r.get('ok') or r.get('partial') for r in status['sources'])
            status['state']='partial' if status['partial'] else 'complete'
            status.update({'totalCollected':len(merged),'displayedCount':len(merged),'matchingCount':sum(r.get('matchState')=='confirmed' for r in merged),'unknownCount':sum(r.get('matchState')=='unknown' for r in merged)})
            atomic_json(mode_file(mode,'status.json'),status)
            print(json.dumps(result,ensure_ascii=False),flush=True)

if __name__ == '__main__':
    import sys
    refresh_modes(sys.argv[1:] or ['rent','sale'])
