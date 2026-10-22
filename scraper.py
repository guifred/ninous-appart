"""Low-rate Belgian rental collectors. Honor robots.txt; no proxy or browser bypass."""
from html.parser import HTMLParser
from functools import lru_cache
from branding import logo_attributes, structured_brand, with_branding
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import html, json, re, time, ssl, unicodedata, subprocess, fcntl
from model import MODES, DEFAULT_RENT, DEFAULT_SALE, atomic_json, normalize_listing, evaluate_listing, best_rows, valid_photos, number_or_none
from agency_discovery import collect_agency_listings, normalized_domain, _read_json as read_agency_json, MONITOR_FILE, SITES_FILE
from biddit import collect_biddit
from sorimo import collect_sorimo, refresh_modes
from brussels_agencies import collect_brussels

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
HOST = 'https://immovlan.be'
REGIE_HOST = 'https://regiefonciere.bruxelles.be'
REGIE_LISTINGS = REGIE_HOST + '/fr/je-cherche-un-bien-immobilier/'
EASY_HOST = 'https://easyproperties.be'
EASY_LISTINGS = EASY_HOST + '/fr/a-louer/'
EASY_SALE_LISTINGS = EASY_HOST + '/fr/a-vendre/'
RED_HOST = 'https://www.redimmobilier.be'
RED_LISTINGS = RED_HOST + '/fr/a-louer'
RED_SALE_LISTINGS = RED_HOST + '/fr/a-vendre'
UA = 'NinousAppartementFinder/0.1 (personal, contact: local app)'
TZ = ZoneInfo('Europe/Brussels')

class CollectionBusyError(RuntimeError):
    """Another process owns the same transaction mode’s collection lock."""
SSL_CONTEXT = ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)
AREAS = {
    'woluwe-saint-lambert': ('1200-sint-lambrechts-woluwe', 'Woluwe-Saint-Lambert'),
    'woluwe saint lambert': ('1200-sint-lambrechts-woluwe', 'Woluwe-Saint-Lambert'),
    'woluwe-saint-pierre': ('1150-sint-pieters-woluwe', 'Woluwe-Saint-Pierre'),
    'woluwe saint pierre': ('1150-sint-pieters-woluwe', 'Woluwe-Saint-Pierre'),
    'schaerbeek': ('1030-schaarbeek', 'Schaerbeek'),
    'etterbeek': ('1040-etterbeek', 'Etterbeek'),
    'evere': ('1140-evere', 'Evere'),
    'bruxelles-ville': ('1000-brussels', 'Bruxelles-Ville'),
    'bruxelles ville': ('1000-brussels', 'Bruxelles-Ville'),
    'brussels city': ('1000-brussels', 'Brussels City'),
    'brussels': ('1000-brussels', 'Brussels City'),
    'bruxelles': ('1000-bruxelles', 'Brussels City'),
    '1000': ('1000-brussels', 'Bruxelles-Ville'),
    '1020': ('1020-laken', 'Laeken'),
    '1030': ('1030-schaarbeek', 'Schaerbeek'),
    '1040': ('1040-etterbeek', 'Etterbeek'),
    '1050': ('1050-elsene', 'Ixelles'),
    '1060': ('1060-sint-gillis', 'Saint-Gilles'),
    '1070': ('1070-anderlecht', 'Anderlecht'),
    '1080': ('1080-sint-jans-molenbeek', 'Molenbeek-Saint-Jean'),
    '1090': ('1090-jette', 'Jette'),
    '1120': ('1120-neder-over-heembeek', 'Neder-Over-Heembeek'),
    '1130': ('1130-haren', 'Haren'),
    '1140': ('1140-evere', 'Evere'),
    '1150': ('1150-sint-pieters-woluwe', 'Woluwe-Saint-Pierre'),
    '1160': ('1160-oudergem', 'Auderghem'),
    '1170': ('1170-watermaal-bosvoorde', 'Watermael-Boitsfort'),
    '1180': ('1180-ukkel', 'Uccle'),
    '1190': ('1190-vorst', 'Forest'),
    '1200': ('1200-sint-lambrechts-woluwe', 'Woluwe-Saint-Lambert'),
    '1210': ('1210-sint-joost-ten-node', 'Saint-Josse-ten-Noode'),
    'antwerp': ('2000-antwerpen','Antwerpen'), 'antwerpen': ('2000-antwerpen','Antwerpen'), '2000': ('2000-antwerpen','Antwerpen'),
    'gent': ('9000-gent','Gent'), 'ghent': ('9000-gent','Gent'), '9000': ('9000-gent','Gent'),
    'leuven': ('3000-leuven','Leuven'), '3000': ('3000-leuven','Leuven'),
    'brugge': ('8000-brugge','Brugge'), 'bruges': ('8000-brugge','Brugge'), '8000': ('8000-brugge','Brugge'),
    'hasselt': ('3500-hasselt','Hasselt'), '3500': ('3500-hasselt','Hasselt'),
    'mechelen': ('2800-mechelen','Mechelen'), 'malines': ('2800-mechelen','Mechelen'), '2800': ('2800-mechelen','Mechelen'),
    'aalst': ('9300-aalst','Aalst'), '9300': ('9300-aalst','Aalst'),
    'kortrijk': ('8500-kortrijk','Kortrijk'), '8500': ('8500-kortrijk','Kortrijk'),
    'oostende': ('8400-oostende','Oostende'), 'ostend': ('8400-oostende','Oostende'), '8400': ('8400-oostende','Oostende'),
    'genk': ('3600-genk','Genk'), '3600': ('3600-genk','Genk'),
    'sint-niklaas': ('9100-sint-niklaas','Sint-Niklaas'), '9100': ('9100-sint-niklaas','Sint-Niklaas'),
    'turnhout': ('2300-turnhout','Turnhout'), '2300': ('2300-turnhout','Turnhout'),
    'roeselare': ('8800-roeselare','Roeselare'), '8800': ('8800-roeselare','Roeselare'),
    'mons': ('7000-mons','Mons'), '7000': ('7000-mons','Mons'),
    'namur': ('5000-namur','Namur'), 'namen': ('5000-namur','Namur'), '5000': ('5000-namur','Namur'),
    'liege': ('4000-liege','Liège'), '4000': ('4000-liege','Liège'),
    'charleroi': ('6000-charleroi','Charleroi'), '6000': ('6000-charleroi','Charleroi'),
    'tournai': ('7500-tournai','Tournai'), '7500': ('7500-tournai','Tournai'),
    'verviers': ('4800-verviers','Verviers'), '4800': ('4800-verviers','Verviers'),
    'arlon': ('6700-arlon','Arlon'), '6700': ('6700-arlon','Arlon'),
    'wavre': ('1300-wavre','Wavre'), '1300': ('1300-wavre','Wavre'),
    'la louviere': ('7100-la-louviere','La Louvière'), '7100': ('7100-la-louviere','La Louvière'),
    'nivelles': ('1400-nivelles','Nivelles'), '1400': ('1400-nivelles','Nivelles'),
}
AREAS.update({
    'anderlecht': ('1070-anderlecht','Anderlecht'),
    'auderghem': ('1160-oudergem','Auderghem'),
    'berchem-sainte-agathe': ('1082-sint-agatha-berchem','Berchem-Sainte-Agathe'),
    'berchem sainte agathe': ('1082-sint-agatha-berchem','Berchem-Sainte-Agathe'),
    'forest': ('1190-vorst','Forest'),
    'ganshoren': ('1083-ganshoren','Ganshoren'),
    'ixelles': ('1050-elsene','Ixelles'),
    'jette': ('1090-jette','Jette'),
    'koekelberg': ('1081-koekelberg','Koekelberg'),
    'molenbeek-saint-jean': ('1080-sint-jans-molenbeek','Molenbeek-Saint-Jean'),
    'molenbeek saint jean': ('1080-sint-jans-molenbeek','Molenbeek-Saint-Jean'),
    'saint-gilles': ('1060-sint-gillis','Saint-Gilles'),
    'saint gilles': ('1060-sint-gillis','Saint-Gilles'),
    'saint-josse-ten-noode': ('1210-sint-joost-ten-node','Saint-Josse-ten-Noode'),
    'saint josse ten noode': ('1210-sint-joost-ten-node','Saint-Josse-ten-Noode'),
    'uccle': ('1180-ukkel','Uccle'),
    'watermael-boitsfort': ('1170-watermaal-bosvoorde','Watermael-Boitsfort'),
    'watermael boitsfort': ('1170-watermaal-bosvoorde','Watermael-Boitsfort'),
})
NEARBY_AREAS={
    'woluwe saint lambert':('Woluwe-Saint-Pierre','Evere','Schaerbeek','Etterbeek'),
    'woluwe saint pierre':('Woluwe-Saint-Lambert','Etterbeek','Auderghem','Ixelles','Watermael-Boitsfort','Uccle'),
    'schaerbeek':('Evere','Saint-Josse-ten-Noode','Bruxelles-Ville'),
    'etterbeek':('Ixelles','Auderghem','Woluwe-Saint-Pierre','Woluwe-Saint-Lambert','Bruxelles-Ville'),
    'evere':('Schaerbeek','Woluwe-Saint-Lambert','Bruxelles-Ville'),
    'bruxelles ville':('Schaerbeek','Etterbeek','Ixelles','Saint-Gilles','Anderlecht','Molenbeek-Saint-Jean','Jette','Laeken'),
}


