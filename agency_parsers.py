"""Small standard-library parsers shared by public agency catalogues."""
from html.parser import HTMLParser
from urllib.parse import urljoin,urlsplit,parse_qsl,urlunsplit,urlencode
import re,json,html,hashlib
from model import COASTAL_AREAS,valid_photos,number_or_none,extract_features

VOID={'img','input','br','hr','meta','link','source','area','base','embed','param','wbr','col'}
class Node:
    def __init__(self,tag='',attrs=None,parent=None):self.tag=tag;self.attrs={k:v or "" for k,v in (attrs or [])};self.parent=parent;self.children=[]
    def all(self):
        for c in self.children:
            if isinstance(c,Node):yield c;yield from c.all()
    def text(self):return ' '.join(' '.join(c.text() if isinstance(c,Node) else c for c in self.children).split())
    def has(self,cls):return cls in self.attrs.get('class','').split()
    def find(self,cls):return next((n for n in self.all() if n.has(cls)),None)
class Tree(HTMLParser):
    def __init__(self,page):super().__init__(convert_charrefs=True);self.root=Node();self.current=self.root;self.feed(page)
    def handle_starttag(self,tag,attrs):
        node=Node(tag,attrs,self.current);self.current.children.append(node)
        if tag not in VOID:self.current=node
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs);self.handle_endtag(tag)
    def handle_endtag(self,tag):
        n=self.current
        while n.parent:
            if n.tag==tag:self.current=n.parent;return
            n=n.parent
    def handle_data(self,data):
        if self.current.tag not in ('script','style'):self.current.children.append(data)

def clean(s):return ' '.join(html.unescape(re.sub('<[^>]*>',' ',str(s or ''))).split())
def amount(s):
    s=re.sub(r'[^\d,.]','',str(s or ''))
    if re.fullmatch(r'\d{1,3}(?:[.,]\d{3})+',s):s=s.replace('.','').replace(',','')
    elif ',' in s:s=s.replace('.','').replace(',','.')
    return number_or_none(s)

def identity(site,url):return 'agency-'+re.sub('[^a-z0-9]+','-',urlsplit(site['website']).hostname.lower())+'-'+hashlib.sha256(url.encode()).hexdigest()[:14]
def brand(site,url):return {'id':identity(site,url),'source':site['name'],'sourceType':'agency-site','agencyName':site['name'],'agencyLogo':site.get('logo'),'agencyWebsite':site['website'],'agencyDomain':urlsplit(site['website']).hostname.removeprefix('www.'),'url':url}
def kind(value):
    value=value.lower()
    if re.search(r'appart|apartment|studio|penthouse|duplex|loft|flat|rez-de-chauss',value):return 'Apartment'
    if re.search(r'maison|house|villa|huis|woning|bungalow|vissershuis|bel-étage|bel-etage',value):return 'House'
    return None

