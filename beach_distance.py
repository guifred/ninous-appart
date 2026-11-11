"""Approximate proximity to the Belgian beach from published listing coordinates."""
import html
import json
import math
import re
import subprocess
import unicodedata
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode, urlsplit, unquote
from urllib.request import Request, urlopen

# Approximate points along the open sandy coast, west to east. Segment
# interpolation avoids measuring every home against only a town centre.
BEACH_LINE = (
    (51.1013, 2.5820), (51.1066, 2.6035), (51.1130, 2.6320),
    (51.1204, 2.6637), (51.1350, 2.6910), (51.1510, 2.7160),
    (51.1700, 2.7660), (51.1846, 2.8050), (51.1990, 2.8410),
    (51.2180, 2.8870), (51.2340, 2.9200), (51.2420, 2.9630),
    (51.2540, 2.9940), (51.2740, 3.0310), (51.2940, 3.0750),
    (51.3160, 3.1280), (51.3290, 3.1800), (51.3410, 3.2380),
    (51.3550, 3.2890),
)

# Verified project location: Portanic's official site and the city of
# Nieuwpoort identify the development at Albert I Laan 65-67 / Jozef
# Cardijnlaan 56-58. The coordinates are the Flemish address-register result
# for Jozef Cardijnlaan 56 (entrance), not a guess from the town centroid.
KNOWN_RESIDENCES = {
    'portanic': ('Jozef Cardijnlaan 56', 'Nieuwpoort', 51.140174203109709, 2.7365549213070959),
}
_GEOCODE_CACHE = {}
_AREA_CENTRES = {
    'ramskapelle':(51.110,2.761,8), 'nieuwpoort':(51.135,2.748,14),
    'de panne':(51.101,2.590,12), 'koksijde':(51.119,2.650,12),
    'middelkerke':(51.183,2.818,12), 'oostende':(51.224,2.921,12),
    'bredene':(51.239,2.963,12), 'de haan':(51.271,3.035,12),
    'blankenberge':(51.313,3.132,12), 'zeebrugge':(51.329,3.203,12),
    'knokke':(51.349,3.283,14),
}
_CACHE_FILE = Path(__file__).resolve().parent / 'data/coast/address-geocodes.json'
_CACHE_LOCK = Lock()
try:
    _GEOCODE_CACHE.update({k:tuple(v) for k,v in json.loads(_CACHE_FILE.read_text()).items()})
except (OSError,ValueError,TypeError):pass

_ADDRESS = re.compile(r"((?:[A-ZÀ-Ý][\wÀ-ÿ'.-]*\s+){0,2}[A-ZÀ-Ý][\wÀ-ÿ'.-]*(?:straat|laan|dijk|weg|plein|kaai|lei|steeg|vaart|promenade)|(?:[A-ZÀ-Ý][\wÀ-ÿ'.-]*\s+){0,2}(?:Steenweg|Boulevard|Avenue|Rue|Place|Quai))\s+(\d{1,4}[A-Za-z]?)\b")
_ADDRESS_STOP = {'appartement','studio','woning','villa','koop','nieuwpoort','located','at','building','in','te','de','het','la','residence','residentie'}
_RESIDENCE = re.compile(r'\b(?:residentie|résidence|residence|res\.)\s+([A-ZÀ-Ý][\wÀ-ÿ-]{3,}(?:\s+[A-ZÀ-Ý][\wÀ-ÿ-]{3,})?)',re.I)
_JSON_LD = re.compile(r'<script[^>]+type=["\']application/ld(?:\+|&#x2B;|&#43;)json["\'][^>]*>(.*?)</script>',re.I|re.S)


def extract_address_from_text(text):
    """Find a numbered street in an advert, leaving vague road names unresolved."""
    special=re.search(r'\bAlbert\s+I[\s-]+laan\s+(\d{1,4}[A-Za-z]?)\b',html.unescape(str(text or '')),re.I)
    if special:return 'Albert I laan '+special.group(1)
    for match in _ADDRESS.finditer(html.unescape(str(text or ''))):
        words=match.group(1).split()
        while len(words)>1 and words[0].lower().strip('.-') in _ADDRESS_STOP:words.pop(0)
        address=' '.join(words)+' '+match.group(2)
        if len(address)<6:continue
        return address
    fallback=re.search(r'\b([a-zà-ÿ][\wà-ÿ-]*(?:straat|laan|dijk|weg|plein|kaai|lei|steeg|vaart|promenade))\s+(\d{1,4}[A-Za-z]?)\b',str(text or ''),re.I)
    if fallback:return fallback.group(1)+' '+fallback.group(2)
    return None