def fetch(url):
    for attempt in range(3):
        try:
            req = Request(url, headers={'User-Agent': UA, 'Accept': 'text/html,application/xhtml+xml'})
            with urlopen(req, timeout=25, context=SSL_CONTEXT) as res:
                if res.status != 200:raise RuntimeError(f'HTTP {res.status} for {url}')
                return res.read().decode('utf-8', errors='replace')
        except HTTPError as e:
            if e.code not in (408,425,429,500,502,503,504) or attempt==2:raise
        except (URLError,TimeoutError) as e:
            if attempt==2:raise
        time.sleep(0.5*(2**attempt))
    raise RuntimeError(f'Requests exhausted for {url}')


def fetch_regie(url):
    # macOS curl uses the system trust store for this public government host;
    # TLS verification remains enabled (no insecure mode or browser emulation).
    for attempt in range(3):
        proc=subprocess.run(['/usr/bin/curl','-fLsS','--max-time','25','--max-redirs','5','-A',UA,url],capture_output=True,text=True,timeout=30)
        if not proc.returncode:return proc.stdout
        message=(proc.stderr or 'Could not fetch Régie Foncière listing page')[-300:]
        if attempt==2:raise RuntimeError(message)
        time.sleep(0.5*(2**attempt))


def robots_ok(url):
    rp = RobotFileParser()
    rp.set_url(HOST + '/robots.txt')
    req = Request(HOST + '/robots.txt', headers={'User-Agent': UA})
    with urlopen(req, timeout=20, context=SSL_CONTEXT) as res:
        if res.status != 200:
            raise RuntimeError('Could not verify robots.txt; refusing to crawl')
        rp.parse(res.read().decode('utf-8', errors='replace').splitlines())
    return rp.can_fetch(UA, url)


def regie_robots_ok(url):
    rp = RobotFileParser()
    rp.set_url(REGIE_HOST + '/robots.txt')
    rules=fetch_regie(REGIE_HOST + '/robots.txt').splitlines()
    rp.parse(rules)
    allowed = rp.can_fetch(UA, url)
    if allowed:
        # robots.txt specifies Crawl-delay: 10 for all agents.
        time.sleep(10)
    return allowed


def source_robots_ok(host, url):
    rp=RobotFileParser(); robots=host+'/robots.txt'; rp.set_url(robots)
    req=Request(robots,headers={'User-Agent':UA})
    with urlopen(req,timeout=20,context=SSL_CONTEXT) as res:
        if res.status!=200: raise RuntimeError('Could not verify robots.txt; refusing to crawl')
        rp.parse(res.read().decode('utf-8',errors='replace').splitlines())
    return rp.can_fetch(UA,url)


def clean_text(value):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>',' ',value)).split())

def energy_metadata(fragment):
    """Retain accessible EPC/PEB text and nearby image or badge attributes."""
    parts=[clean_text(fragment)]
    for tag in re.findall(r'<[^>]+>',fragment,re.I):
        attrs={k:html.unescape(v) for k,v in re.findall(r'([\w:-]+)=["\']([^"\']*)["\']',tag)}
        values=' '.join(str(v) for v in attrs.values())
        if re.search(r'epc|peb|energy|energie',values,re.I):parts.append(values)
    return ' '.join(x for x in parts if x)