def parse_catalogue(page,page_url,mode,site):
    tree=Tree(page).root;rows={};route=('a-louer','location','te-huur','rent') if mode=='rent' else ('a-vendre','vente','te-koop','tekoop','sale','buy')
    detail_route=route if mode=='rent' else (*route,'/nl/aanbod/','/nl-be/detail/')
    for node in tree.all():
        # These containers have one property each, not a whole results grid.
        card=any(node.has(c) for c in ('gallcell','estate-card','card-T11-estate-new','property_listing','estate_summary','pand-wrapper','artPub','card-body','listing_box','property','estate-item','property-item','cta--property','node--property--teaser','aanbod-grid-item','card--pub'))
        if not card and node.tag=='a':
            href=node.attrs.get('href') or ''
            card=bool(any(w in href.lower() for w in detail_route) and len(node.text())>25 and ('€' in node.text() or '&euro;' in node.text()) and (kind(href+' '+node.text()) or node.has('aanbod-grid-item')))
        if not card:continue
        nodes=[node,*node.all()];links=[n.attrs['href'] for n in nodes if n.tag=='a' and n.attrs.get('href')]
        if node.tag=='a' and node.attrs.get('href'):links.insert(0,node.attrs['href'])
        href=next((u for u in links if any(w in u.lower() for w in detail_route)),None)
        if not href:continue
        if mode!='rent' and re.search(r'optie[-_ ]koop|in[-_ ]optie',href,re.I):continue
        if mode!='rent' and (re.search(r'handelsruimte|handelspand|bedrijfsvastgoed|/kantoor/|/horeca/|bouwgrond',href,re.I) or re.search(r'/(?:garage|parking|staanplaats)(?:/|-)',href,re.I)):continue
        url=urljoin(page_url,href)
        if urlsplit(url).hostname!=urlsplit(page_url).hostname:continue
        body=node.text();ptype=kind(href) or kind(body)
        if not ptype and node.has('aanbod-grid-item'):continue
        if not ptype:continue
        flags=' '.join(n.text() for n in nodes if any(w in n.attrs.get('class','').lower() for w in ('flag','banner','status','ribbon')))
        if re.search(r'\b(?:loué|vendu|verhuurd|verkocht|option|sold|rented)\b',flags,re.I):continue
        if re.search(r'\b(?:Verkocht|In optie|Vendu|Sous option)\b',body[:45],re.I):continue
        def cls(c):
            v=node.find(c);return v.text() if v else ''
        price_text=cls('estate-card__text-details-price') or cls('listing_unit_price_wrapper')
        if not price_text:
            price_pattern=r'(\d{1,3}(?:[.,\s\u202f]\d{3})+|\d{4,8}|\d{1,3})'
            leading=re.search(r'€\s*'+price_pattern,body)
            trailing=re.search(price_pattern+r'\s*€',body) if not leading else None
            price_text=leading[1] if leading else trailing[1] if trailing else ''
        price=amount(price_text)
        if price is None:continue
        images=[n for n in nodes if n.tag=='img'];photos=[]
        for n in images:
            u=n.attrs.get('data-src') or n.attrs.get('src')
            if u and not re.search(r'icon|peb|epc|logo|\.svg',u,re.I):photos.append(urljoin(page_url,u))
        for n in nodes:
            bg=re.search(r"background-image\s*:\s*url\(['\"]?(.*?)['\"]?\)",n.attrs.get('style',''),re.I)
            if bg and not re.search(r'icon|peb|epc|logo|\.svg',bg[1],re.I):photos.append(urljoin(page_url,bg[1]))
        city=cls('city') or cls('estate-card__text') or cls('property_location_image')
        postal=re.search(r'(?<!\d)([1-9]\d{3})[- /]',href+' '+body)
        if site.get('coastal') and postal and not postal[1].startswith('8'):postal=None
        if not city:
            m=re.search(r'/(([1-9]\d{3})-[^/]+)/\d+',href)
            if m:city=m[1].replace('-',' ')
        if not city:
            # New custom cards often put the locality in their heading.
            city=next((n.text() for n in nodes if n.tag in ('h2','h3') and re.search(r'\b[1-9]\d{3}\b',n.text())), '')
        if not city:
            m=re.search(r'\b([1-9]\d{3})\s+([A-ZÀ-Ý][\wÀ-ÿ .’\-]+?)(?=\s+(?:Chambres|Salles|Garage|Surface)\b|$)',body)
            if m:city=m[1]+' '+m[2].strip()
        if not city:
            places=(*COASTAL_AREAS,'Oostduinkerke','Westende','Heist-aan-Zee','Wenduine')
            city=next((place for place in places if re.search(r'\b'+re.escape(place)+r'\b',body,re.I)), '')
        if len(city)>60:
            m=re.search(r'\b([1-9]\d{3})\s+([A-Za-zÀ-ÿ-]+)',city)
            city=m[1]+' '+m[2] if m else next((place for place in (*COASTAL_AREAS,'Oostduinkerke','Westende','Heist-aan-Zee','Wenduine') if re.search(r'\b'+re.escape(place)+r'\b',city,re.I)), '')
        if not city:continue
        postal_code=postal[1] if postal else None
        if site.get('coastal') and not postal_code:
            coastal_codes={'De Panne':'8660','Koksijde':'8670','Oostduinkerke':'8670',
                           'Nieuwpoort':'8620','Middelkerke':'8430','Westende':'8434',
                           'Oostende':'8400','Bredene':'8450','De Haan':'8420','Wenduine':'8420',
                           'Blankenberge':'8370','Zeebrugge':'8380','Knokke-Heist':'8300','Heist-aan-Zee':'8301'}
            postal_code=coastal_codes.get(city)
        area_match=re.search(r'([\d.,]+)\s*m[²2]',body)
        beds=None;baths=None
        for n in nodes:
            marker=str(n.attrs)
            if n.tag in ('img','i') and re.search(r'bedrooms|fa-bed\b',marker):
                m=re.search(r'\d+',n.parent.text());beds=int(m[0]) if m else beds
            if n.tag in ('img','i') and re.search(r'bathrooms|fa-bath\b',marker):
                m=re.search(r'\d+',n.parent.text());baths=int(m[0]) if m else baths
        if beds is None:
            m=re.search(r'(\d+)\s*(?:chambres?|ch\.|slaapkamers?|bedrooms?)',body,re.I);beds=int(m[1]) if m else (0 if 'studio' in body.lower() else None)
        title=next((n.text() for n in nodes if n.tag in ('h2','h3','h4')),None) or next((html.unescape(n.attrs.get('alt','')).split(' - ')[0] for n in images if kind(n.attrs.get('alt',''))),None) or ('Appartement' if ptype=='Apartment' else 'Maison')
        energy=' '.join(' '.join(str(v) for v in n.attrs.values()) for n in nodes if re.search(r'peb|epc|energielabel|energieklasse|energy.class',str(n.attrs),re.I))
        row={**brand(site,url),'transaction':mode,'title':title,'propertyType':ptype,'location':((postal_code+' ') if postal_code and postal_code not in city else '')+city,'postalCode':postal_code,'price':price,'area':amount(area_match[1]) if area_match else None,'bedrooms':beds,'bathrooms':baths,'fees':None,'summary':body[:700],'photos':valid_photos(photos),'energyText':energy+' '+body[:1800],'publicationDate':None}
        if url not in rows or len(row['photos'])>len(rows[url]['photos']):rows[url]=row
    return list(rows.values())