def extract_address_from_url(url):
    """Some agencies publish the street and house number in the advert slug."""
    segments=[unquote(x) for x in urlsplit(str(url or '')).path.split('/') if x]
    for segment in reversed(segments):
        match=re.fullmatch(r'([a-zà-ÿ-]+(?:straat|laan|dijk|weg|plein|kaai|lei|steeg|vaart))-([1-9]\d{0,3}[a-z]?)(?:-\d+)?',segment,re.I)
        if match:
            return ' '.join(part.capitalize() for part in match.group(1).split('-'))+' '+match.group(2)
    return None


def _norm_name(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value or '').lower()) if not unicodedata.combining(c))


def residence_names(row):
    text=' '.join(str(row.get(k) or '') for k in ('title','summary'))
    names=set()
    for match in _RESIDENCE.finditer(text):
        name=_norm_name(match.group(1).strip())
        name=re.sub(r'\s+[a-z]$','',name)
        if name not in ('nieuwpoort','appartement','vastgoed','te koop','located') and len(name)>=5:names.add(name)
    return names


def persist_geocodes():
    """Keep only confirmed address coordinates between daily collections."""
    _CACHE_FILE.parent.mkdir(parents=True,exist_ok=True)
    _CACHE_FILE.write_text(json.dumps({k:v for k,v in _GEOCODE_CACHE.items() if v},ensure_ascii=False,indent=2)+'\n')


def _norm_address(value):
    return re.sub(r'[^a-z0-9]','',html.unescape(str(value or '')).lower())


def _geocode(address,city):
    query=address+', '+city
    with _CACHE_LOCK:
        if query in _GEOCODE_CACHE:return _GEOCODE_CACHE[query]
    try:
        variants=[query]
        canonical=re.sub(r'\bI-laan\b','I laan',address,flags=re.I)
        if canonical!=address:variants.append(canonical+', '+city)
        if 'Ramskapelle' in city:variants.append(address+', '+city.replace('Ramskapelle','Nieuwpoort'))
        candidates=[]
        for variant in variants:
            url='https://geo.api.vlaanderen.be/geolocation/v4/Location?'+urlencode({'q':variant})
            request=Request(url,headers={'User-Agent':'NinousAppartementFinder/0.1 (personal real-estate search)'})
            try:
                with urlopen(request,timeout=2) as response:data=json.load(response)
            except OSError:
                result=subprocess.run(['curl','-fsSL','--max-time','8',url],capture_output=True,text=True,timeout=10,check=True)
                data=json.loads(result.stdout)
            candidates=data.get('LocationResult') or []
            if candidates:break
        postal=re.search(r'\b\d{4}\b',city)
        match=next((x for x in candidates if
                    re.search(r'\b'+re.escape(str(x.get('Housenumber') or ''))+r'\b',address,re.I) and
                    (str(x.get('Municipality') or '').lower() in city.lower() or
                     (postal and x.get('Zipcode')==postal.group())) and
                    _norm_address(x.get('Thoroughfarename')) in _norm_address(address)),None)
        position=(match or {}).get('Location') or {}
        pair=_coastal_pair(position.get('Lat_WGS84'),position.get('Lon_WGS84'))
    except (OSError,ValueError,TypeError,subprocess.SubprocessError):pair=None
    with _CACHE_LOCK:_GEOCODE_CACHE[query]=pair
    return pair


