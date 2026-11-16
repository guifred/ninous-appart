"""Bounded collection from public coastal agency sale catalogues.

Each request is checked against the site's robots.txt by collect_site. A
configured source counts as working only after a live run parses listings.
"""
from brussels_agencies import collect_site, restricted_agency_domains
from agency_discovery import normalized_domain, _robots, _fetch
from agency_parsers import Tree, amount, brand, kind
from model import valid_photos
from beach_distance import extract_coordinates, add_beach_distance
from energy_detail import extract_detail_energy
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor
from xml.etree import ElementTree
import re
import time

SOURCES = (
    ('Agentschap Bécue', 'https://www.becue.be', 'https://www.becue.be/te-koop'),
    ('Immo Cattaert', 'https://www.immocattaert.be', 'https://www.immocattaert.be/te-koop'),
    ('Immo De Panne', 'https://www.immodepanne.be', 'https://www.immodepanne.be/nl-be/te-koop'),
    ('Caenen', 'https://www.caenen.be', 'https://www.caenen.be/nl/te-koop'),
    ('Immo Angelo', 'https://www.immoangelo.be', 'https://www.immoangelo.be/nl/te-koop'),
    ('Immo Padiva', 'https://www.immopadiva.be', 'https://www.immopadiva.be/te-koop'),
    ('Buro-M', 'https://buro-m.be', 'https://buro-m.be/nl/te-koop'),
    ('Dewaele Nieuwpoort', 'https://www.dewaele.com', 'https://www.dewaele.com/nl/te-koop/8620-nieuwpoort'),
    ('Euro Immo', 'https://euroimmo.be', 'https://euroimmo.be/kopen/te-koop/'),
    ('Century 21 Sea Port', 'https://www.century21seaport.be', 'https://www.century21seaport.be/aanbod/te-koop'),
    ('Immo Group-S', 'https://www.immogroup-s.be', 'https://www.immogroup-s.be/nl/te-koop'),
    ('Immo Maritiem', 'https://immo-maritiem.be', 'https://immo-maritiem.be/nl/te-koop'),
    ('Portus', 'https://www.portus.be', 'https://www.portus.be/nl/te-koop'),
    ('Vlaemynck', 'https://www.vlaemynck.be', 'https://www.vlaemynck.be/te-koop/nieuwpoort'),
    ('Residentie Vastgoed Nieuwpoort', 'https://www.residentievastgoed.be', 'https://www.residentievastgoed.be/te-koop'),
    ('ERA Servimo Nieuwpoort', 'https://www.era.be', 'https://www.era.be/nl/te-koop/nieuwpoort'),
    ('Immo Eecke', 'https://www.eecke.be', 'https://www.eecke.be/nl/vastgoed/te-koop'),
    ('Westland Vastgoed', 'https://westlandvastgoed.be', 'https://westlandvastgoed.be/nl/te-koop'),
    ('Agence Nieuwpoort', 'https://www.agencenieuwpoort.be', 'https://www.agencenieuwpoort.be/nl/te-koop'),
    ('Immo Beguin Nieuwpoort', 'https://www.immobeguin.be', 'https://www.immobeguin.be/te-koop/'),
    ('Immo de Kaai', 'https://immodekaai.be', 'https://immodekaai.be/nl/te-koop'),
)

def collect_coast_agencies(criteria):
    restricted=restricted_agency_domains()
    def collect_one(source):
        name,website,catalogue=source
        try:
            if normalized_domain(website) in restricted:
                return [],{'source':name,'transaction':'coast','ok':False,'found':0,
                           'reason':'Published site terms require prior permission.'}
            if name=='Immo Padiva':
                return collect_padiva(criteria,website,catalogue)
            if name=='Euro Immo':
                return collect_euroimmo(criteria,website,catalogue)
            if name=='Immo Beguin Nieuwpoort':
                return collect_beguin(criteria,website)
            site={'name':name,'website':website,'coastal':True,'samples':{'sale':[{'url':catalogue}]}}
            found,status=collect_site(site,'sale',criteria,max_pages=45,max_details=120)
            status['transaction']='coast'
            return found,status
        except Exception as exc:
            return [],{'source':name,'domain':normalized_domain(website),'transaction':'coast',
                       'ok':False,'found':0,'partial':True,'reason':str(exc)[:200]}
    rows=[];results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for found,status in pool.map(collect_one,SOURCES):
            rows.extend(found);results.append(status)
    return rows,results


