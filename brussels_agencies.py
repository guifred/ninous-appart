"""Public agency catalogues requested by the user; per-domain access and coverage."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlsplit
from html.parser import HTMLParser
import json, re, time, html
from agency_discovery import _fetch, _robots, normalized_domain, now, _transaction_paths
from model import atomic_json

ROOT=Path(__file__).resolve().parent
REGISTRY=ROOT/'data/agencies/brussels-sources.json'
REPORT=ROOT/'data/agencies/brussels-coverage.json'
CACHE=Path('/tmp/ninou-agency-audit')

def restricted_agency_domains():
    """Domains whose recorded site terms require prior written permission."""
    path=ROOT/'data/agencies/requested-agencies.json'
    if not path.exists():return set()
    try: agencies=json.loads(path.read_text()).get('agencies',[])
    except (OSError,ValueError): return set()
    return {normalized_domain(a.get('website') or ('https://'+a['domain']))
            for a in agencies if a.get('siteTermsStatus')=='restricted' and (a.get('website') or a.get('domain'))}

class Links(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.images=[];self.current=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'):self.current={'href':a['href'],'text':[]}
        if tag=='img':self.images.append(a)
    def handle_data(self,data):
        if self.current is not None:self.current['text'].append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:
            self.links.append((self.current['href'],' '.join(' '.join(self.current['text']).split())));self.current=None

def seed():
    entries={}
    for s in json.loads((ROOT/'data/agencies/sites.json').read_text()):
        name=(s.get('brands') or [s['domain']])[0]
        if s['domain'] in ('allten.be','ambbroker.be'):continue
        entries[s['domain']]={'name':name,'website':s['website'],'enabled':False,'requestBasis':'User requested all Brussels agencies, 2026-10-07'}
    for name,url in [('Victoire','https://victoire.be/fr/'),('Latour & Petit','https://latouretpetit.be/'),('5th Corner','https://www.5thcorner.be/fr/home-7/')]:
        entries[normalized_domain(url)]={'name':name,'website':url,'enabled':False,'requestBasis':'User requested all Brussels agencies, 2026-10-07'}
    if REGISTRY.exists():
        for old in json.loads(REGISTRY.read_text()):entries[normalized_domain(old['website'])]=old
    blocked=restricted_agency_domains()
    return [entry for entry in entries.values() if normalized_domain(entry['website']) not in blocked]

def discover_catalogues(page,home,mode):
    """Choose same-site search/archive links from the homepage and its labels."""
    links=Links();links.feed(page);host=normalized_domain(home)
    desired=('rent','rental','location','louer','huren','verhuur') if mode=='rent' else ('sale','vente','vendre','koop','buy','verkopen')
    other=('vendre','vente','sale','koop') if mode=='rent' else ('louer','location','rent','huren','verhuur')
    out=[]
    for href,label in links.links:
        url=urljoin(home,html.unescape(href).strip());p=urlsplit(url);path=p.path.lower();word=(path+' '+label.lower())
        if p.scheme!='https' or normalized_domain(url)!=host:continue
        if not any(w in word for w in desired):continue
        if any(w in path for w in other) and not any(w in path for w in desired):continue
        if re.search(r'/\d{4,}/?$',path) or re.search(r'/(?:contact|blog|actualit|offre|service|estimation|mettre-en|vendre-avec|louer-avec)(?:/|$)',path):continue
        if p.path in ('/','/fr','/nl','/en'):continue
        out.append(url)
    # Prefer archive routes (not an individual ad), exact search paths, then stable order.
    out=list(dict.fromkeys(out));out.sort(key=lambda u:(bool(re.search(r'/\d{4,}/?$',urlsplit(u).path)),len(urlsplit(u).path.split('/')),len(u)))
    return out[:4]

def audit_one(site):
    site=dict(site);cache={};domain=normalized_domain(site['website']);folder=CACHE/domain;folder.mkdir(parents=True,exist_ok=True)
    def read(url,filename):
        allowed,reason=_robots(url,cache)
        if not allowed:raise RuntimeError('robots: '+reason)
        page,final=_fetch(url);(folder/filename).write_text(page);time.sleep(1)
        return page,final
    try:
        page,home=read(site['website'],'home.html');site['website']=home
        if any(t in page.lower() for t in ('cf-chl-','verify you are human','just a moment...')):raise RuntimeError('Browser challenge')
        site['catalogues']={};site['samples']={};links=Links();links.feed(page)
        logos=[urljoin(home,a.get('data-src') or a.get('src') or '') for a in links.images if 'logo' in str(a).lower() and 'cookie' not in str(a).lower()]
        if logos:site['logo']=next((u for u in logos if u.startswith('https://')),None)
        for mode in ('rent','sale'):
            paths=discover_catalogues(page,home,mode)
            if normalized_domain(home)=='latouretpetit.be':paths=['https://latouretpetit.be/fr/nos-biens/'+('location' if mode=='rent' else 'vente')]
            # Archive paths only; exclude individual ads and service/marketing pages.
            paths=[u for u in paths if not re.search(r'/\d{5,}/?$|contact|estim|gestion|blog|actualit|/services?/',u,re.I)]
            site['catalogues'][mode]=paths
            samples=[]
            for i,url in enumerate(paths[:2]):
                try:
                    body,final=read(url,f'{mode}-{i}.html')
                    samples.append({'url':final,'file':f'{mode}-{i}.html','bytes':len(body),'webulous':'/List/InfiniteScroll' in body,'jsonld':bool(re.search('application/ld',body)),'nextjs':'__NEXT_DATA__' in body})
                except Exception as exc:samples.append({'url':url,'error':str(exc)[:120]})
            site['samples'][mode]=samples
        site['auditStatus']='checked';site['auditError']=None
    except Exception as exc:site['auditStatus']='unavailable';site['auditError']=str(exc)[:200]
    site['lastChecked']=now()
    return site

def audit():
    sites=seed();out=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(audit_one,s) for s in sites]
        for future in as_completed(futures):
            s=future.result();out.append(s);print(json.dumps({k:s.get(k) for k in ('name','auditStatus','auditError','samples')},ensure_ascii=False),flush=True)
    atomic_json(REGISTRY,sorted(out,key=lambda s:s['name']))
    return out

def collect_site(site,mode,criteria,*,cached=False,max_pages=45,max_details=30):
    from agency_parsers import parse_catalogue,structured_detail,pagination,brand,kind,clean
    from agency_discovery import _jsonld_item_urls, SSL_CONTEXT, UA
    from scraper import source_area_matches
    from urllib.request import Request,urlopen
    from model import valid_photos,number_or_none,extract_features
    site=dict(site);home=site['website'];domain=normalized_domain(home);rules={};last=0
    result={'source':site['name'],'domain':domain,'transaction':mode,'ok':False,'found':0,'parsed':0,'pages':0,'details':0,'partial':False};rows={};errors=[]
    def read(url,payload=None):
        nonlocal last
        if normalized_domain(url)!=domain:raise ValueError('Cross-domain catalogue rejected')
        ok,reason=_robots(url,rules)
        if not ok:raise PermissionError('robots '+reason)
        wait=1.1-(time.monotonic()-last)
        if wait>0:time.sleep(wait)
        last=time.monotonic()
        if payload is None:return _fetch(url)[0]
        req=Request(url,data=json.dumps(payload).encode(),headers={'User-Agent':UA,'Content-Type':'application/json','Accept':'application/json'})
        with urlopen(req,timeout=25,context=SSL_CONTEXT) as response:return response.read(8_000_000).decode()
    def add(row):
        if not row.get('url') or not row.get('location'):return
        wanted=(criteria.get('property') or 'Apartment').lower()
        if (row.get('propertyType') or kind(row.get('title','')) or '').lower() not in wanted:return
        if not source_area_matches(criteria,row['location']):return
        rows[row['url']]=row
    try:
        if domain=='latouretpetit.be':
            from scraper import matches_areas
            catalogue='https://latouretpetit.be/fr/nos-biens/'+('location' if mode=='rent' else 'vente')
            page=read(catalogue);decoded=page.replace('\\"','"')
            endpoint=re.search(r'"endpoint":"(/api/estates/[^"\s]+)"',decoded)
            if not endpoint:raise ValueError('Latour & Petit public search endpoint missing')
            endpoint=urljoin(home,endpoint[1]);zipcodes=[slug.split('-')[0] for slug,_ in matches_areas(criteria) if slug[:4].isdigit()]
            total_seen=0
            for page_no in range(1,max_pages+1):
                data=json.loads(read(endpoint,{'filters':{'zipcodes':zipcodes},'pagination':{'limit':10,'page':page_no},'sort':'updated_at','locale':'fr'}))
                records=data.get('estates')
                if not isinstance(records,list):raise ValueError('Latour & Petit search response not recognized')
                result['pages']+=1;total_seen+=len(records)
                for item in records:
                    url=urljoin(home,item.get('url',''));ptype=kind(url)
                    if not ptype or (item.get('purposeStatus') or {}).get('id') not in (1,2):continue
                    desc=next((d.get('content','') for d in item.get('longDescription',[]) if d.get('languageId')=='fr-BE'),'')
                    features=extract_features(clean(desc))
                    for target,field in [('terrace','terrace'),('garden','garden'),('parking','parking'),('furnished','furnished')]:
                        if item.get(field) in (0,1):features[target]=bool(item[field])
                    fees=None
                    for detail in item.get('details',[]):
                        if 'charges locataire' in detail.get('label','').lower():fees=number_or_none(detail.get('value'))
                        if detail.get('label','').lower()=='ascenseur' and detail.get('value') in ('0','1'):features['lift']=detail['value']=='1'
                    row={**brand(site,url),'transaction':mode,'title':'Appartement' if ptype=='Apartment' else 'Maison','propertyType':ptype,'price':item.get('price') if item.get('displayPrice',True) else None,'fees':fees,'area':item.get('area'),'bedrooms':item.get('rooms'),'bathrooms':item.get('bathRooms'),'location':str(item.get('zip',''))+' '+str(item.get('city','')),'postalCode':str(item.get('zip','')),'photos':valid_photos([p.get('urlLarge') or p.get('urlXXL') for p in item.get('pictures',[]) if p.get('urlLarge') or p.get('urlXXL')]),'summary':clean(desc)[:1800],'features':features,'energyRating':item.get('energyClass'),'energyText':clean(desc),'publicationDate':item.get('putOnlineDateTime'),'sourceModified':item.get('updateDateTime')}
                    result['parsed']+=1;add(row)
                if total_seen>=data.get('totalCount',total_seen):break
                if not records:raise ValueError('Empty catalogue page before totalCount reached')
            else:result['partial']=True;errors.append('Catalogue page cap reached')
            result['ok']=True
        else:
            samples=site.get('samples',{}).get(mode,[])
            paths=[s['url'] for s in samples if not s.get('error') and ('/bien/' not in s['url']) and not re.search(r'/\d{5,}/?$',urlsplit(s['url']).path)]
            paths=[p for p in paths if not re.search(r'/services?/|/Page/|/page/|verhuren|verkopen|/\d{5,}/?$',urlsplit(p).path)]
            paths=list(dict.fromkeys(paths))[:2]
            if not paths:raise ValueError('No public '+mode+' catalogue identified')
            queue=list(paths);visited=set();detail_candidates=set();has_supported=False
            route=('a-louer','location','te-huur','rent') if mode=='rent' else ('a-vendre','vente','te-koop','sale')
            while queue and result['pages']<max_pages:
                url=queue.pop(0)
                if url in visited:continue
                visited.add(url);page=read(url);result['pages']+=1
                found=parse_catalogue(page,url,mode,site);result['parsed']+=len(found)
                if found:has_supported=True
                for row in found:add(row)
                links=Links();links.feed(page)
                feeds=[urljoin(url,u) for u in links.links if '/List/InfiniteScroll?' in u]
                for target in feeds+pagination(page,url):
                    if normalized_domain(target)==domain and target not in visited and target not in queue:queue.append(target)
                detail_candidates.update(_jsonld_item_urls(page,url))
                page_links=Links();page_links.feed(page)
                for href,label in page_links.links:
                    target=urljoin(url,html.unescape(href).strip());path=urlsplit(target).path.lower()
                    if normalized_domain(target)==domain and any(w in path for w in route) and re.search(r'/\d{5,}/?$',path):detail_candidates.add(target)
                # RealEstateListing detail URLs are found in ItemList even when card HTML is client-rendered.
                if 'numberOfItems' in page and detail_candidates and not queue:result['partial']=True
            if queue:result['partial']=True;errors.append('Catalogue page cap reached')
            route=('a-louer','location','te-huur','rent') if mode=='rent' else ('a-vendre','vente','te-koop','sale')
            candidates=[u for u in sorted(detail_candidates) if normalized_domain(u)==domain and any(w in u.lower() for w in route)]
            # Existing card rows already have their location; enrich only selected ones.
            detail_urls=list(dict.fromkeys(candidates if not rows else []))
            if len(detail_urls)>max_details:errors.append('Détails complémentaires limités à 30 pages')
            for url in detail_urls[:max_details]:
                try:
                    page=read(url);result['details']+=1
                    detail_rows=structured_detail(page,url,mode,site)
                    if detail_rows:has_supported=True
                    for row in detail_rows:
                        result['parsed']+=int(url not in rows)
                        if url in rows:
                            rows[url].update({k:v for k,v in row.items() if v is not None and v not in ('',[])})
                        else:add(row)
                    # Webulous publishes the same explicit estate object as Sorimo.
                    if url in rows and re.search(r'\bvar estate\s*=',page):
                        from sorimo import enrich
                        original=rows[url];temp={**original,'id':'sorimo-'+url.rstrip('/').split('/')[-1]}
                        enriched=enrich(temp,page);enriched['id']=original['id'];rows[url]=enriched
                except Exception as exc:errors.append(str(exc)[:140])
            if not has_supported and not rows:raise ValueError('Public catalogue structure not supported or no active residential adverts')
            result['ok']=True
    except Exception as exc:errors.append(str(exc)[:200]);result['partial']=True
    result['found']=len(rows);result['lastRun']=now()
    if errors:result['reason']='; '.join(dict.fromkeys(errors))[:700]
    return list(rows.values()),result

def collect_brussels(mode,criteria,only=None,workers=4):
    sites=json.loads(REGISTRY.read_text()) if REGISTRY.exists() else []
    blocked=restricted_agency_domains()
    if isinstance(only,list):
        sites=[s for s in sites if s['name'] in only]
    elif only=='all':
        sites=[s for s in sites if s.get('enabled') or s.get('auditStatus')=='checked']
    else:
        sites=[s for s in sites if s.get('enabled')]
    sites=[s for s in sites if normalized_domain(s['website']) not in blocked]
    out=[];results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        tasks={pool.submit(collect_site,s,mode,criteria):s for s in sites}
        for task in as_completed(tasks):
            rows,status=task.result();out.extend(rows);results.append(status)
            print(json.dumps(status,ensure_ascii=False),flush=True)
    return out,results

def refresh(modes=('rent','sale'),only='all'):
    import fcntl
    from scraper import mode_file,TZ
    from datetime import datetime
    from model import normalize_listing,evaluate_listing,best_rows
    all_results=[]
    for mode in modes:
        with mode_file(mode,'.collection.lock').open('w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            criteria=json.loads(mode_file(mode,'criteria.json').read_text());old=json.loads(mode_file(mode,'listings.json').read_text());previous={r['id']:r for r in old}
            rows,results=collect_brussels(mode,criteria,only);all_results.extend(results)
            updated=[];today=datetime.now(TZ).date().isoformat()
            for row in rows:
                row=normalize_listing(row,mode,today,previous);evaluate_listing(row,criteria,mode,row.get('renovationOverride'));updated.append(row)
            touched={r['source'] for r in results};partial={r['source'] for r in results if not r['ok'] or r['partial']};ids={r['id'] for r in updated}
            keep=[r for r in old if r.get('source') not in touched]
            keep.extend({**r,'stale':True} for r in old if r.get('source') in partial and r['id'] not in ids)
            merged=best_rows(keep+updated,criteria);atomic_json(mode_file(mode,'listings.json'),merged)
            status=json.loads(mode_file(mode,'status.json').read_text());status['sources']=[s for s in status.get('sources',[]) if s.get('source') not in touched]+results
            status['activeSources']=sorted(set(status.get('activeSources',[]))|{r['source'] for r in results if r['ok']})
            status['partial']=any(not r.get('ok') or r.get('partial') for r in status['sources']);status['state']='partial' if status['partial'] else 'complete'
            status.update({'totalCollected':len(merged),'displayedCount':len(merged),'matchingCount':sum(r.get('matchState')=='confirmed' for r in merged),'unknownCount':sum(r.get('matchState')=='unknown' for r in merged)})
            atomic_json(mode_file(mode,'status.json'),status)
    sites=json.loads(REGISTRY.read_text())
    for site in sites:
        outcomes=[r for r in all_results if r['source']==site['name']]
        if not outcomes:continue
        site['results']={**site.get('results',{}),**{r['transaction']:r for r in outcomes}}
        site['enabled']=any(r['ok'] for r in site['results'].values())
        site['adapterStatus']='working' if site['enabled'] else 'unsupported-or-unavailable'
    atomic_json(REGISTRY,sites)
    report={'updatedAt':now(),'auditedDomains':len(sites),'workingAgencies':sum(any(r.get('ok') for r in (s.get('results') or {}).values()) for s in sites),'rentWorking':sum((s.get('results') or {}).get('rent',{}).get('ok',False) for s in sites),'saleWorking':sum((s.get('results') or {}).get('sale',{}).get('ok',False) for s in sites),'sources':[{k:s.get(k) for k in ('name','website','enabled','adapterStatus','auditStatus','auditError','results')} for s in sites]}
    atomic_json(REPORT,report)
    sources_file=ROOT/'sources.json';source_data=json.loads(sources_file.read_text());existing=source_data.get('sources',[])
    for site in sites:
        modes=[m for m,r in site.get('results',{}).items() if r.get('ok')]
        if not modes:continue
        current=next((x for x in existing if x.get('name')==site['name']),None)
        record={'name':site['name'],'status':'integrated','transactions':modes,'coverage':'Bruxelles et communes demandées, filtrées sur le code postal des annonces','verified':'2026-10-07','url':site['website'],'limit':'Catalogue public contrôlé par transaction; pagination et détails plafonnés, erreurs signalées.'}
        if current:current.update(record)
        else:existing.append(record)
    source_data['lastReviewed']='2026-10-07';source_data['sources']=existing;atomic_json(sources_file,source_data)
    return report