def resolve_property_location(row):
    """Locate an identifiable residence or numbered Flemish street address."""
    existing=_coastal_pair(row.get('latitude'),row.get('longitude'))
    if existing and _area_pair_ok(row,existing):return row
    if existing and not _area_pair_ok(row,existing):
        row.pop('latitude',None);row.pop('longitude',None);row.pop('beachLocationBasis',None)
    words=' '.join(str(row.get(k) or '') for k in ('title','summary','streetAddress')).lower()
    city=str(row.get('location') or '')
    for name,(address,municipality,lat,lon) in KNOWN_RESIDENCES.items():
        if name in words and municipality.lower() in city.lower():
            row['latitude'],row['longitude']=lat,lon
            row['beachLocationBasis']='verified-residence'
            return row
    address=(str(row.get('streetAddress') or '').strip() or
             extract_address_from_text(row.get('summary')) or
             extract_address_from_text(row.get('title')) or
             extract_address_from_url(row.get('url')))
    if not address or not re.search(r'\b\d+[a-zA-Z]?\b',address) or not city:return row
    pair=_geocode(address,city)
    if pair and _area_pair_ok(row,pair):
        row['latitude'],row['longitude']=pair
        row['beachLocationBasis']='verified-address'
        row['streetAddress']=address
    return row


def enrich_coastal_locations(rows):
    """Resolve addresses, then transfer a unique residence location to its ads."""
    for row in rows:add_beach_distance(row)
    known={}
    candidate_names=set().union(*(residence_names(row) for row in rows))
    for row in rows:
        pair=_coastal_pair(row.get('latitude'),row.get('longitude'))
        if not pair:continue
        text=_norm_name(' '.join(str(row.get(k) or '') for k in ('title','summary')))
        for name in candidate_names:
            if re.search(r'\b'+re.escape(name)+r'\b',text):
                known.setdefault((name,str(row.get('location') or '').split()[-1].lower()),set()).add(pair)
    def compact_location(pairs):
        if not pairs:return None
        centre=(sum(p[0] for p in pairs)/len(pairs),sum(p[1] for p in pairs)/len(pairs))
        # Multiple unit map pins can differ slightly; farther apart means the
        # residence name is ambiguous and must not be propagated.
        if any(math.hypot((p[0]-centre[0])*111195,(p[1]-centre[1])*70000)>120 for p in pairs):return None
        return centre
    unique={key:pair for key,pairs in known.items() if (pair:=compact_location(pairs))}
    for row in rows:
        if row.get('beachDistanceM') is not None or row.get('beachWalkMinutes') is not None:continue
        city=str(row.get('location') or '').split()[-1].lower()
        matches={unique[(name,city)] for name in residence_names(row) if (name,city) in unique}
        if len(matches)!=1:continue
        row['latitude'],row['longitude']=next(iter(matches))
        row['beachLocationBasis']='matched-residence'
        add_beach_distance(row)
    persist_geocodes()
    return rows


def _coastal_pair(lat, lon):
    try:
        lat=float(lat);lon=float(lon)
    except (ValueError,TypeError):return None
    return (lat,lon) if 50.95<=lat<=51.48 and 2.48<=lon<=3.48 else None


def _area_pair_ok(row,pair):
    place=str(row.get('location') or '').lower()
    centre=next((v for name,v in _AREA_CENTRES.items() if name in place),None)
    if not centre:return True
    lat,lon,radius_km=centre
    return math.hypot((pair[0]-lat)*111.195,(pair[1]-lon)*111.195*math.cos(math.radians(lat)))<=radius_km


