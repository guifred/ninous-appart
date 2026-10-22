"""Import licensed Belgian CBE Open Data and maintain the agency-site registry.

No agency directory is crawled here. The CBE bulk files are a free official source
after the user registers and accepts the reuse licence. Agency websites are not
crawled until the registry records a permission basis and the site's robots rules
allow the exact public listing URL.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse, urljoin
from datetime import datetime
from zoneinfo import ZoneInfo
from zipfile import ZipFile
from io import TextIOWrapper
from html.parser import HTMLParser
from urllib.robotparser import RobotFileParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urldefrag
import csv, json, re, unicodedata
import html, ssl, time

from branding import structured_brand
from model import atomic_json, valid_photos, number_or_none

ROOT=Path(__file__).resolve().parent
AGENCY_DIR=ROOT/'data'/'agencies'
OFFICES_FILE=AGENCY_DIR/'offices.json'
SITES_FILE=AGENCY_DIR/'sites.json'
STATE_FILE=AGENCY_DIR/'discovery-state.json'
MONITOR_FILE=AGENCY_DIR/'monitoring.json'
SOURCES_FILE=AGENCY_DIR/'discovery-sources.json'
TZ=ZoneInfo('Europe/Brussels')
UA='NinousAppartementFinder/0.3 (personal use; public pages only)'
SSL_CONTEXT=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)
CBE_SOURCE='CBE Open Data (user-supplied licensed file)'
REAL_ESTATE_AGENCY_CODES={'68310','6831','6831001'}

EXCLUDED_DIRECTORIES=[
    {'name':'Vendre-Ma-Maison independent-agency directory','url':'https://www.vendre-ma-maison.be/agence-immobiliere/independant/','status':'excluded','lastVerified':'2026-09-30','reason':'Published CGU prohibit automated robots/spiders and copying or storing site information in a database.'},
    {'name':'ERA official broker directory','url':'https://www.era.be/en/our-brokers?page=1','status':'excluded','lastVerified':'2026-09-30','reason':'Published terms prohibit data mining, robots, screen scraping and automated extraction without express prior written permission.'},
    {'name':'We Invest official agency directory','url':'https://weinvest.be/fr-BE/agencies','status':'excluded','lastVerified':'2026-09-30','reason':'Published terms prohibit data explorers, robots and screen scraping without express prior written permission.'},
]

def now():return datetime.now(TZ).isoformat(timespec='seconds')

def norm(value):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',str(value or '').lower()).encode('ascii','ignore').decode()).strip()

def normalized_domain(url):
    p=urlparse(url if '://' in str(url) else 'https://'+str(url))
    host=(p.hostname or '').lower().rstrip('.')
    return host[4:] if host.startswith('www.') else host

def _iter_csv_rows(zf, basename):
    target=next((n for n in zf.namelist() if Path(n).name.lower()==basename.lower()),None)
    if not target:return
    with zf.open(target) as raw:
        text=TextIOWrapper(raw,encoding='utf-8-sig',errors='replace',newline='')
        yield from csv.DictReader(text,delimiter=',')

def _get(row,*keys):
    for key in keys:
        if key in row and row[key] not in (None,'','NULL'):return str(row[key]).strip()
    return ''

def _read_json(path,default):
    try:return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError,ValueError):return default

def update_requested_agency_coverage():
    requested=_read_json(AGENCY_DIR/'requested-agencies.json',{'agencies':[]}).get('agencies',[])
    sites=_read_json(SITES_FILE,[])
    registry=_read_json(ROOT/'sources.json',{}).get('sources',[])
    integrated_names={norm(s.get('name')) for s in registry if s.get('status')=='integrated'}
    identified=[a for a in requested if a.get('domain') or a.get('website')]
    working_domains={s.get('domain') for s in sites if s.get('adapterStatus','').startswith('working-')}
    working_names={norm(n) for s in sites if s.get('domain') in working_domains for n in s.get('userRequestedAgencyNames',[])}
    working_names|={norm(a.get('name')) for a in requested if norm(a.get('name')) in integrated_names}
    monitoring=_read_json(MONITOR_FILE,{})
    monitoring.update({'requestedAgencyNames':len(requested),
                       'requestedAgencyNamesWithWebsite':len(identified),
                       'requestedAgencyUniqueDomains':len({a.get('domain') or normalized_domain(a.get('website')) for a in identified}),
                       'requestedAgencyWorkingSiteScrapers':len(working_names),
                       'requestedAgencyNamesAwaitingWebsite':len(requested)-len(identified),
                       'requestedAgencyLastReconciledAt':now()})
    atomic_json(MONITOR_FILE,monitoring)
    return {k:monitoring[k] for k in ('requestedAgencyNames','requestedAgencyNamesWithWebsite','requestedAgencyUniqueDomains','requestedAgencyWorkingSiteScrapers','requestedAgencyNamesAwaitingWebsite')}

def _fetch(url):
    p=urlparse(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('Only validated public HTTPS URLs are permitted.')
    req=Request(url,headers={'User-Agent':UA,'Accept':'text/html,application/xhtml+xml'})
    with urlopen(req,timeout=15,context=SSL_CONTEXT) as response:
        if response.status!=200:raise RuntimeError(f'HTTP {response.status}')
        raw=response.read(4_000_001)
        if len(raw)>4_000_000:raise RuntimeError('Response exceeds 4 MB limit')
        return raw.decode('utf-8',errors='replace'),response.geturl()

def _robots(url,cache):
    p=urlparse(url);origin=f'{p.scheme}://{p.netloc}'
    if origin not in cache:
        rp=RobotFileParser();robots=origin+'/robots.txt';rp.set_url(robots)
        req=Request(robots,headers={'User-Agent':UA})
        try:
            with urlopen(req,timeout=12,context=SSL_CONTEXT) as res:
                if res.status!=200:return False,'robots-unverifiable'
                rp.parse(res.read(500_001).decode('utf-8',errors='replace').splitlines())
        except HTTPError as e:
            if e.code!=404:return False,f'robots-http-{e.code}'
            rp.parse([])
        except Exception as e:return False,'robots-unavailable: '+str(e)[:100]
        cache[origin]=rp
    return cache[origin].can_fetch(UA,url),('allowed' if cache[origin].can_fetch(UA,url) else 'disallowed')

class _PageLinks(HTMLParser):
    def __init__(self):super().__init__();self.links=[];self.current=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='a' and a.get('href'):self.current={'href':a['href'],'text':[]}
    def handle_data(self,data):
        if self.current is not None:self.current['text'].append(data)
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:self.links.append((self.current['href'],' '.join(' '.join(self.current['text']).split())));self.current=None

def _transaction_paths(page,home,mode):
    p=_PageLinks();p.feed(page);out=[]
    words=(('a-louer','te-huur','for-rent','rentals','rental','location','huren','huurwoningen','rent') if mode=='rent' else ('a-vendre','te-koop','for-sale','sale','vente','koop','kopen','verkopen'))
    for href,label in p.links:
        full=urljoin(home,html.unescape(href));text=(href+' '+label).lower()
        if normalized_domain(full)!=normalized_domain(home):continue
        if any(w in text for w in words) and not any(w in text for w in ('holiday','short-stay','vakantie','studenten','kot','commercial')):out.append(urldefrag(full)[0])
    return list(dict.fromkeys(out))[:3]

def _rental_paths(page,home):
    return _transaction_paths(page,home,'rent')

def _jsonld_listings(page,page_url,mode='rent'):
    rows=[]
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:obj=json.loads(html.unescape(block))
        except (ValueError,TypeError):continue
        todo=obj if isinstance(obj,list) else [obj]
        while todo:
            n=todo.pop()
            if isinstance(n,list):todo.extend(n);continue
            if not isinstance(n,dict):continue
            if isinstance(n.get('@graph'),list):todo.extend(n['@graph'])
            t=n.get('@type',[]);types=t if isinstance(t,list) else [t]
            name=str(n.get('name') or '');desc=str(n.get('description') or '')
            offer=n.get('offers') or {};offer=offer[0] if isinstance(offer,list) and offer else offer
            url=urljoin(page_url,str(n.get('url') or n.get('@id') or page_url))
            category=(name+' '+desc+' '+str(types)+' '+url+' '+page_url).lower()
            if not any(str(x).lower() in ('apartment','residence','realestatelisting') for x in types):continue
            transaction_words=('rent','huur','louer','location') if mode=='rent' else ('sale','sell','koop','verkauf','vente','vendre')
            other_words=('sale','sell','koop','verkauf','vente','vendre') if mode=='rent' else ('rent','huur','louer','location')
            if not any(w in category for w in transaction_words) or any(w in category for w in other_words):continue
            if any(w in category for w in ('holiday','short-stay','vakantie','studenten','kot','commercial')):continue
            if not isinstance(offer,dict):continue
            price=number_or_none(offer.get('price'))
            if price is None:continue
            addr=n.get('address') or {};addr=addr if isinstance(addr,dict) else {}
            size=n.get('floorSize') or {};size=number_or_none(size.get('value') if isinstance(size,dict) else size)
            beds=number_or_none(n.get('numberOfBedrooms'))
            if beds is None:
                match=re.search(r'\b(\d+)\s*(?:bedrooms?|slaapkamers?|chambres?)\b',desc,re.I);beds=number_or_none(match.group(1)) if match else (0 if 'studio' in category else None)
            area_match=re.search(r'\b(\d{1,3}(?:[.,]\d+)?)\s*m(?:²|2)\b',desc,re.I)
            if size is None and area_match:size=number_or_none(area_match.group(1).replace(',','.'))
            city=addr.get('addressLocality') or addr.get('addressRegion')
            if not city:
                loc=re.search(r"(?:te huur|for rent|à louer|a louer)\s+(?:in|à|au|en)?\s*([\wÀ-ÿ’ .-]{2,45}?)(?:,|\.|;|\s+\d)",desc,re.I)
                if loc:city=loc.group(1).strip()
            images=n.get('image') or [];images=[images] if isinstance(images,str) else images
            energy_fields=('energyEfficiencyClass','energyRating','energyClass','epc','peb')
            energy_text=' '.join(f'{key} {n[key]}' for key in energy_fields if n.get(key) not in (None,''))
            rows.append({**structured_brand(n,page_url),'url':url,'transaction':mode,'title':name or ('Appartement à louer' if mode=='rent' else 'Appartement à vendre'),'location':' '.join(x for x in (addr.get('postalCode'),city) if x) or None,'postalCode':addr.get('postalCode'),'streetAddress':addr.get('streetAddress'),'price':price,'fees':None,'area':size,'bedrooms':beds,'summary':desc[:650],'energyRating':n.get('energyEfficiencyClass') or n.get('energyRating') or n.get('energyClass'),'energyText':energy_text,'photos':valid_photos([urljoin(page_url,x.get('url') if isinstance(x,dict) else x) for x in images]),'publicationDate':n.get('datePublished'),'sourceModified':n.get('dateModified')})
    unique={}
    for row in rows:
        key=urldefrag(row['url'])[0].rstrip('/').lower()
        if key not in unique:unique[key]=row
        else:unique[key]['photos']=valid_photos(unique[key].get('photos',[])+row.get('photos',[]))
    return list(unique.values())

def _jsonld_item_urls(page,page_url):
    """Read listing detail URLs from schema.org ItemList pages (Omnicasa etc.)."""
    urls=[]
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:obj=json.loads(html.unescape(block))
        except (ValueError,TypeError):continue
        todo=obj if isinstance(obj,list) else [obj]
        while todo:
            node=todo.pop()
            if isinstance(node,list):todo.extend(node);continue
            if not isinstance(node,dict):continue
            if isinstance(node.get('@graph'),list):todo.extend(node['@graph'])
            kind=node.get('@type',[]);kind=kind if isinstance(kind,list) else [kind]
            if 'ItemList' not in kind:continue
            for entry in node.get('itemListElement',[]) or []:
                if not isinstance(entry,dict):continue
                item=entry.get('item') if isinstance(entry.get('item'),dict) else {}
                candidate=entry.get('url') or entry.get('@id') or item.get('url') or item.get('@id')
                if candidate:
                    url=urldefrag(urljoin(page_url,html.unescape(str(candidate))))[0]
                    if urlparse(url).scheme=='https' and url not in urls:urls.append(url)
    return urls

def authorize_site(domain,evidence_url,basis):
    if basis not in ('published-terms','written-permission'):raise ValueError('basis must be published-terms or written-permission')
    evidence=urlparse(str(evidence_url or ''))
    if evidence.scheme!='https' or not evidence.hostname or evidence.username or evidence.password:raise ValueError('Evidence must be a public HTTPS terms page or permission record URL.')
    if basis=='published-terms' and normalized_domain(evidence_url)!=normalized_domain(domain):raise ValueError('Published-terms evidence must be hosted on the agency website.')
    requested=_read_json(AGENCY_DIR/'requested-agencies.json',{'agencies':[]}).get('agencies',[])
    restricted=[a for a in requested if a.get('domain')==normalized_domain(domain) and a.get('siteTermsStatus')=='restricted']
    if restricted and basis!='written-permission':
        raise PermissionError('This agency site prohibits reuse in its published terms; written permission is required before enabling collection.')
    sites=_read_json(SITES_FILE,[]);match=next((x for x in sites if x.get('domain')==normalized_domain(domain)),None)
    if not match:raise ValueError('Domain is not in the agency-site registry; register it first')
    match.update({'termsStatus':'permitted','accessBasis':basis,'accessEvidenceUrl':evidence_url,'accessReviewedAt':now(),'robotsStatus':'unchecked','rentalSiteStatus':'unknown','saleSiteStatus':'unknown','adapterStatus':'not-enabled'})
    atomic_json(SITES_FILE,sites)
    offices=_read_json(OFFICES_FILE,[])
    for o in offices:
        if o.get('websiteDomain')==match['domain']:o.update({'termsStatus':'permitted','accessBasis':basis,'accessEvidenceUrl':evidence_url,'accessReviewedAt':match['accessReviewedAt']})
    atomic_json(OFFICES_FILE,offices)
    return match

def restrict_site(domain,evidence_url,reason):
    """Record a published extraction restriction and exclude that domain."""
    evidence=urlparse(str(evidence_url or ''))
    if evidence.scheme!='https' or not evidence.hostname or evidence.username or evidence.password:raise ValueError('Restriction evidence must be a public HTTPS terms page.')
    if not str(reason or '').strip():raise ValueError('A concise restriction reason is required.')
    domain=normalized_domain(domain);sites=_read_json(SITES_FILE,[])
    match=next((x for x in sites if x.get('domain')==domain),None)
    if not match:raise ValueError('Domain is not in the agency-site registry; register it first')
    match.update({'termsStatus':'restricted','accessEvidenceUrl':evidence_url,'accessReviewedAt':now(),'status':'manual-only','adapterStatus':'manual-only','adapterStatusByTransaction':{'rent':'manual-only','sale':'manual-only'},'accessNote':str(reason).strip()})
    atomic_json(SITES_FILE,sites)
    requested=_read_json(AGENCY_DIR/'requested-agencies.json',{'agencies':[]})
    for agency in requested.get('agencies',[]):
        if agency.get('domain')==domain:
            agency.update({'siteTermsStatus':'restricted','siteTermsEvidence':evidence_url,'integrationStatus':'manual-only','accessNote':str(reason).strip()})
    atomic_json(AGENCY_DIR/'requested-agencies.json',requested)
    update_requested_agency_coverage()
    return match

def register_requested_site(agency_name, website):
    """Link a user-requested agency to its own site without enabling collection."""
    requested=_read_json(AGENCY_DIR/'requested-agencies.json',{'agencies':[]})
    target=next((x for x in requested.get('agencies',[]) if norm(x.get('name'))==norm(agency_name)),None)
    if not target:raise ValueError('Agency name is not in the user-provided target list')
    parsed=urlparse(str(website or ''))
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Agency website must be a clean public HTTPS URL')
    domain=normalized_domain(website)
    if not domain or '.' not in domain:raise ValueError('Invalid agency website domain')
    target.update({'website':website,'domain':domain,'websiteStatus':'identified','websiteIdentifiedAt':now()})
    atomic_json(AGENCY_DIR/'requested-agencies.json',requested)
    sites=_read_json(SITES_FILE,[])
    site=next((x for x in sites if x.get('domain')==domain),None)
    if not site:
        site={'domain':domain,'website':website,'offices':[],'registeredLocations':[],'legalEntities':[],'brands':[],
              'userRequestedAgencyNames':[],'cities':[],'discoverySource':'User-provided agency list',
              'status':'manual-review','rentalSiteStatus':'unknown','saleSiteStatus':'unknown',
              'transactions':['rent','sale'],'termsStatus':'unchecked','robotsStatus':'unchecked',
              'adapterStatus':'not-enabled','adapterStatusByTransaction':{'rent':'not-enabled','sale':'not-enabled'}}
        sites.append(site)
    site['website']=site.get('website') or website
    site.setdefault('brands',[])
    site.setdefault('userRequestedAgencyNames',[])
    for field in ('brands','userRequestedAgencyNames'):
        if agency_name not in site[field]:site[field].append(agency_name)
    if target.get('siteTermsStatus')=='restricted':
        site.update({'termsStatus':'restricted','status':'manual-only','adapterStatus':'manual-only','accessNote':target.get('accessNote','Published terms restrict automated reuse.')})
    # Shared franchise platforms/domains remain one website integration.
    atomic_json(SITES_FILE,sorted(sites,key=lambda x:x.get('domain','')))
    coverage=update_requested_agency_coverage()
    return {'agency':target,'site':site,'coverage':coverage}

def check_agency_site(site):
    if site.get('termsStatus')!='permitted':raise PermissionError('Terms/permission have not been reviewed and recorded for this domain.')
    home=site.get('website')
    if not home or urlparse(home).scheme!='https':raise ValueError('Agency URL must be HTTPS.')
    cache={};allowed,rule=_robots(home,cache)
    if not allowed:raise PermissionError('Homepage robots check: '+rule)
    page,final=_fetch(home);time.sleep(1)
    if normalized_domain(final)!=normalized_domain(home):raise PermissionError('Homepage redirected to a different domain; review it separately.')
    transaction_results={};rows=[];errors=[];detail_pages_checked=0
    for mode in ('rent','sale'):
        paths=_transaction_paths(page,final,mode);checked=[];mode_rows=[];detail_checked=[];detail_candidates=[];partial=False
        for url in paths:
            ok,rule=_robots(url,cache)
            if not ok:errors.append({'url':url,'transaction':mode,'error':'robots '+rule});continue
            try:
                body,detail_final=_fetch(url)
                if normalized_domain(detail_final)!=normalized_domain(home):raise PermissionError('Listing page redirected to a different domain; review it separately.')
                checked.append(url);mode_rows.extend(_jsonld_listings(body,url,mode))
                # Many agency sites publish structured ItemList URLs but place
                # the actual price, photos and energy data on detail pages.
                # Read a bounded first page of detail URLs, with robots checks
                # and the same-site restriction applied to every request.
                detail_candidates.extend(_jsonld_item_urls(body,url))
                time.sleep(1)
            except Exception as e:errors.append({'url':url,'transaction':mode,'error':str(e)[:200]})
        detail_candidates=list(dict.fromkeys(u for u in detail_candidates if normalized_domain(u)==normalized_domain(home) and u not in checked))
        if len(detail_candidates)>20:partial=True
        for detail_url in detail_candidates[:20]:
            ok,rule=_robots(detail_url,cache)
            if not ok:
                errors.append({'url':detail_url,'transaction':mode,'error':'robots '+rule});continue
            try:
                detail_body,detail_final=_fetch(detail_url)
                if normalized_domain(detail_final)!=normalized_domain(home):raise PermissionError('Detail page redirected to a different domain; review it separately.')
                detail_checked.append(detail_url);mode_rows.extend(_jsonld_listings(detail_body,detail_final,mode));detail_pages_checked+=1
            except Exception as e:errors.append({'url':detail_url,'transaction':mode,'error':str(e)[:200]})
            time.sleep(1)
        transaction_results[mode]={'urls':paths,'checkedUrls':checked,'checkedDetailUrls':detail_checked,'detailCandidates':len(detail_candidates),'partial':partial,'status':'publishes-rental-pages' if mode=='rent' and checked else 'publishes-sale-pages' if mode=='sale' and checked else ('unknown' if paths else 'no-rental-page-found' if mode=='rent' else 'no-sale-page-found'),'adapterStatus':'working-jsonld' if mode_rows else ('parse-unsupported' if checked else 'no-page-checked'),'parsedListingCount':len(mode_rows)}
        rows.extend(mode_rows)
    dedup={}
    for row in rows:
        key=urldefrag(row['url'])[0].rstrip('/').lower()
        if key not in dedup:dedup[key]=row
        else:dedup[key]['photos']=valid_photos(dedup[key].get('photos',[])+row.get('photos',[]))
    result={'websiteStatus':'checked','website':final,'robotsStatus':'allowed','rentalSiteStatus':transaction_results['rent']['status'],'saleSiteStatus':transaction_results['sale']['status'],'rentalUrls':transaction_results['rent']['urls'],'saleUrls':transaction_results['sale']['urls'],'checkedRentalUrls':transaction_results['rent']['checkedUrls'],'checkedSaleUrls':transaction_results['sale']['checkedUrls'],'checkedRentalDetailUrls':transaction_results['rent']['checkedDetailUrls'],'checkedSaleDetailUrls':transaction_results['sale']['checkedDetailUrls'],'agencyDetailPagesChecked':detail_pages_checked,'adapterStatus':'working-jsonld' if dedup else ('parse-unsupported' if any(x['checkedUrls'] for x in (transaction_results['rent'],transaction_results['sale'])) else 'no-page-checked'),'adapterStatusByTransaction':{m:x['adapterStatus'] for m,x in transaction_results.items()},'parseFailuresByTransaction':{m:(x['adapterStatus']=='parse-unsupported') for m,x in transaction_results.items()},'parsedListings':list(dedup.values()),'parsedListingCount':len(dedup),'partialByTransaction':{m:x['partial'] for m,x in transaction_results.items()},'errors':errors,'lastChecked':now()}
    return result

def verify_sites(limit=100):
    sites=_read_json(SITES_FILE,[])
    # Revisit permitted domains in bounded batches so temporary source failures
    # recover automatically and every enabled agency is eventually rechecked.
    eligible=[s for s in sites if s.get('termsStatus')=='permitted' and s.get('robotsStatus') in ('allowed','unchecked',None,'temporary-error')]
    pending=eligible[:max(0,min(int(limit),500))]
    checked=0;failed=0
    for site in pending:
        try:site.update(check_agency_site(site))
        except Exception as e:
            message=str(e)[:300]
            site.update({'websiteStatus':'failed','lastChecked':now(),'checkError':message});failed+=1
            if 'disallowed' in message.lower():site['robotsStatus']='disallowed'
            elif 'robots' in message.lower():site['robotsStatus']='unverifiable'
            else:site['robotsStatus']='temporary-error'
        checked+=1;time.sleep(1)
    atomic_json(SITES_FILE,sites)
    monitoring=_read_json(MONITOR_FILE,{})
    access_failed=lambda x:x.get('websiteStatus')=='failed' or bool(x.get('errors'))
    monitoring.update({'updatedAt':now(),'sitesChecked':sum(1 for x in sites if x.get('lastChecked')),'sitesCheckedThisRun':checked,'failedSitesThisRun':failed,'sitesWithRentalPages':sum(1 for x in sites if x.get('rentalSiteStatus')=='publishes-rental-pages'),'sitesWithSaleListings':sum(1 for x in sites if x.get('saleSiteStatus')=='publishes-sale-pages'),'workingScrapers':sum(1 for x in sites if x.get('adapterStatus','').startswith('working-')),'rentalWorkingScrapers':sum(1 for x in sites if x.get('adapterStatusByTransaction',{}).get('rent','').startswith('working-')),'saleWorkingScrapers':sum(1 for x in sites if x.get('adapterStatusByTransaction',{}).get('sale','').startswith('working-')),'parseFailures':sum(1 for x in sites if any((x.get('parseFailuresByTransaction') or {}).values()) or x.get('adapterStatus')=='parse-unsupported'),'rentalParseFailures':sum(1 for x in sites if (x.get('parseFailuresByTransaction') or {}).get('rent')),'saleParseFailures':sum(1 for x in sites if (x.get('parseFailuresByTransaction') or {}).get('sale')),'failedSites':sum(1 for x in sites if access_failed(x)),'accessFailures':sum(1 for x in sites if access_failed(x)),'profilesPending':sum(1 for x in sites if x.get('termsStatus')!='permitted' or x.get('robotsStatus')!='allowed')})
    monitoring.setdefault('source',CBE_SOURCE)
    monitoring.setdefault('coverageNote','No licensed CBE archive has been imported; agency-owned website coverage is currently zero.')
    monitoring.setdefault('officesDiscovered',0);monitoring.setdefault('legalEntitiesDiscovered',0);monitoring.setdefault('brandsDiscovered',0);monitoring.setdefault('uniqueDomains',0)
    atomic_json(MONITOR_FILE,monitoring)
    update_requested_agency_coverage()
    return monitoring

def collect_agency_listings(criteria,previous_by_id=None,limit=100,mode='rent'):
    if mode not in ('rent','sale'):raise ValueError('mode must be rent or sale')
    previous_by_id=previous_by_id or {};sites=_read_json(SITES_FILE,[])
    published='publishes-rental-pages' if mode=='rent' else 'publishes-sale-pages'
    candidates=[s for s in sites if mode in s.get('transactions',['rent']) and s.get('termsStatus')=='permitted' and s.get('robotsStatus')=='allowed' and s.get('rentalSiteStatus' if mode=='rent' else 'saleSiteStatus')==published]
    known=[s for s in candidates if s.get('adapterStatus','').startswith('working-')]
    other=[s for s in candidates if s not in known]
    state=_read_json(STATE_FILE,{});offset=int(state.get('collectOffset',0))%max(len(other),1)
    # Working adapters are not privileged over other verified domains; sweep
    # every eligible site within the configured cap. This makes coverage
    # predictable as the requested-agency registry grows.
    batch=(known+other)[:max(0,min(int(limit),500))]
    rows=[];failed=[];checked=0
    for site in batch:
        try:
            result=check_agency_site(site);site.update({k:v for k,v in result.items() if k!='parsedListings'});checked+=1
            for row in result.get('parsedListings',[]):
                if row.get('transaction')!=mode:continue
                agency_name=(site.get('brands') or site.get('legalEntities') or ['Agency website'])[0]
                row.update({'source':agency_name,'agencyName':agency_name,'agencyWebsite':site.get('website'),'agencyDomain':site['domain'],'sourceType':'agency-site','id':'agency-'+mode+'-'+re.sub(r'[^a-z0-9]+','-',site['domain']+'-'+row.get('url','')).strip('-')[:170]})
                rows.append(row)
        except Exception as e:
            failed.append(site['domain']);site.update({'websiteStatus':'failed','lastChecked':now(),'checkError':str(e)[:300]})
            if 'disallowed' in str(e).lower():site['robotsStatus']='disallowed'
            elif 'robots' in str(e).lower():site['robotsStatus']='unverifiable'
        time.sleep(0.8)
    state.update({'collectOffset':0,'lastAgencyCollectionAt':now()});atomic_json(STATE_FILE,state);atomic_json(SITES_FILE,sites)
    access_failed=lambda x:x.get('websiteStatus')=='failed' or bool(x.get('errors'))
    monitor=_read_json(MONITOR_FILE,{})
    new_count=sum(1 for r in rows if r['id'] not in previous_by_id)
    new_by_mode=monitor.get('newListingsByMode',{});new_by_mode[mode]=new_count
    monitor.update({'updatedAt':now(),'newListingsThisCollection':new_count,'newListingsByMode':new_by_mode,'sitesCheckedThisCollection':checked,'failedSitesThisCollection':len(failed),'sitesChecked':sum(1 for x in sites if x.get('lastChecked')),'sitesWithRentalPages':sum(1 for x in sites if x.get('rentalSiteStatus')=='publishes-rental-pages'),'sitesWithSaleListings':sum(1 for x in sites if x.get('saleSiteStatus')=='publishes-sale-pages'),'workingScrapers':sum(1 for x in sites if x.get('adapterStatus','').startswith('working-')),'rentalWorkingScrapers':sum(1 for x in sites if x.get('adapterStatusByTransaction',{}).get('rent','').startswith('working-')),'saleWorkingScrapers':sum(1 for x in sites if x.get('adapterStatusByTransaction',{}).get('sale','').startswith('working-')),'failedSites':sum(1 for x in sites if access_failed(x)),'accessFailures':sum(1 for x in sites if access_failed(x)),'parseFailures':sum(1 for x in sites if any((x.get('parseFailuresByTransaction') or {}).values()) or x.get('adapterStatus')=='parse-unsupported'),'rentalParseFailures':sum(1 for x in sites if (x.get('parseFailuresByTransaction') or {}).get('rent')),'saleParseFailures':sum(1 for x in sites if (x.get('parseFailuresByTransaction') or {}).get('sale'))})
    monitor.setdefault('source',CBE_SOURCE);monitor.setdefault('coverageNote','No licensed CBE archive has been imported; agency-owned website coverage is currently zero.');monitor.setdefault('officesDiscovered',0);monitor.setdefault('legalEntitiesDiscovered',0);monitor.setdefault('brandsDiscovered',0);monitor.setdefault('uniqueDomains',0);atomic_json(MONITOR_FILE,monitor);update_requested_agency_coverage()
    partial=checked<len(candidates) or any((s.get('partialByTransaction') or {}).get(mode) for s in batch)
    detail_count=sum(int(s.get('agencyDetailPagesChecked') or 0) for s in batch)
    return rows,{'source':'Agency-owned sites (JSON-LD)','ok':True,'found':len(rows),'checkedSites':checked,'checkedDetailPages':detail_count,'failedSites':len(failed),'failedSources':failed,'partial':partial,'transaction':mode,'note':f'{checked}/{len(candidates)} authorized, verified sites; JSON-LD listing pages plus bounded detail pages (up to 20 per catalogue).'}

def _website_contacts(rows):
    out={}
    for r in rows:
        value=_get(r,'Value','value')
        if value.startswith(('http://','https://','www.')):
            key=_get(r,'EntityNumber','entitynumber')
            if key:out.setdefault(key,[]).append(value if '://' in value else 'https://'+value)
    return out

def import_cbe_open_data(archive_path):
    """Read the official full CBE Open Data ZIP. The archive must be obtained under its reuse licence."""
    archive=Path(archive_path)
    if not archive.is_file() or archive.suffix.lower()!='.zip':raise ValueError('Provide the registered CBE Open Data full ZIP archive.')
    with ZipFile(archive) as zf:
        names={Path(n).name.lower() for n in zf.namelist()}
        required={'enterprise.csv','establishment.csv','activity.csv','address.csv','denomination.csv','contact.csv'}
        if not required.issubset(names):raise ValueError('CBE ZIP is missing one or more required CSV tables: '+', '.join(sorted(required-names)))
        activity_entities=set()
        for r in _iter_csv_rows(zf,'activity.csv'):
            code=re.sub(r'\D','',_get(r,'NaceCode','nacecode'))
            if code.startswith('6831'):
                entity=_get(r,'EntityNumber','entitynumber')
                if entity:activity_entities.add(entity)
        establishment_to_enterprise={}
        for r in _iter_csv_rows(zf,'establishment.csv'):
            est=_get(r,'EstablishmentNumber','establishmentnumber')
            if est in activity_entities:establishment_to_enterprise[est]=_get(r,'EnterpriseNumber','enterprisenumber')
        possible_enterprises=activity_entities|set(establishment_to_enterprise.values())
        active_enterprises=set()
        for r in _iter_csv_rows(zf,'enterprise.csv'):
            entity=_get(r,'EnterpriseNumber','enterprisenumber')
            if entity in possible_enterprises and _get(r,'Status','status') in ('AC',''):
                active_enterprises.add(entity)
        relevant=(activity_entities&active_enterprises)|{parent for parent in establishment_to_enterprise.values() if parent in active_enterprises}
    if not relevant:raise ValueError('No active NACE 68.31 real-estate brokerage entities found in this archive.')
    with ZipFile(archive) as zf:
        establishments=[]
        for r in _iter_csv_rows(zf,'establishment.csv'):
            if _get(r,'EnterpriseNumber','enterprisenumber') in relevant:establishments.append(r)
        wanted=set(relevant)
        wanted.update(_get(r,'EstablishmentNumber','establishmentnumber') for r in establishments)
        addresses=[];denominations=[];contacts=[];meta=[]
        for r in _iter_csv_rows(zf,'address.csv'):
            if _get(r,'EntityNumber','entitynumber') in wanted:addresses.append(r)
        for r in _iter_csv_rows(zf,'denomination.csv'):
            if _get(r,'EntityNumber','entitynumber') in wanted:denominations.append(r)
        for r in _iter_csv_rows(zf,'contact.csv'):
            if _get(r,'EntityNumber','entitynumber') in wanted:contacts.append(r)
        meta=list(_iter_csv_rows(zf,'meta.csv') or [])
    names_by_id={}
    for r in denominations:
        entity=_get(r,'EntityNumber','entitynumber');name=_get(r,'Denomination','denomination')
        if entity and name:names_by_id.setdefault(entity,[]).append(name)
    address_by_id={}
    for r in addresses:
        entity=_get(r,'EntityNumber','entitynumber')
        if entity:address_by_id.setdefault(entity,r)
    contacts_by_id=_website_contacts(contacts)
    offices=[]
    for r in establishments:
        est=_get(r,'EstablishmentNumber','establishmentnumber');enterprise_no=_get(r,'EnterpriseNumber','enterprisenumber')
        if enterprise_no not in relevant:continue
        address=address_by_id.get(est,{})
        branch_name=next(iter(names_by_id.get(est,[])),None) or next(iter(names_by_id.get(enterprise_no,[])),enterprise_no)
        website=next(iter(contacts_by_id.get(est,[])),None) or next(iter(contacts_by_id.get(enterprise_no,[])),None)
        postal=_get(address,'Zipcode','zipcode');city=_get(address,'MunicipalityFR','MunicipalityNL','municipalityfr','municipalitynl')
        profile=f'cbe://establishment/{est}'
        offices.append({'officeId':'cbe-'+est,'recordType':'establishment','agencyName':branch_name,'legalEntityName':next(iter(names_by_id.get(enterprise_no,[])),branch_name),'legalEntityId':'cbe-enterprise-'+enterprise_no,'enterpriseNumber':enterprise_no,'establishmentNumber':est,'website':website,'websiteDomain':normalized_domain(website) if website else None,'discoverySource':CBE_SOURCE,'discoverySourceUrl':'https://kbopub.economie.fgov.be/kbo-open-data/','city':city or None,'postalCode':postal or None,'streetAddress':' '.join(x for x in (_get(address,'StreetFR','StreetNL','streetfr','streetnl'),_get(address,'HouseNumber','housenumber')) if x) or None,'region':_region(postal),'rentalSiteStatus':'unknown','websiteStatus':'discovered' if website else 'no-website-in-CBE','termsStatus':'unchecked','robotsStatus':'unchecked','profileUrl':profile,'discoveredAt':now()})
    # Some licensed records list an active agency entity without an establishment unit.
    represented={x['enterpriseNumber'] for x in offices}
    for enterprise_no in sorted(relevant-represented):
        address=address_by_id.get(enterprise_no,{})
        name=next(iter(names_by_id.get(enterprise_no,[])),enterprise_no)
        website=next(iter(contacts_by_id.get(enterprise_no,[])),None);postal=_get(address,'Zipcode','zipcode')
        offices.append({'officeId':'cbe-enterprise-'+enterprise_no,'recordType':'enterprise-address','agencyName':name,'legalEntityName':name,'legalEntityId':'cbe-enterprise-'+enterprise_no,'enterpriseNumber':enterprise_no,'establishmentNumber':None,'website':website,'websiteDomain':normalized_domain(website) if website else None,'discoverySource':CBE_SOURCE,'discoverySourceUrl':'https://kbopub.economie.fgov.be/kbo-open-data/','city':_get(address,'MunicipalityFR','MunicipalityNL') or None,'postalCode':postal or None,'streetAddress':' '.join(x for x in (_get(address,'StreetFR','StreetNL'),_get(address,'HouseNumber')) if x) or None,'region':_region(postal),'rentalSiteStatus':'unknown','websiteStatus':'discovered' if website else 'no-website-in-CBE','termsStatus':'unchecked','robotsStatus':'unchecked','profileUrl':f'cbe://enterprise/{enterprise_no}','discoveredAt':now()})
    offices.sort(key=lambda x:(x.get('legalEntityName','').lower(),x.get('city') or ''))
    sites={}
    for o in offices:
        domain=o.get('websiteDomain')
        if not domain:continue
        item=sites.setdefault(domain,{'domain':domain,'website':o.get('website'),'offices':[],'registeredLocations':[],'legalEntities':[],'cities':[],'status':'manual-review','rentalSiteStatus':'unknown','saleSiteStatus':'unknown','termsStatus':'unchecked','robotsStatus':'unchecked','adapterStatus':'not-enabled','transactions':['rent','sale']})
        item['registeredLocations'].append(o['officeId'])
        if o.get('establishmentNumber'):item['offices'].append(o['officeId'])
        item['legalEntities'].append(o['legalEntityName']);
        if o.get('city'):item['cities'].append(o['city'])
    for s in sites.values():
        s['officeCount']=len(set(s['offices']));s['registeredLocationCount']=len(set(s['registeredLocations']));s['legalEntities']=sorted(set(s['legalEntities']));s['cities']=sorted(set(s['cities']))
    # Keep individually registered user-requested sites across future CBE imports.
    for old in _read_json(SITES_FILE,[]):
        if not old.get('userRequestedAgencyNames'):continue
        current=sites.get(old.get('domain'))
        if current is None:
            sites[old['domain']]=old
            continue
        for field in ('userRequestedAgencyNames','brands','offices','registeredLocations','legalEntities','cities'):
            current[field]=list(dict.fromkeys((current.get(field) or [])+(old.get(field) or [])))
        for field in ('termsStatus','accessBasis','accessEvidenceUrl','accessReviewedAt','robotsStatus','adapterStatus','adapterStatusByTransaction','rentalSiteStatus','saleSiteStatus'):
            if old.get(field) not in (None,'unchecked','not-enabled','unknown'):current[field]=old[field]
    site_rows=sorted(sites.values(),key=lambda x:x['domain'])
    version=next((_get(r,'Value','value') for r in meta if _get(r,'Name','name') in ('SnapshotDate','ExtractTimestamp','Version')),None)
    atomic_json(AGENCY_DIR/'offices.json',offices);atomic_json(AGENCY_DIR/'sites.json',site_rows)
    sources={'updatedAt':now(),'sources':[{'name':CBE_SOURCE,'url':'https://economie.fgov.be/en/themes/enterprises/crossroads-bank-enterprises/services-everyone/public-data-reuse','status':'licensed-file-required','terms':'Free open-data files; prior registration and acceptance of CBE Open Data licence required. Public Search web service is paid and is not used.','access':'offline ZIP import; no public-search scraping'},*EXCLUDED_DIRECTORIES]}
    atomic_json(SOURCES_FILE,sources)
    office_region_counts={};location_region_counts={}
    for o in offices:
        region=o.get('region') or 'Belgium (region unknown)'
        location_region_counts[region]=location_region_counts.get(region,0)+1
        if o.get('establishmentNumber'):office_region_counts[region]=office_region_counts.get(region,0)+1
    monitoring={'updatedAt':now(),'source':CBE_SOURCE,'archiveName':archive.name,'snapshot':version,'officesDiscovered':sum(1 for o in offices if o.get('establishmentNumber')),'registeredLocationRecords':len(offices),'legalEntitiesDiscovered':len(set(o['enterpriseNumber'] for o in offices)),'brandsDiscovered':0,'brandsNote':'CBE does not reliably link trading brands to legal entities; brands require a separately permitted source.','uniqueDomains':len(site_rows),'sitesChecked':0,'sitesWithRentalPages':0,'workingScrapers':0,'failedSites':0,'parseFailures':0,'profilesPending':len(site_rows),'newListingsFoundThisRun':0,'officesByRegion':office_region_counts,'registeredLocationsByRegion':location_region_counts,'coverageNote':'Licensed official CBE data identifies active agency legal entities, registered establishments and supplied contact websites. A website, brand or rental catalogue is not inferred where the register does not provide reliable evidence.'}
    atomic_json(MONITOR_FILE,monitoring)
    update_requested_agency_coverage()
    atomic_json(STATE_FILE,{'lastCbeImportAt':now(),'archiveName':archive.name,'snapshot':version})
    return monitoring

def _region(postal):
    try:code=int(postal)
    except (ValueError,TypeError):return None
    if 1000<=code<=1299:return 'Bruxelles-Capitale'
    if 1300<=code<=1499 or 4000<=code<=7999:return 'Wallonie'
    if 1500<=code<=3999 or 8000<=code<=9999:return 'Flandre'
    return None

if __name__=='__main__':
    import sys
    if len(sys.argv)>1 and sys.argv[1]=='refresh-brussels':
        from brussels_agencies import refresh
        refresh(sys.argv[2:] or ['rent','sale']);raise SystemExit(0)
    if len(sys.argv)>1 and sys.argv[1]=='audit-brussels':
        from brussels_agencies import audit
        audit();raise SystemExit(0)
    import argparse
    ap=argparse.ArgumentParser(description='Maintain a permission-aware Belgian agency website registry.')
    ap.add_argument('command',choices=('import-cbe','coverage','authorize','register-requested','restrict-site','verify-sites'))
    ap.add_argument('archive',nargs='?',help='Path to the official CBE Open Data full ZIP.')
    ap.add_argument('--domain',help='Domain already present in the agency-site registry')
    ap.add_argument('--evidence-url',help='Terms page or permission evidence URL')
    ap.add_argument('--basis',choices=('published-terms','written-permission'))
    ap.add_argument('--agency-name',help='Exact agency name from data/agencies/requested-agencies.json')
    ap.add_argument('--website',help='Official public HTTPS website for that agency')
    ap.add_argument('--reason',help='Published restriction reason recorded against a domain')
    ap.add_argument('--limit',type=int,default=40)
    args=ap.parse_args()
    if args.command=='import-cbe':
        if not args.archive:ap.error('import-cbe requires the registered CBE Open Data ZIP path')
        print(json.dumps(import_cbe_open_data(args.archive),ensure_ascii=False,indent=2))
    elif args.command=='coverage':
        try:print(json.dumps(json.loads(MONITOR_FILE.read_text()),ensure_ascii=False,indent=2))
        except (OSError,ValueError):print(json.dumps({'officesDiscovered':0,'registeredLocationRecords':0,'legalEntitiesDiscovered':0,'brandsDiscovered':0,'uniqueDomains':0,'sitesChecked':0,'sitesWithRentalPages':0,'workingScrapers':0,'failedSites':0,'parseFailures':0,'profilesPending':0,'newListingsFoundThisRun':0,'coverageState':'licensed CBE file not imported','coverageNote':'No licensed CBE archive has been imported; agency-owned website coverage is currently zero.'},ensure_ascii=False,indent=2))
    elif args.command=='authorize':
        if not args.domain or not args.evidence_url or not args.basis:ap.error('authorize requires --domain, --evidence-url and --basis after you review site terms or obtain written permission')
        print(json.dumps(authorize_site(args.domain,args.evidence_url,args.basis),ensure_ascii=False,indent=2))
    elif args.command=='register-requested':
        if not args.agency_name or not args.website:ap.error('register-requested requires --agency-name and --website')
        print(json.dumps(register_requested_site(args.agency_name,args.website),ensure_ascii=False,indent=2))
    elif args.command=='restrict-site':
        if not args.domain or not args.evidence_url or not args.reason:ap.error('restrict-site requires --domain, --evidence-url and --reason')
        print(json.dumps(restrict_site(args.domain,args.evidence_url,args.reason),ensure_ascii=False,indent=2))
    else:print(json.dumps(verify_sites(args.limit),ensure_ascii=False,indent=2))