def parse_beguin_detail(page,url,website):
    """Parse Immo Beguin's public detail, excluding related-property cards."""
    from scraper import parse_detail_photos
    from beach_distance import listing_description
    root=Tree(page).root
    metadata={node.attrs.get('property'):node.attrs.get('content') for node in root.all()
              if node.tag=='meta' and node.attrs.get('property')}
    title=metadata.get('og:title') or ''
    ptype=kind(url+' '+title)
    if not ptype:return None
    address=next((node.attrs.get('value','') for node in root.all()
                  if node.tag=='input' and node.attrs.get('name')=='propertyAddress'),'')
    match=re.search(r'\b(8\d{3})\s+([^,]+)',address)
    if not match:return None
    postal,city=match.group(1),match.group(2).strip().title()
    text=root.text()
    price_match=re.search(r'€\s*([\d.,]+)',text)
    price=amount(price_match.group(1)) if price_match else None
    if price is None:return None
    area=re.search(r'Bewoonbare oppervlakte\s*([\d.,]+)\s*m[²2]',text,re.I)
    beds=re.search(r'Aantal slaapkamers\s*(\d+)',text,re.I)
    photos=parse_detail_photos(page,url)
    if not photos and metadata.get('og:image'):photos=[metadata['og:image']]
    row={**brand({'name':'Immo Beguin Nieuwpoort','website':website},url),
         'transaction':'coast','title':title,'propertyType':ptype,
         'location':postal+' '+city,'postalCode':postal,
         'streetAddress':address.split(',')[0].strip(),'price':price,
         'area':amount(area.group(1)) if area else None,
         'bedrooms':int(beds.group(1)) if beds else None,
         'summary':listing_description(page)[:1800] or metadata.get('og:description',''),
         'photos':valid_photos(photos),'energyRating':extract_detail_energy(page)}
    coordinates=extract_coordinates(page)
    if coordinates:row['latitude'],row['longitude']=coordinates
    add_beach_distance(row)
    return row


def collect_beguin(criteria,website):
    """Use the agency's public sitemap to avoid crawling its national catalogue."""
    from scraper import source_area_matches
    status={'source':'Immo Beguin Nieuwpoort','domain':normalized_domain(website),
            'transaction':'coast','ok':False,'found':0,'pages':0,'details':0,'partial':False}
    rules={};last=0;rows=[]
    def read(url):
        nonlocal last
        if normalized_domain(url)!=normalized_domain(website):raise ValueError('Cross-domain link')
        allowed,reason=_robots(url,rules)
        if not allowed:raise PermissionError('robots: '+reason)
        delay=1.1-(time.monotonic()-last)
        if delay>0:time.sleep(delay)
        page,_=_fetch(url);last=time.monotonic();return page
    try:
        index=ElementTree.fromstring(read(website+'/sitemaps-1-sitemap.xml'));status['pages']+=1
        sitemaps=[node.text for node in index.iter() if node.tag.endswith('loc') and node.text
                  and 'section-properties-1-sitemap-' in node.text][:12]
        urls=[]
        for sitemap in sitemaps:
            document=ElementTree.fromstring(read(sitemap));status['pages']+=1
            urls.extend(node.text for node in document.iter() if node.tag.endswith('loc') and node.text
                        and '/te-koop/' in node.text and re.search(r'/8\d{3}-[^/]+/(?:appartement|studio|woning|huis|villa)/',node.text,re.I))
        for url in dict.fromkeys(urls):
            locality=re.search(r'/([8]\d{3})-([^/]+)/',url)
            if not locality or not source_area_matches(criteria,locality[1]+' '+locality[2].replace('-',' ')):continue
            if status['details']>=120:status['partial']=True;break
            try:
                page=read(url);status['details']+=1
                row=parse_beguin_detail(page,url,website)
                wanted=(criteria.get('property') or 'Apartment').lower()
                if row and row['propertyType'].lower() in wanted:rows.append(row)
            except Exception as exc:
                status['partial']=True;status['reason']=str(exc)[:180]
        status['ok']=status['pages']>1
    except Exception as exc:
        status['partial']=True;status['reason']=str(exc)[:180]
    status['found']=len(rows)
    return rows,status