def extract_coordinates(page):
    """Use property map attributes or property-specific JSON-LD, never office maps."""
    for block in _JSON_LD.findall(page):
        try:todo=[json.loads(html.unescape(block))]
        except ValueError:continue
        while todo:
            node=todo.pop()
            if isinstance(node,list):todo.extend(node);continue
            if not isinstance(node,dict):continue
            typ=node.get('@type') or [];typ=[typ] if isinstance(typ,str) else typ
            if any(t in ('Apartment','House','Residence','RealEstateListing','Accommodation') for t in typ):
                about=node.get('about')
                geo=node.get('geo') or (about.get('geo') if isinstance(about,dict) else None)
                if isinstance(geo,dict):
                    pair=_coastal_pair(geo.get('latitude'),geo.get('longitude'))
                    if pair:return pair
            for value in node.values():
                if isinstance(value,(dict,list)):todo.append(value)
    for tag in re.findall(r'<[^>]+>',page):
        attrs=dict((key.lower(),html.unescape(value)) for key,value in re.findall(r'([\w:-]+)=["\']([^"\']+)["\']',tag))
        marker=(attrs.get('class','')+' '+attrs.get('id','')).lower()
        if not re.search(r'\b(?:panddetail|property-map|detail-map|listing-map|gmap|map-property)\b',marker):continue
        lat=attrs.get('data-lat') or attrs.get('data-latitude') or attrs.get('data-map-lat')
        lon=attrs.get('data-long') or attrs.get('data-lng') or attrs.get('data-lon') or attrs.get('data-longitude') or attrs.get('data-map-lng')
        pair=_coastal_pair(lat,lon)
        if pair:return pair
    lat=re.search(r'window\.AD_LATITUDE\s*=\s*["\']([\d.]+)',page)
    lon=re.search(r'window\.AD_LONGITUDE\s*=\s*["\']([\d.]+)',page)
    if lat and lon:
        pair=_coastal_pair(lat[1],lon[1])
        if pair:return pair
    for tag in re.findall(r'<(?:a|iframe|img)\b[^>]+>',page,re.I):
        if 'maps.google' in tag or 'google.com/maps' in tag:
            match=re.search(r'(?:[?&](?:sll|ll|center)=)([\d.]+)[,+]([\d.]+)',html.unescape(tag),re.I)
            if match:
                pair=_coastal_pair(match[1],match[2])
                if pair:return pair
        if 'property-map' in tag and 'staticmap' in tag:
            match=re.search(r'center=([\d.]+),([\d.]+)',html.unescape(tag),re.I)
            if match:
                pair=_coastal_pair(match[1],match[2])
                if pair:return pair
        if 'era-location-mapbox-static-map' in tag:
            match=re.search(r'marker[^"\']*\(([\d.]+),([\d.]+)\)',tag,re.I)
            if match:
                pair=_coastal_pair(match[2],match[1])
                if pair:return pair
    return None


def listing_description(page):
    """Read a property's own description from structured data or page metadata."""
    for block in _JSON_LD.findall(page):
        try:todo=[json.loads(html.unescape(block))]
        except ValueError:continue
        while todo:
            node=todo.pop()
            if isinstance(node,list):todo.extend(node);continue
            if not isinstance(node,dict):continue
            typ=node.get('@type') or [];typ=[typ] if isinstance(typ,str) else typ
            if any(t in ('Apartment','House','Residence','RealEstateListing','Accommodation') for t in typ):
                description=node.get('description')
                if isinstance(description,str) and len(description)>40:
                    return ' '.join(html.unescape(re.sub(r'<[^>]+>',' ',description)).split())[:1800]
            for value in node.values():
                if isinstance(value,(dict,list)):todo.append(value)
    for tag in re.findall(r'<meta\b[^>]*>',page,re.I):
        attrs=dict((key.lower(),html.unescape(value)) for key,value in re.findall(r'([\w:-]+)=["\']([^"\']+)["\']',tag))
        if attrs.get('name','').lower()=='description' or attrs.get('property','').lower()=='og:description':
            description=attrs.get('content','')
            if len(description)>40:return ' '.join(re.sub(r'<[^>]+>',' ',description).split())[:1800]
    return ''


def extract_detail_address(page):
    """Prefer the property's structured address or its own map link."""
    for block in _JSON_LD.findall(page):
        try:todo=[json.loads(html.unescape(block))]
        except ValueError:continue
        while todo:
            node=todo.pop()
            if isinstance(node,list):todo.extend(node);continue
            if not isinstance(node,dict):continue
            typ=node.get('@type') or [];typ=[typ] if isinstance(typ,str) else typ
            if any(t in ('Apartment','House','Residence','RealEstateListing','Accommodation','Product') for t in typ):
                about=node.get('about')
                address=node.get('address') or (about.get('address') if isinstance(about,dict) else None)
                if isinstance(address,dict):address=address.get('streetAddress')
                candidate=extract_address_from_text(address)
                if candidate:return candidate
            for value in node.values():
                if isinstance(value,(dict,list)):todo.append(value)
    for tag,body in re.findall(r'(<a\b[^>]*href=["\'][^"\']*(?:maps\.google|google\.com/maps)[^"\']*["\'][^>]*>)(.*?)</a>',page,re.I|re.S):
        candidate=extract_address_from_text(re.sub(r'<[^>]+>',' ',body))
        if candidate:return candidate
        href=re.search(r'href=["\']([^"\']+)',tag,re.I)
        if href:
            candidate=extract_address_from_text(unquote(html.unescape(href[1])).replace('+',' '))
            if candidate:return candidate
    field=re.search(r'>\s*Adres\s*</div>\s*<div[^>]*>\s*:\s*</div>\s*<div[^>]*>(.*?)</div>',page,re.I|re.S)
    if field:
        candidate=extract_address_from_text(re.sub(r'<[^>]+>',' ',field[1]))
        if candidate:return candidate
    return extract_address_from_text(listing_description(page))