def jsonld_energy_metadata(node):
    if not isinstance(node,dict):return ''
    keys=('energyEfficiencyClass','energyRating','energyClass','epc','peb')
    parts=[f'{key} {node[key]}' for key in keys if node.get(key) not in (None,'')]
    extra=node.get('additionalProperty') or []
    if isinstance(extra,dict):extra=[extra]
    for prop in extra if isinstance(extra,list) else []:
        if isinstance(prop,dict) and re.search(r'energy|energie|epc|peb',str(prop.get('name','')),re.I):
            parts.append(str(prop.get('name',''))+' '+str(prop.get('value','')))
    return ' '.join(parts)


def srcset_urls(value):
    return [part.strip().split()[0] for part in value.split(',') if part.strip()]


def photo_attrs(attrs):
    out=[]
    for key in ('src','data-src','data-lazy-src','data-original','data-image','data-fallback-src'):
        if attrs.get(key):out.append(attrs[key])
    for key in ('srcset','data-srcset','data-lazy-srcset'):
        if attrs.get(key):out.extend(srcset_urls(attrs[key]))
    return out


def parse_detail_photos(page, base_url):
    """Extract a listing gallery from public page markup and structured metadata."""
    candidates=[]
    # Some portals serialize their public gallery data into page scripts instead
    # of rendering every slide as an <img> until the visitor opens it.
    serialized=html.unescape(page).replace('\\/','/').replace('\\u002F','/').replace('\\u0026','&')
    candidates.extend(re.findall(r'https?://[^"\'<>\s\\]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\'<>\s\\]*)?',serialized,re.I))
    candidates.extend(re.findall(r'https?://api-image\.immovlan\.be/[^"\'<>\s\\]+',serialized,re.I))
    for tag in re.findall(r'<(?:img|source|meta)\b[^>]*>',page,re.I):
        attrs={k:html.unescape(v) for k,v in re.findall(r'([\w:-]+)=["\']([^"\']*)["\']',tag)}
        candidates.extend(photo_attrs(attrs))
        if attrs.get('property','').lower() in ('og:image','og:image:url') or attrs.get('name','').lower() in ('twitter:image','twitter:image:src'):
            if attrs.get('content'):candidates.append(attrs['content'])
    structured_images=[]
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:todo=[json.loads(html.unescape(block))]
        except (ValueError,TypeError):continue
        while todo:
            node=todo.pop()
            if isinstance(node,list):todo.extend(node);continue
            if not isinstance(node,dict):continue
            image=node.get('image') or node.get('photo') or node.get('associatedMedia') or []
            images=image if isinstance(image,list) else [image]
            for value in images:
                if isinstance(value,str):candidates.append(value);structured_images.append(value)
                elif isinstance(value,dict):
                    for key in ('url','contentUrl','thumbnailUrl'):
                        if isinstance(value.get(key),str):candidates.append(value[key]);structured_images.append(value[key])
            if isinstance(node.get('@graph'),list):todo.extend(node['@graph'])
    # Image delivery often emits the same photograph at several resolutions.
    # Keep its stable image ID once, using the largest advertised rendition.
    groups={};order=[]
    for value in valid_photos([urljoin(base_url,value) for value in candidates]):
        parsed=urlparse(value);match=re.search(r'/images/([^/]+)',parsed.path,re.I)
        if match:
            key='image:'+match.group(1)
            size=re.search(r'/size/(\d+)x(\d+)',parsed.path,re.I)
            rank=1000000+int(size.group(1))*int(size.group(2)) if size else 400 if 'extralarge' in parsed.path.lower() else 300 if 'large' in parsed.path.lower() else 200 if 'medium' in parsed.path.lower() else 100
        elif '/thumbnail-webp/' in parsed.path or '/gallery-like-image/' in parsed.path:
            key='preview:'+parsed.netloc+parsed.path.split('/')[3];rank=0
        else:
            key='url:'+parsed.netloc+parsed.path.split('/size/')[0];rank=0
        if key not in groups:groups[key]=(rank,value);order.append(key)
        elif rank>groups[key][0]:groups[key]=(rank,value)
    if any(k.startswith('image:') for k in groups):order=[k for k in order if not k.startswith('preview:')]
    for value in structured_images:
        m=re.search(r'/images/([^/]+)',urlparse(urljoin(base_url,value)).path,re.I)
        key='image:'+m.group(1) if m else None
        if key in order:order.remove(key);order.insert(0,key)
    return [groups[k][1] for k in order][:12]


@lru_cache(maxsize=2)
def jsonld_index(page):
    """Parse structured metadata once per catalogue, rather than once per card."""
    index={}
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:stack=[json.loads(html.unescape(block))]
        except (ValueError,TypeError):continue
        while stack:
            node=stack.pop()
            if isinstance(node,list):stack.extend(node);continue
            if not isinstance(node,dict):continue
            candidate=node.get('url') or node.get('@id')
            if isinstance(candidate,str):index.setdefault(urlparse(candidate).path.rstrip('/'),{}).update(node)
            stack.extend(v for v in node.values() if isinstance(v,(dict,list)))
    return index


def jsonld_for_url(page,url):
    return dict(jsonld_index(page).get(urlparse(url).path.rstrip('/'),{}))


def jsonld_images(node):
    image=node.get('image',[]) if isinstance(node,dict) else []
    if isinstance(image,str):image=[image]
    out=[]
    for item in image:
        if isinstance(item,str):out.append(item)
        elif isinstance(item,dict) and item.get('url'):out.append(item['url'])
    return out


def source_area_matches(criteria, location):
    normalize=lambda s: re.sub(r'[^a-z0-9]+',' ',''.join(c for c in unicodedata.normalize('NFKD',s.lower()) if not unicodedata.combining(c))).strip()
    loc=normalize(location)
    requested=expanded_areas(criteria)
    if not requested:return False
    for raw in requested:
        wanted=normalize(raw)
        if wanted and (wanted in loc or loc in wanted):return True
        for key,(slug,name) in AREAS.items():
            if normalize(key) in wanted or wanted in normalize(key) or normalize(name)==wanted:
                route_name=slug.split('-',1)[-1]
                if normalize(name) in loc or normalize(route_name) in loc:return True
        if re.search(r'\b\d{4}\b',raw) and re.search(r'\b'+re.escape(re.search(r'\b\d{4}\b',raw).group())+r'\b',location):return True
    return False