def collect_euroimmo(criteria,website,catalogue):
    """Euro Immo omits the property type from most catalogue cards."""
    from scraper import source_area_matches
    site={'name':'Euro Immo','website':website}
    status={'source':site['name'],'domain':normalized_domain(website),'transaction':'coast',
            'ok':False,'found':0,'pages':0,'details':0,'partial':False}
    rules={};last=0;rows={}
    def read(url):
        nonlocal last
        if normalized_domain(url)!=normalized_domain(website):raise ValueError('Cross-domain link')
        allowed,reason=_robots(url,rules)
        if not allowed:raise PermissionError('robots: '+reason)
        delay=1.1-(time.monotonic()-last)
        if delay>0:time.sleep(delay)
        page,_=_fetch(url);last=time.monotonic();return page
    def field(root,cls):
        node=root.find(cls)
        return node.text() if node else ''
    try:
        root=Tree(read(catalogue)).root;status['pages']=1
        cards=[n for n in root.all() if n.tag=='a' and n.has('aanbod-grid-item') and re.search(r'/tekoop/detail/\d+/?$',n.attrs.get('href',''))]
        status['partial']=len(cards)>120
        for card in cards[:120]:
            url=urljoin(catalogue,card.attrs['href'])
            if url in rows:continue
            try:
                detail_html=read(url);detail=Tree(detail_html).root;status['details']+=1
                title=field(detail,'panddetail-description-title') or field(detail,'aankoopraming-cost-type')
                ptype=kind(title)
                wanted=(criteria.get('property') or 'Apartment').lower()
                if not ptype or ptype.lower() not in wanted:continue
                address=field(detail,'panddetail-adres-text')
                city=address.rsplit(',',1)[-1].strip()
                location=('8620 ' if city.lower()=='nieuwpoort' else '')+city
                if not source_area_matches(criteria,location):continue
                price=amount(field(detail,'panddetail-prijs'))
                if price is None:continue
                description=field(detail,'panddetail-description-text')
                beds=re.search(r'(\d+)\s*slaapkamer',title+' '+description,re.I)
                photo=next((n.attrs.get('data-src') or n.attrs.get('src') for n in card.all() if n.tag=='img' and (n.attrs.get('data-src') or n.attrs.get('src','').startswith('https://'))),None)
                from scraper import parse_detail_photos
                gallery=parse_detail_photos(detail_html,url)
                rows[url]={**brand(site,url),'transaction':'coast','title':title,'propertyType':ptype,
                           'location':location,'postalCode':'8620' if city.lower()=='nieuwpoort' else None,
                           'streetAddress':address.rsplit(',',1)[0].strip() if ',' in address else None,
                           'price':price,'bedrooms':int(beds[1]) if beds else None,
                           'summary':description[:1200],'photos':valid_photos(gallery or ([urljoin(url,photo)] if photo else [])),
                           'energyRating':extract_detail_energy(detail_html,url)}
                coordinates=extract_coordinates(detail_html)
                if coordinates:
                    rows[url]['latitude'],rows[url]['longitude']=coordinates
                    add_beach_distance(rows[url])
            except Exception as exc:
                status['partial']=True;status['reason']=str(exc)[:180]
        status['ok']=status['details']>0
        if not status['ok']:status['reason']='No public property detail could be read.'
    except Exception as exc:
        status['partial']=True;status['reason']=str(exc)[:180]
    status['found']=len(rows)
    return list(rows.values()),status