def distance_to_beach(lat,lon):
    pair=_coastal_pair(lat,lon)
    if not pair:return None
    lat,lon=pair
    scale_x=111_195*math.cos(math.radians(lat))
    scale_y=111_195
    point=(lon*scale_x,lat*scale_y)
    best=float('inf')
    for (a_lat,a_lon),(b_lat,b_lon) in zip(BEACH_LINE,BEACH_LINE[1:]):
        ax,ay=a_lon*scale_x,a_lat*scale_y
        bx,by=b_lon*scale_x,b_lat*scale_y
        dx,dy=bx-ax,by-ay
        fraction=max(0,min(1,((point[0]-ax)*dx+(point[1]-ay)*dy)/(dx*dx+dy*dy)))
        best=min(best,math.hypot(point[0]-ax-fraction*dx,point[1]-ay-fraction*dy))
    metres=max(0,round(best/50)*50)
    # An indicative walking time; actual paths, barriers and entrances vary.
    minutes=max(1,round((metres*1.3)/80))
    return metres,minutes


def stated_proximity(text):
    """Extract only explicit beach/coast distances and walking times in ad text."""
    text=' '.join(html.unescape(str(text or '')).lower().split())
    place=r'(?:strand|plage|zee|mer|zeedijk|dijk|côte|kust)'
    distance=(re.search(r'\b(\d{1,4}(?:[,.]\d)?)\s*(km|kilom[eè]tres?|m[eè]tres?|meter|m)\s*(?:van|tot|de|du|à|a)\s*(?:het|la|le|de|du)?\s*'+place,text) or
              re.search(place+r'\s*(?:op|à|a|environ|ca\.?|circa|±)?\s*(\d{1,4}(?:[,.]\d)?)\s*(km|kilom[eè]tres?|m[eè]tres?|meter|m)\b',text))
    metres=None
    if distance:
        value=float(distance.group(1).replace(',','.'))
        metres=round(value*1000 if distance.group(2).startswith(('km','kilo')) else value)
        if metres>20_000:metres=None
    walking=(re.search(r'\b(\d{1,2})\s*(?:min(?:utes?|uten)?)\s*(?:à pied|a pied|wandelen|walking|lopen)\s*(?:van|de|du|tot|à|a)?\s*(?:het|la|de|du)?\s*'+place,text) or
             re.search(place+r'.{0,35}?\b(\d{1,2})\s*min(?:utes?|uten)?\s*(?:à pied|a pied|wandelen|walking|lopen)',text))
    minutes=int(walking.group(1)) if walking else None
    nearby=bool(re.search(r'(?:nabij|vlak bij|dicht bij|proche de|près de|pres de|à deux pas de|a deux pas de)\s*(?:het|la|de|du)?\s*'+place,text))
    return metres,minutes,nearby


def add_beach_distance(row):
    if row.get('beachDistanceBasis')=='straight-line-estimate':
        row.pop('beachDistanceM',None)
    metres,minutes,nearby=stated_proximity((row.get('title') or '')+' '+(row.get('summary') or ''))
    if metres is not None or minutes is not None:
        if metres is not None:row['beachDistanceM']=metres
        if minutes is not None:row['beachWalkMinutes']=minutes
        row['beachDistanceBasis']='listing-text'
    else:
        resolve_property_location(row)
        pair=_coastal_pair(row.get('latitude'),row.get('longitude'))
        result=distance_to_beach(*pair) if pair and _area_pair_ok(row,pair) else None
        if result:
            row['beachDistanceM']=result[0]
            row.pop('beachWalkMinutes',None)
            row['beachDistanceBasis']='straight-line-estimate'
    if nearby:row['beachProximityClaim']=True
    return row