def parse_easy_properties(page, criteria, mode='rent'):
    out=[]
    for m in re.finditer(r'<a\s+href="(/fr/listing/[^\"]+)"\s+class="property__inner[^\"]*"[^>]*>(.*?)</a>',page,re.I|re.S):
        card=m.group(2)
        status=re.search(r'class="property__status[^\"]*"[^>]*>(.*?)</',card,re.I|re.S)
        if status: continue
        info=clean_text((re.search(r'class="property__informations[^\"]*"[^>]*>(.*?)</div>',card,re.I|re.S) or [None,''])[1])
        im=re.search(r'\b(\d{4})\s+(.+?)\s+-\s*(Appartement|Maison|Studio|Duplex|Industriel|Bureau|Garage)',info,re.I)
        if not im or im.group(3).lower() not in ('appartement','studio','duplex'):continue
        postal,city=im.group(1),im.group(2).strip()
        location=f'{postal} {city}'
        if not source_area_matches(criteria,location):continue
        title=clean_text((re.search(r'class="property__title[^\"]*"[^>]*>(.*?)</h2>',card,re.I|re.S) or [None,'Appartement à louer'])[1])
        price_m=re.search(r'class="property__price[^\"]*"[^>]*>(.*?)</',card,re.I|re.S)
        price=int(re.sub(r'\D','',clean_text(price_m.group(1)))) if price_m and re.search(r'\d',price_m.group(1)) else None
        tags=clean_text((re.search(r'class="property__tags[^\"]*"[^>]*>(.*?)</div>',card,re.I|re.S) or [None,''])[1])
        nums=re.findall(r'\d+',tags); bedrooms=int(nums[0]) if nums else None
        area_m=re.search(r'(\d+)\s*m',tags,re.I); area=int(area_m.group(1)) if area_m else None
        url=urljoin(EASY_HOST,m.group(1))
        photos=[]
        for tag in re.findall(r'<img\b[^>]*>',card,re.I):
            attrs={k:html.unescape(v) for k,v in re.findall(r'([\w-]+)=["\']([^"\']*)["\']',tag)};photos.extend(photo_attrs(attrs))
        structured=jsonld_for_url(page,url)
        out.append({'id':'easy-'+m.group(1).rstrip('/').split('/')[-1],'source':'Easy Properties','url':url,'title':title,'location':location,'postalCode':postal,'price':price,'fees':None,'bedrooms':bedrooms,'area':area,'summary':title,'energyText':energy_metadata(card)+' '+jsonld_energy_metadata(structured),'available':None,'availability':'À confirmer auprès de l’agence','photos':valid_photos([urljoin(EASY_HOST,p) for p in photos+jsonld_images(structured)]),'publicationDate':structured.get('datePublished'),'sourceModified':structured.get('dateModified')})
    return out


class RedProperties(HTMLParser):
    """Extract individually rendered active property detail panels on Red Immobilier."""
    def __init__(self):
        super().__init__(convert_charrefs=True); self.rows=[]; self.row=None; self.depth=0; self.listing_ids=set(); self.photos={};self.card_id=None
    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        if tag=='div' and 'portfolio-item' in attrs.get('class','').split() and attrs.get('id','').isdigit():
            self.listing_ids.add(attrs['id']);self.card_id=attrs['id'];self.photos.setdefault(self.card_id,[])
        if self.card_id and tag=='img':self.photos[self.card_id].extend(photo_attrs(attrs))
        if self.row is None and tag=='div' and re.fullmatch(r'property\d+',attrs.get('id','')):
            self.row={'id':attrs['id'],'texts':[],'url':''}; self.depth=1; return
        if self.row is None:return
        context=' '.join(str(v) for v in attrs.values())
        if re.search(r'epc|peb|energy|energie',context,re.I):self.row['texts'].append(context)
        if tag=='div':self.depth+=1
        if tag=='a' and '/fr/detail/' in attrs.get('href','') and not self.row['url']:
            self.row['url']=urljoin(RED_HOST,attrs['href'].split('?')[0])
    def handle_data(self,data):
        if self.row is not None and data.strip():self.row['texts'].append(data.strip())
    def handle_endtag(self,tag):
        if self.row is None or tag!='div':return
        self.depth-=1
        if self.depth==0:self.rows.append(self.row);self.row=None


def parse_red_properties(page,criteria,mode='rent'):
    parser=RedProperties();parser.feed(page);out=[]
    for row in parser.rows:
        if row['id'].removeprefix('property') not in parser.listing_ids:continue
        text=' '.join(row['texts']);url=row['url']
        if not url or not re.search(r'Appartement|Studio|Duplex',text,re.I):continue
        # Each hidden detail panel begins with title, municipality, type and rent.
        parts=[clean_text(part) for part in row['texts'] if clean_text(part)]
        title=parts[2] if len(parts)>2 else 'Appartement à louer'
        city=parts[3] if len(parts)>3 else ''
        if not city or not source_area_matches(criteria,city):continue
        def field(label):
            m=re.search(re.escape(label)+r'\s*:?\s*(\d[\d\s.,]*)(?:\s*€)?',text,re.I);return int(re.sub(r'\D','',m.group(1))) if m else None
        price=field('Loyer') if mode=='rent' else field('Prix')
        fees=field('Charges') if mode=='rent' else field('Charges de copropriété')
        area=field('Habitable')
        rooms=field('Chambres')
        if rooms is None:
            rm=re.search(r'(\d+)\s*(?:chambres?|ch\b)',title,re.I);rooms=int(rm.group(1)) if rm else None
        if price is None:
            pm=re.search(r'(\d[\d\s.,]*)\s*€',text);price=int(re.sub(r'\D','',pm.group(1))) if pm else None
        desc=' '.join(row['texts'])[:700]
        photos=valid_photos([urljoin(RED_HOST,p) for p in parser.photos.get(row['id'].removeprefix('property'),[])])
        structured=jsonld_for_url(page,url)
        photos=valid_photos([urljoin(RED_HOST,p) for p in parser.photos.get(row['id'].removeprefix('property'),[])+jsonld_images(structured)])
        out.append({'id':'red-'+row['id'].lower(),'source':'Red Immobilier','url':url,'title':title,'location':city,'price':price,'fees':fees,'bedrooms':rooms,'area':area,'summary':desc,'energyText':energy_metadata(desc)+' '+jsonld_energy_metadata(structured),'available':None,'availability':'Annonce publiée par l’agence' if mode=='rent' else None,'photos':photos,'publicationDate':structured.get('datePublished'),'sourceModified':structured.get('dateModified')})
    return out


