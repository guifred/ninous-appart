"""Approximate proximity to the Belgian beach from published listing coordinates."""
import html
import json
import math
import re
from urllib.parse import urlencode
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


def resolve_property_location(row):
    """Locate an identifiable residence or numbered Flemish street address."""
    if _coastal_pair(row.get('latitude'), row.get('longitude')):return row
    words=' '.join(str(row.get(k) or '') for k in ('title','summary','streetAddress')).lower()
    city=str(row.get('location') or '')
    for name,(address,municipality,lat,lon) in KNOWN_RESIDENCES.items():
        if name in words and municipality.lower() in city.lower():
            row['latitude'],row['longitude']=lat,lon
            row['beachLocationBasis']='verified-residence'
            return row
    address=str(row.get('streetAddress') or '').strip()
    if not address or not re.search(r'\b\d+[a-zA-Z]?\b',address) or not city:return row
    query=address+', '+city
    if query not in _GEOCODE_CACHE:
        try:
            url='https://geo.api.vlaanderen.be/geolocation/v4/Location?'+urlencode({'q':query})
            request=Request(url,headers={'User-Agent':'NinousAppartementFinder/0.1 (personal real-estate search)'})
            with urlopen(request,timeout=2) as response:
                data=json.load(response)
            candidates=data.get('LocationResult') or []
            match=next((x for x in candidates if re.search(r'\b'+re.escape(str(x.get('Housenumber') or ''))+r'\b',address,re.I) and str(x.get('Municipality') or '').lower() in city.lower()),None)
            position=(match or {}).get('Location') or {}
            _GEOCODE_CACHE[query]=_coastal_pair(position.get('Lat_WGS84'),position.get('Lon_WGS84'))
        except (OSError,ValueError,TypeError):_GEOCODE_CACHE[query]=None
    pair=_GEOCODE_CACHE[query]
    if pair:
        row['latitude'],row['longitude']=pair
        row['beachLocationBasis']='verified-address'
    return row


def _coastal_pair(lat, lon):
    try:
        lat=float(lat);lon=float(lon)
    except (ValueError,TypeError):return None
    return (lat,lon) if 50.95<=lat<=51.48 and 2.48<=lon<=3.48 else None


def extract_coordinates(page):
    """Use property map attributes or property-specific JSON-LD, never office maps."""
    for tag in re.findall(r'<[^>]+>',page):
        attrs=dict((key.lower(),html.unescape(value)) for key,value in re.findall(r'([\w:-]+)=["\']([^"\']+)["\']',tag))
        lat=attrs.get('data-lat') or attrs.get('data-latitude')
        lon=attrs.get('data-long') or attrs.get('data-lng') or attrs.get('data-lon') or attrs.get('data-longitude')
        pair=_coastal_pair(lat,lon)
        if pair:return pair
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
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
    return None


def listing_description(page):
    """Read a property's own description from structured data or page metadata."""
    for block in re.findall(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
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
    metres,minutes,nearby=stated_proximity((row.get('title') or '')+' '+(row.get('summary') or ''))
    if metres is not None or minutes is not None:
        if metres is not None:row['beachDistanceM']=metres
        if minutes is not None:row['beachWalkMinutes']=minutes
        row['beachDistanceBasis']='listing-text'
    else:
        resolve_property_location(row)
        result=distance_to_beach(row.get('latitude'),row.get('longitude'))
        if result:
            row['beachDistanceM']=result[0]
            row.pop('beachWalkMinutes',None)
            row['beachDistanceBasis']='straight-line-estimate'
    if nearby:row['beachProximityClaim']=True
    return row