def structured_detail(page,url,mode,site):
    rows=[]
    for block in re.findall(r'<script[^>]*type=["\']application/ld(?:\+|&#x2B;|&#43;)json["\'][^>]*>(.*?)</script>',page,re.I|re.S):
        try:stack=[json.loads(html.unescape(block))]
        except ValueError:continue
        while stack:
            n=stack.pop()
            if isinstance(n,list):stack.extend(n);continue
            if not isinstance(n,dict):continue
            stack.extend(v for v in n.values() if isinstance(v,(list,dict)))
            typ=n.get('@type');typ=typ if isinstance(typ,list) else [typ]
            if not set(typ)&{'Apartment','House','Residence','RealEstateListing','Product'}:continue
            row_url=urljoin(url,str(n.get('url') or url))
            if urlsplit(row_url).path.rstrip('/')!=urlsplit(url).path.rstrip('/'):continue
            desc=clean(n.get('description'));title=n.get('name') or '';about=n.get('about') or n;ptype=kind(str(about.get('@type'))+' '+title+' '+url)
            if not ptype:continue
            offers=n.get('offers') or {};offers=offers[0] if isinstance(offers,list) and offers else offers
            if not isinstance(offers,dict):continue
            if any(w in str(offers.get('availability','')).lower() for w in ('soldout','discontinued','outofstock')):continue
            addr=about.get('address') or n.get('address') or {};addr=addr if isinstance(addr,dict) else {}
            price=number_or_none(offers.get('price'));area=about.get('floorSize') or {};area=area.get('value') if isinstance(area,dict) else area
            photos=n.get('image') or about.get('image') or [];photos=photos if isinstance(photos,list) else [photos]
            energy_fields=[(k,about.get(k) or n.get(k)) for k in ('energyEfficiencyClass','energyRating','energyClass','energielabel','epc','peb')]
            rows.append({**brand(site,row_url),'transaction':mode,'title':title,'propertyType':ptype,'summary':desc[:1800],'price':price,'fees':None,'area':number_or_none(area),'bedrooms':number_or_none(about.get('numberOfBedrooms')),'bathrooms':number_or_none(about.get('numberOfBathroomsTotal')),'streetAddress':addr.get('streetAddress'),'postalCode':addr.get('postalCode'),'location':' '.join(str(addr.get(k) or '') for k in ('postalCode','addressLocality')).strip(),'photos':valid_photos([urljoin(url,p.get('url') or p.get('contentUrl') or '') if isinstance(p,dict) else urljoin(url,p) for p in photos if p]),'features':extract_features(desc),'energyRating':next((v for k,v in energy_fields if v),None),'energyText':desc+' '+' '.join(f'{k} {v}' for k,v in energy_fields if v),'publicationDate':n.get('datePublished')})
    return rows

def pagination(page,url):
    tree=Tree(page).root;out=[]
    current_query=dict(parse_qsl(urlsplit(url).query,keep_blank_values=True))
    current_page=next((int(current_query[k]) for k in ('page','pageindex','d_page') if current_query.get(k,'').isdigit()),1)
    for node in tree.all():
        if node.tag not in ('a','link') or not node.attrs.get('href'):continue
        target=urljoin(url,node.attrs['href']);parent=node.parent
        parts=urlsplit(target);query=dict(parse_qsl(parts.query,keep_blank_values=True))
        if node.has('yw-dropdown-item') or 'id' in query or 'sort' in query or query.get('view')=='detail':continue
        target_page=next((int(query[k]) for k in ('page','pageindex','d_page') if query.get(k,'').isdigit()),None)
        if target_page is not None and target_page<=current_page:continue
        is_page='next' in node.attrs.get('rel','') or node.has('next-page') or node.has('next') or node.has('page-numbers') or node.has('yw-page-btn')
        while parent and not is_page:
            is_page=any('pagination' in c for c in parent.attrs.get('class','').split());parent=parent.parent
        if not is_page and parts.path==urlsplit(url).path:is_page=target_page is not None
        if is_page and parts.hostname==urlsplit(url).hostname:
            canonical=urlunsplit((parts.scheme,parts.netloc,parts.path,urlencode(sorted(query.items())),''))
            if canonical not in out:out.append(canonical)
    return out