class Cards(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.items=[]; self.current=None; self.depth=0; self.capture=[]; self.active=None; self.active_tag=None
    def handle_starttag(self, tag, attrs):
        a=dict(attrs); cls=a.get('class','')
        if self.current is None and tag=='article' and 'v3-search-card' in cls:
            self.current={'url':a.get('data-url',''),'fields':{},'photos':[],'publicationDate':None,'energyText':[],'allText':[]}; self.depth=1; return
        if self.current is None: return
        if tag=='article': self.depth+=1
        if tag=='a' and a.get('href','').startswith('https://immovlan.be/en/detail/') and not self.current.get('url'):
            self.current['url']=a['href']
        if tag=='img':
            brand=logo_attributes(a,HOST)
            if brand:self.current.update(brand)
            else:self.current['photos'].extend(photo_attrs(a))
        attr_text=' '.join(str(v) for v in a.values())
        if re.search(r'epc|peb|energy|energie',attr_text,re.I):self.current['energyText'].append(attr_text)
        if tag=='source' and a.get('srcset'):
            self.current['photos'].extend(srcset_urls(a['srcset']))
        if tag=='time' and a.get('datetime') and not self.current.get('publicationDate'):
            self.current['publicationDate']=a['datetime']
        for field, marker in [('price','v3-search-card-price'),('title','v3-search-card-title'),('location','v3-search-card-location'),('description','v3-search-card-description'),('highlights','v3-search-card-highlights')]:
            if marker in cls.split(): self.active=field; self.active_tag=tag; self.capture=[]; break
    def handle_data(self,data):
        if self.current is not None:
            if data.strip():self.current['allText'].append(data.strip())
            if self.active:self.capture.append(data)
    def handle_endtag(self,tag):
        if self.current is None:return
        if self.active and tag==self.active_tag:
            value=' '.join(' '.join(self.capture).split())
            if value:
                old=self.current['fields'].get(self.active,'')
                self.current['fields'][self.active]=(old+' '+value).strip()
            self.active=None; self.active_tag=None; self.capture=[]
        if tag=='article':
            self.depth-=1
            if self.depth==0:
                self.current['energyText']=' '.join(self.current['energyText']+self.current['allText'])
                self.items.append(self.current); self.current=None


def parse_cards(page,mode='rent'):
    p=Cards(); p.feed(page); out=[]
    for item in p.items:
        f=item['fields']; url=item['url']
        if not url or '/detail/' not in url: continue
        price_match=re.search(r'([\d\u202f\u00a0 ,.]+)',f.get('price',''))
        price=int(re.sub(r'\D','',price_match.group(1))) if price_match else None
        bh=re.search(r'(\d+)\s+Bedroom',f.get('highlights',''),re.I)
        ah=re.search(r'(\d+)\s*m',f.get('highlights',''),re.I)
        bedrooms=int(bh.group(1)) if bh else None
        area=int(ah.group(1)) if ah else None
        structured=jsonld_for_url(page,url)
        photos=valid_photos([urljoin(HOST,p) for p in item.get('photos',[])+jsonld_images(structured)])
        out.append({**{k:item[k] for k in ('agencyName','agencyLogo','agencyWebsite') if item.get(k)},**structured_brand(structured,url),'source':'Immovlan','url':url,'title':f.get('title','Apartment for rent'), 'location':f.get('location','Brussels'), 'price':price,'fees':None,'bedrooms':bedrooms,'area':area,'summary':f.get('description','')[:540],'energyText':item.get('energyText','')+' '+jsonld_energy_metadata(structured), 'available':None,'photos':photos,'publicationDate':item.get('publicationDate') or structured.get('datePublished'),'sourceModified':structured.get('dateModified')})
    return out


def immovlan_page_urls(page, first_url, limit=3):
    """Follow only same-search pagination links; cap each query at three pages."""
    base=urlparse(first_url);candidates={first_url}
    nav=re.search(r'<nav[^>]*class=["\'][^"\']*v3-pagination[^"\']*["\'][^>]*>(.*?)</nav>',page,re.I|re.S)
    if nav:
        for href in re.findall(r'href=["\']([^"\']+)["\']',nav.group(1),re.I):
            absolute=urljoin(first_url,html.unescape(href));parsed=urlparse(absolute)
            if parsed.scheme=='https' and parsed.netloc==base.netloc and parsed.path==base.path:candidates.add(absolute)
    def number(url):
        m=re.search(r'(?:\?|&)page=(\d+)',urlparse(url).query)
        return int(m.group(1)) if m else 1
    ordered=sorted(candidates,key=number)
    return ordered[:max(1,min(3,limit))],len(ordered)>limit


class RegieCards(HTMLParser):
    """Read the factual fields displayed in each public Régie property card."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards=[]; self.current=None; self.text=[]
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=='article' and self.current is None:
            self.current={'url':''}; self.text=[]
        elif self.current is not None and tag=='a' and '/logements/logement-' in attrs.get('href',''):
            self.current['url']=urljoin(REGIE_HOST,attrs['href'])
    def handle_data(self, data):
        if self.current is not None: self.text.append(data)
    def handle_endtag(self, tag):
        if tag=='article' and self.current is not None:
            self.current['text']=' '.join(' '.join(self.text).split())
            self.cards.append(self.current); self.current=None; self.text=[]


def parse_regie_cards(page):
    parser=RegieCards(); parser.feed(page); out=[]
    for card in parser.cards:
        text=card.get('text',''); url=card.get('url','')
        if not url or not re.search(r'\b(?:Appartement|Maison|Studio|Duplex)\b',text,re.I): continue
        price=re.search(r'Loyer\s*:\s*([\d\s.,]+)\s*€',text,re.I)
        fees=re.search(r'Charges\s*:\s*([\d\s.,]+)\s*€',text,re.I)
        rooms=re.search(r'\b(\d+)\s*chambre(?:\(s\))?',text,re.I)
        postal=re.search(r'\b(\d{4})\s+([A-ZÀ-Ÿ][A-ZÀ-Ÿ -]*)',text)
        if not price or not postal: continue
        amount=lambda m: int(re.sub(r'\D','',m.group(1))) if m else None
        municipality=postal.group(2).strip().title()
        out.append({'id':'regie-'+re.sub(r'[^a-zA-Z0-9]+','-',url.rstrip('/').split('/')[-1]).lower(),
            'source':'Régie Foncière de Bruxelles','url':url,'title':'Logement communal à louer',
            'location':f'{postal.group(1)} {municipality}','postalCode':postal.group(1),
            'price':amount(price),'fees':amount(fees),'bedrooms':int(rooms.group(1)) if rooms else None,
            'area':None,'summary':'Annonce de la Régie Foncière de la Ville de Bruxelles. Conditions de candidature à vérifier sur la page officielle.',
            'available':None,'availability':'À confirmer auprès de la Régie'})
    return out


def requested_regie_postcodes(criteria):
    requested=[x.strip().lower() for x in expanded_areas(criteria) if x.strip()]
    brussels_codes={'1000','1020','1120','1130'}
    result=set()
    for item in requested:
        if any(term in item for term in ('bruxelles','brussels','bruxelles-ville','brussels city')):
            result.update(brussels_codes)
        for code in brussels_codes:
            if code in item: result.add(code)
        aliases={'laeken':'1020','neder-over-heembeek':'1120','neder over heembeek':'1120','haren':'1130'}
        for name,code in aliases.items():
            if name in item: result.add(code)
    return result


def matches_areas(criteria):
    requested=expanded_areas(criteria)
    mapped=[]
    for raw in requested:
        normalize=lambda s:re.sub(r'[^a-z0-9]+',' ',''.join(c for c in unicodedata.normalize('NFKD',str(s).lower()) if not unicodedata.combining(c))).strip()
        normalized=normalize(raw)
        pair=next((v for k,v in AREAS.items() if normalize(k)==normalized or normalize(v[1])==normalized),None)
        if not pair:
            folded=''.join(c for c in unicodedata.normalize('NFKD',raw) if not unicodedata.combining(c))
            slug=re.sub(r'[^a-z0-9]+','-',folded.lower()).strip('-')
            # Best effort for unlisted municipalities. An unsupported or incorrect
            # Immovlan slug will be reported as a source error; never substitute another city.
            pair=(slug,raw)
        if pair and pair not in mapped: mapped.append(pair)
    return mapped


def expanded_areas(criteria):
    """Resolve well-known Belgian city names/postcodes and optional one-hop Brussels neighbours."""
    normalize=lambda s:re.sub(r'[^a-z0-9]+',' ',''.join(c for c in unicodedata.normalize('NFKD',str(s).lower()) if not unicodedata.combining(c))).strip()
    requested=[x.strip() for x in re.split(r'[,;\n]',str(criteria.get('areas',''))) if x.strip()]
    pairs=[];names=[]
    for raw in requested:
        wanted=normalize(raw)
        pair=next((value for key,value in AREAS.items() if normalize(key) in wanted or wanted in normalize(key) or normalize(value[1])==wanted),None)
        if pair is None:
            folded=''.join(c for c in unicodedata.normalize('NFKD',raw) if not unicodedata.combining(c));pair=(re.sub(r'[^a-z0-9]+','-',folded.lower()).strip('-'),raw)
        if pair not in pairs:pairs.append(pair);names.append(pair[1])
    if criteria.get('nearby',True):
        for pair in list(pairs):
            key=normalize(pair[1]);neighbors=NEARBY_AREAS.get(key,())
            for name in neighbors:
                wanted=normalize(name);neighbor=next((v for k,v in AREAS.items() if normalize(v[1])==wanted),None)
                if neighbor and neighbor not in pairs:pairs.append(neighbor);names.append(neighbor[1])
    # Return display names for source-card location matching; match_areas maps to route slugs.
    return names


def ensure_mode_data():
    rent=DATA/'rent';sale=DATA/'sale'
    rent.mkdir(parents=True,exist_ok=True);sale.mkdir(parents=True,exist_ok=True)
    legacy_criteria=DATA/'criteria.json';legacy_listings=DATA/'listings.json';legacy_status=DATA/'status.json'
    if not (rent/'criteria.json').exists():
        old=json.loads(legacy_criteria.read_text()) if legacy_criteria.exists() else DEFAULT_RENT
        merged={**DEFAULT_RENT,**old};atomic_json(rent/'criteria.json',merged)
    if not (sale/'criteria.json').exists():
        rent_criteria=json.loads((rent/'criteria.json').read_text()) if (rent/'criteria.json').exists() else DEFAULT_RENT
        sale_criteria={**DEFAULT_SALE,'areas':rent_criteria.get('areas',''),'nearby':rent_criteria.get('nearby',True)}
        atomic_json(sale/'criteria.json',sale_criteria)
    for name,legacy,default in (('listings.json',legacy_listings,[]),('status.json',legacy_status,{})):
        if not (rent/name).exists():
            value=json.loads(legacy.read_text()) if legacy.exists() else default
            if name=='listings.json':
                for row in value:
                    row.setdefault('transaction','rent');row.setdefault('firstDiscovered',row.get('seen'));row.setdefault('lastObserved',row.get('seen'));row.setdefault('photos',[]);row.setdefault('publicationDate',None)
            atomic_json(rent/name,value)
    for name,default in (('listings.json',[]),('status.json',{})):
        if not (sale/name).exists():atomic_json(sale/name,default)


def mode_file(mode,name):
    if mode not in MODES:raise ValueError('Unknown transaction mode')
    ensure_mode_data();return DATA/mode/name


def _adapter(mode,criteria,requested,now,previous_by_id=None):
    rows=[];results=[];active=[];failed_sources=set()
    areas=requested
    ptype=(criteria.get('property') or 'Apartment').lower()
    types=['house'] if 'house' in ptype and 'apartment' not in ptype else ['apartment']
    if 'apartment or house' in ptype:types=['apartment','house']
    route='for-rent' if mode=='rent' else 'for-sale'
    for slug,name in areas:
        for kind in types:
            url=f'{HOST}/en/real-estate/{kind}/{route}/{slug}'
            try:
                if not robots_ok(url):raise PermissionError('Disallowed by robots.txt')
                first_page=fetch(url);page_urls,more=immovlan_page_urls(first_page,url,3);count=0;partial=more;page_errors=[]
                for page_index,page_url in enumerate(page_urls):
                    try:
                        if page_index and not robots_ok(page_url):raise PermissionError('Pagination disallowed by robots.txt')
                        page=first_page if page_index==0 else fetch(page_url)
                        for row in parse_cards(page,mode):
                            row['id']='immovlan-'+re.sub(r'[^a-zA-Z0-9]+','-',row['url'].rstrip('/').split('/')[-1]).lower()
                            row['areaSearch']=name
                            if mode=='rent':row['availability']=next((m.group(0) for m in [re.search(r'(?:available|availability|libre|beschikbaar)[^.;]{0,55}',row['summary'],re.I)] if m),'À confirmer auprès de l’agence')
                            rows.append(row);count+=1
                    except Exception as page_error:
                        partial=True;page_errors.append(str(page_error)[:180]);break
                    if page_index:time.sleep(1.2)
                results.append({'source':'Immovlan','area':name,'type':kind,'ok':True,'found':count,'partial':partial,'pages':len(page_urls),'note':('Cap de trois pages atteint; résultats partiels.' if more else '; '.join(page_errors))})
                active.append('Immovlan')
            except Exception as e:
                failed_sources.add('Immovlan');results.append({'source':'Immovlan','area':name,'type':kind,'ok':False,'reason':str(e)[:250]})
            time.sleep(1.2)
    for name,host,url,parser,modes in (
        ('Easy Properties',EASY_HOST,EASY_LISTINGS if mode=='rent' else EASY_SALE_LISTINGS,parse_easy_properties,('rent','sale')),
        ('Red Immobilier',RED_HOST,RED_LISTINGS if mode=='rent' else RED_SALE_LISTINGS,parse_red_properties,('rent','sale')),
    ):
        try:
            if not source_robots_ok(host,url):raise PermissionError('Disallowed by robots.txt')
            page=fetch(url);found=parser(page,criteria,mode);rows.extend(found)
            results.append({'source':name,'area':'selected regions','type':mode,'ok':True,'found':len(found),'partial':name=='Easy Properties','note':'Pagination partielle; première page publique uniquement.' if name=='Easy Properties' else ''})
            active.append(name)
        except Exception as e:
            failed_sources.add(name);results.append({'source':name,'area':'selected regions','type':mode,'ok':False,'reason':str(e)[:250]})
        time.sleep(1.2)
    restricted_agencies=read_agency_json(DATA/'agencies'/'requested-agencies.json',{}).get('agencies',[])
    sorimo_restricted=any(a.get('domain')=='sorimo.be' and a.get('siteTermsStatus')=='restricted' for a in restricted_agencies)
    if sorimo_restricted:
        sorimo_rows=[]
        sorimo_result={'source':'Sorimo','transaction':mode,'ok':False,'partial':True,'found':0,'reason':'Collecte suspendue : accord écrit préalable requis selon les conditions enregistrées.'}
    else:
        sorimo_rows,sorimo_result=collect_sorimo(mode,criteria,fetch,source_robots_ok,source_area_matches)
    rows.extend(sorimo_rows);results.append(sorimo_result)
    if sorimo_result['ok']:active.append('Sorimo')
    if not sorimo_result['ok'] or sorimo_result['partial']:failed_sources.add('Sorimo')
    try:
        direct_rows,direct_results=collect_brussels(mode,criteria)
        rows.extend(direct_rows)
        for result in direct_results:
            results.append(result)
            if result.get('ok'):active.append(result['source'])
            if not result.get('ok') or result.get('partial'):failed_sources.add(result['source'])
    except Exception as agency_error:
        results.append({'source':'Brussels direct agencies','transaction':mode,'ok':False,'reason':str(agency_error)[:250]})
        failed_sources.update(s.get('name','') for s in __import__('json').loads((DATA/'agencies'/'brussels-sources.json').read_text()) if s.get('enabled'))
    try:
        # A scheduled/manual collection should sweep the whole reviewed and
        # robots-allowed agency inventory, not just eight rotating domains.
        # The collector remains sequential and rate-limited per site.
        agency_rows,agency_result=collect_agency_listings(criteria,previous_by_id or {},limit=500,mode=mode)
        agency_rows=[r for r in agency_rows if r.get('location') and source_area_matches(criteria,r.get('location',''))]
        agency_result['collectedBeforeAreaFilter']=agency_result.get('found',0)
        agency_result['found']=len(agency_rows)
        rows.extend(agency_rows);results.append(agency_result)
        if agency_result.get('ok') and (agency_result.get('checkedSites',0)>0 or agency_result.get('found',0)>0):active.append(agency_result['source'])
        failed_sources.update(agency_result.get('failedSources',[]))
    except Exception as e:
        failed_sources.add('Agency-owned sites (JSON-LD)')
        results.append({'source':'Agency-owned sites (JSON-LD)','ok':False,'reason':str(e)[:250]})
    if mode=='sale':
        try:
            include_houses='house' in ptype
            biddit_rows,biddit_result=collect_biddit('sale',include_houses=include_houses)
            before=len(biddit_rows)
            biddit_rows=[r for r in biddit_rows if source_area_matches(criteria,r.get('location',''))]
            biddit_result['collectedBeforeAreaFilter']=before
            biddit_result['found']=len(biddit_rows)
            rows.extend(biddit_rows);results.append(biddit_result)
            if biddit_result.get('ok'):active.append('Biddit')
            if biddit_result.get('partial'):
                failed_sources.add('Biddit')
        except Exception as e:
            failed_sources.add('Biddit')
            results.append({'source':'Biddit','transaction':'sale','ok':False,'reason':str(e)[:250]})
    if mode=='rent':
        regie_codes=requested_regie_postcodes(criteria)
        if regie_codes:
            try:
                if not regie_robots_ok(REGIE_LISTINGS):raise PermissionError('Disallowed by robots.txt')
                found=[x for x in parse_regie_cards(fetch_regie(REGIE_LISTINGS)) if x.get('postalCode') in regie_codes]
                rows.extend(found);results.append({'source':'Régie Foncière de Bruxelles','area':'Bruxelles-Ville','type':'public rentals','ok':True,'found':len(found),'partial':False});active.append('Régie Foncière de Bruxelles')
            except Exception as e:
                failed_sources.add('Régie Foncière de Bruxelles');results.append({'source':'Régie Foncière de Bruxelles','area':'Bruxelles-Ville','type':'public rentals','ok':False,'reason':str(e)[:250]})
    return rows,results,sorted(set(active)),failed_sources


def deduplicate_listings(found,mode,today,previous=None):
    """Conservative cross-source merge: exact URL or complete exact unit signature."""
    previous=previous or {};seen={}
    for raw in found:
        row=normalize_listing(with_branding(raw),mode,today,previous.get(raw.get('id')))
        urlkey=('url',row.get('url','').split('#')[0].rstrip('/').lower())
        address=' '.join(str(row.get('streetAddress') or '').lower().split())
        postal=str(row.get('postalCode') or '').strip()
        addrkey=('address',address,postal,row.get('price'),row.get('area'),row.get('bedrooms')) if address and postal and row.get('price') is not None and row.get('area') is not None else None
        key=urlkey if urlkey[1] else ('source',row.get('source'),row.get('id'))
        target=addrkey if addrkey and addrkey in seen else key
        attribution={'source':row.get('source'),'url':row.get('url'),'agencyWebsite':row.get('agencyWebsite')}
        if target in seen:
            kept=seen[target]
            attrs=kept.setdefault('sourceAttributions',[{'source':kept.get('source'),'url':kept.get('url'),'agencyWebsite':kept.get('agencyWebsite')}])
            if attribution not in attrs:attrs.append(attribution)
            if addrkey:seen[addrkey]=kept
        else:
            row['sourceAttributions']=[attribution];seen[key]=row
            if addrkey:seen[addrkey]=row
    result=[];ids=set()
    for row in seen.values():
        if id(row) not in ids:ids.add(id(row));result.append(row)
    return result


def _collect_unlocked(mode='rent'):
    ensure_mode_data();criteria=json.loads(mode_file(mode,'criteria.json').read_text());old=json.loads(mode_file(mode,'listings.json').read_text())
    previous={x.get('id'):x for x in old if x.get('id')};requested=matches_areas(criteria);now=datetime.now(TZ);stamp=now.isoformat(timespec='seconds')
    if not requested:
        status={'state':'no-areas','transaction':mode,'lastRun':stamp,'nextRun':'10:00 et 17:00 Europe/Brussels','activeSources':[],'sources':[],'note':'Ajoutez une commune ou un code postal pour lancer la collecte.','matchingCount':0,'nearMissCount':0,'displayedCount':0}
        atomic_json(mode_file(mode,'status.json'),status);print(json.dumps({'status':status,'results':len(old)},ensure_ascii=False));return old
    found,source_results,active,failed=_adapter(mode,criteria,requested,stamp,previous)
    seen={};today=now.date().isoformat()
    deduped=deduplicate_listings(found,mode,today,previous)
    for row in deduped:
        seen[('url',row.get('url','').split('#')[0].rstrip('/').lower())]=row
    # A temporary source failure must not erase its previous successful records.
    for prior in old:
        if prior.get('source') in failed or (prior.get('sourceType')=='agency-site' and prior.get('agencyDomain') in failed):
            key=('url',prior.get('url','').split('#')[0].rstrip('/').lower())
            if key not in seen:
                copy=dict(prior);copy['stale']=True;seen[key]=copy
    # The alias key points at the same dict, so discard duplicate references before normalization.
    unique_entries=[];object_ids=set()
    for row in seen.values():
        if id(row) not in object_ids:object_ids.add(id(row));unique_entries.append(row)
    entries=[]
    for row in unique_entries:
        prior=previous.get(row.get('id'),{})
        row=evaluate_listing(row,criteria,mode,prior.get('renovationOverride'))
        entries.append(row)
    ordered=best_rows(entries,criteria)
    confirmed=[x for x in ordered if x.get('matchState')=='confirmed'];unknown=[x for x in ordered if x.get('matchState')=='unknown'];failed_rows=[x for x in ordered if x.get('matchState')=='failed']
    # Keep every result; UI separates exacts, up to two suggestions, and allows more results.
    final=confirmed+unknown+failed_rows
    success=any(x.get('ok') for x in source_results);partial=any(not x.get('ok') or x.get('partial') for x in source_results)
    status={'state':'partial' if partial and success else 'complete' if success else 'source-error','transaction':mode,'lastRun':stamp,'nextRun':'10:00 et 17:00 Europe/Brussels','activeSources':active,'sources':source_results,'agencyCoverage':read_agency_json(MONITOR_FILE,{}),'note':'Une valeur inconnue n’est pas considérée comme une correspondance confirmée. Vérifiez les détails et la disponibilité sur l’annonce originale.','matchingCount':len(confirmed),'unknownCount':len(unknown),'nearMissCount':min(2,len(unknown)),'totalCollected':len(final),'displayedCount':len(final),'partial':partial}
    atomic_json(mode_file(mode,'listings.json'),final);atomic_json(mode_file(mode,'status.json'),status)
    print(json.dumps({'status':status,'results':len(final),'matches':len(confirmed),'unknown':len(unknown)},ensure_ascii=False,indent=2));return final


def collect(mode='rent'):
    if mode not in MODES:raise ValueError('Mode must be rent or sale')
    ensure_mode_data();lock_path=DATA/mode/'.collection.lock'
    with lock_path.open('w') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise CollectionBusyError(f'Une collecte {mode} est déjà en cours; aucun résultat n’a été remplacé.')
        try:return _collect_unlocked(mode)
        finally:fcntl.flock(lock.fileno(),fcntl.LOCK_UN)


def collect_all():
    outcomes={}
    for mode in MODES:
        try:outcomes[mode]={'ok':True,'count':len(collect(mode))}
        except CollectionBusyError as e:
            outcomes[mode]={'ok':False,'busy':True,'error':str(e)}
        except Exception as e:
            outcomes[mode]={'ok':False,'error':str(e)[:400]}
            try:
                prior=json.loads(mode_file(mode,'status.json').read_text());prior.update({'state':'source-error','error':str(e)[:400],'lastAttempt':datetime.now(TZ).isoformat(timespec='seconds')});atomic_json(mode_file(mode,'status.json'),prior)
            except Exception:pass
    return outcomes


if __name__=='__main__':
    import sys
    selected=sys.argv[1] if len(sys.argv)>1 else 'rent'
    if selected=='sorimo':
        refresh_modes(sys.argv[2:] or ['rent','sale']);raise SystemExit(0)
    try:result=collect_all() if selected=='all' else {'count':len(collect(selected))}
    except CollectionBusyError as e:
        import sys as _sys;print(str(e),file=_sys.stderr);raise SystemExit(75)
    print(json.dumps(result,ensure_ascii=False))