def collect_padiva(criteria,website,catalogue):
    """Padiva's public teasers link to detail pages without structured data."""
    from scraper import source_area_matches
    site={'name':'Immo Padiva','website':website}
    status={'source':site['name'],'domain':normalized_domain(website),'transaction':'coast',
            'ok':False,'found':0,'pages':0,'details':0,'partial':False}
    rules={};last=0;rows=[]
    def read(url):
        nonlocal last
        if normalized_domain(url)!=normalized_domain(website):raise ValueError('Cross-domain link')
        allowed,reason=_robots(url,rules)
        if not allowed:raise PermissionError('robots: '+reason)
        delay=1.1-(time.monotonic()-last)
        if delay>0:time.sleep(delay)
        page,_=_fetch(url);last=time.monotonic();return page
    def by_class(root,name):
        node=next((n for n in root.all() if n.has(name)),None)
        return node.text() if node else ''
    try:
        page=read(catalogue);status['pages']=1;root=Tree(page).root
        links=[]
        for card in root.all():
            if not card.has('property-teaser'):continue
            link=next((n.attrs.get('href') for n in card.all() if n.tag=='a' and n.attrs.get('href','').startswith('/te-koop/')),None)
            if link:
                url=urljoin(website,link)
                if url not in links:links.append(url)
        status['partial']=len(links)>30
        for url in links[:30]:
            try:
                detail=read(url);status['details']+=1;detail_root=Tree(detail).root
                description=by_class(detail_root,'field--name-body')
                meta=re.search(r'<meta name="description" content="([^"]+)',detail,re.I)
                description=(meta[1] if meta else description)[:1200]
                ptype=kind(description+' '+url)
                wanted=(criteria.get('property') or 'Apartment').lower()
                if not ptype or ptype.lower() not in wanted:continue
                address=by_class(detail_root,'property--detail__address')
                info=by_class(detail_root,'property--detail__general-info')
                city=re.search(r'\b([1-9]\d{3})\s+([A-Za-zÀ-ÿ-]+)',address)
                location=city[0] if city else ''
                if not source_area_matches(criteria,location):continue
                price=amount(by_class(detail_root,'property--detail__price'))
                if price is None:continue
                area=re.search(r'Bewoonbare oppervlakte\s*([\d.,]+)',info,re.I)
                beds=re.search(r'Slaapkamers\s*(\d+)',info,re.I)
                title=by_class(detail_root,'property--detail__title') or ('Appartement' if ptype=='Apartment' else 'Maison')
                from scraper import parse_detail_photos
                photos=valid_photos(parse_detail_photos(detail,url) or [urljoin(url,n.attrs['src']) for n in detail_root.all() if n.tag=='img' and 'property-popup' in n.attrs.get('class','') and n.attrs.get('src')])
                rows.append({**brand(site,url),'transaction':'coast','title':title,'propertyType':ptype,
                             'location':location,'postalCode':city[1] if city else None,'streetAddress':address.split(location)[0].strip() if location else None,
                             'price':price,'area':amount(area[1]) if area else None,'bedrooms':int(beds[1]) if beds else None,
                             'summary':description,'photos':photos,'energyRating':extract_detail_energy(detail,url)})
                coordinates=extract_coordinates(detail)
                if coordinates:
                    rows[-1]['latitude'],rows[-1]['longitude']=coordinates
                    add_beach_distance(rows[-1])
            except Exception as exc:
                status['partial']=True;status['reason']=str(exc)[:180]
        status['ok']=status['details']>0
        if not status['ok']:status['reason']='No public property detail could be read.'
    except Exception as exc:
        status['partial']=True;status['reason']=str(exc)[:180]
    status['found']=len(rows)
    return rows,status
