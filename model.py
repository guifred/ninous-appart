"""Shared schemas, matching, normalization and renovation planning estimates."""
from __future__ import annotations

from datetime import datetime, date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import html
import json
import os
import re
import tempfile
import unicodedata
from collections import deque
from urllib.parse import urlparse

TZ = ZoneInfo('Europe/Brussels')
MODES = ('rent', 'sale')
FEATURES = {
    'terrace': [(r'\bterrace\b', r'\bterrasse\b', r'\bterras\b'), (r'\bno terrace\b', r'\bwithout (?:a )?terrace\b', r'\bpas de terrasse\b', r'\bsans terrasse\b', r'\bgeen terras\b', r'\bzonder terras\b')],
    'balcony': [(r'\bbalcony\b', r'\bbalcon\b', r'\bbalkon\b'), (r'\bno balcony\b', r'\bwithout (?:a )?balcony\b', r'\bpas de balcon\b', r'\bsans balcon\b', r'\bgeen balkon\b', r'\bzonder balkon\b')],
    'garden': [(r'\bgarden\b', r'\bjardin\b', r'\btuin\b'), (r'\bno garden\b', r'\bwithout (?:a )?garden\b', r'\bpas de jardin\b', r'\bsans jardin\b', r'\bgeen tuin\b', r'\bzonder tuin\b')],
    'parking': [(r'\bparking\b', r'\bgarage\b', r'\bcar park\b', r'\bstationnement\b', r'\bparkeerplaats\b'), (r'\bno parking\b', r'\bwithout parking\b', r'\bpas de parking\b', r'\bsans parking\b', r'\bgeen parking\b', r'\bzonder parkeerplaats\b')],
    'lift': [(r'\blift\b', r'\belevator\b', r'\bascenseur\b', r'\blift\b'), (r'\bno (?:lift|elevator)\b', r'\bwithout (?:an? )?(?:lift|elevator)\b', r'\bwithout (?:a )?lift\b', r'\bsans ascenseur\b', r"\bpas d[’']ascenseur\b", r'\bgeen lift\b')],
    'cellar': [(r'\bcellar\b', r'\bcave\b', r'\bkelder\b'), (r'\bno cellar\b', r'\bwithout (?:a )?cellar\b', r'\bsans cave\b', r'\bpas de cave\b', r'\bgeen kelder\b')],
    'furnished': [(r'\bfurnished\b', r'\bmeubl[eé]\b', r'\bgemeubileerd\b'), (r'\bunfurnished\b', r'\bunmeubl[eé]\b', r'\bnon[- ]meubl[eé]\b', r'\bonbemeubeld\b', r'\bniet gemeubileerd\b')],
    'accessible': [(r'\bwheelchair accessible\b', r'\baccessible aux personnes? à mobilité réduite\b', r'\brolstoeltoegankelijk\b'), (r'\bnot accessible\b', r'\binaccessible\b', r'\bniet toegankelijk\b')],
    'petsAllowed': [(r'\bpets? allowed\b', r'\banimaux accept[eé]s\b', r'\bhuisdieren toegelaten\b'), (r'\bno pets?\b', r'\banimaux non accept[eé]s\b', r'\bhuisdieren niet toegelaten\b')],
}

DEFAULT_RENT = {'areas':'', 'minBudget':'', 'maxBudget':'', 'budgetBasis':'rent', 'bedrooms':'', 'property':'Apartment', 'subtypes':[], 'minArea':'', 'maxArea':'', 'features':{}, 'furnished':'any', 'moveDate':'', 'mustHaves':'', 'energyRating':'any', 'floorMin':'', 'floorMax':'', 'publicationDays':'', 'sort':'relevance', 'nearby':True}
DEFAULT_SALE = {'areas':'', 'minPrice':'', 'maxPrice':'', 'maxPricePerM2':'', 'bedrooms':'', 'property':'Apartment', 'subtypes':[], 'minArea':'', 'maxArea':'', 'features':{}, 'construction':'any', 'condition':'any', 'occupancy':'any', 'maxCondoFees':'', 'renovationScope':'cosmetic', 'renovationRateLow':'', 'renovationRateHigh':'', 'maxRenovation':'', 'maxCombined':'', 'includeUnknownRenovation':False, 'contingencyPct':15, 'vatPct':21, 'energyRating':'any', 'floorMin':'', 'floorMax':'', 'sort':'relevance', 'publicationDays':'', 'nearby':True}


def norm(s):
    return re.sub(r'[^a-z0-9]+', ' ', ''.join(c for c in unicodedata.normalize('NFKD', str(s or '').lower()) if not unicodedata.combining(c))).strip()


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def parse_publication_date(value, now=None):
    """Parse only a value explicitly labelled as publication date; never infer from collection time."""
    if not value: return {'value':None,'uncertain':False}
    s=html.unescape(str(value)).strip(); now=now or datetime.now(TZ).date()
    try:
        d=datetime.fromisoformat(s.replace('Z','+00:00')).date(); return {'value':d.isoformat(),'uncertain':False}
    except ValueError: pass
    n=norm(s)
    m=re.search(r'(?:\b(\d+)\s+(?:day|days|jour|jours|dag|dagen)\s+ago\b|il y a\s+(\d+)\s+jours?|(?:geplaatst|published)\s+(\d+)\s+dagen? geleden|\b(\d+)\s+dagen? geleden)',n)
    if m:
        days=int(next(x for x in m.groups() if x))
        try:return {'value':(now-timedelta(days=days)).isoformat(),'uncertain':True}
        except OverflowError:return {'value':None,'uncertain':True}
    formats=('%d/%m/%Y','%d-%m-%Y','%Y-%m-%d','%d %B %Y','%d %b %Y')
    for fmt in formats:
        try:return {'value':datetime.strptime(s,fmt).date().isoformat(),'uncertain':False}
        except ValueError:pass
    months={'janvier':1,'février':2,'fevrier':2,'mars':3,'avril':4,'mai':5,'juin':6,'juillet':7,'août':8,'aout':8,'septembre':9,'octobre':10,'novembre':11,'décembre':12,'decembre':12,'januari':1,'februari':2,'maart':3,'april':4,'mei':5,'juni':6,'juli':7,'augustus':8,'september':9,'oktober':10,'november':11,'december':12}
    m=re.search(r'\b(\d{1,2})\s+([a-zéû]+)\s+(\d{4})\b',s.lower())
    if m and m.group(2) in months:
        try:return {'value':date(int(m.group(3)),months[m.group(2)],int(m.group(1))).isoformat(),'uncertain':False}
        except ValueError:pass
    return {'value':None,'uncertain':True}


def extract_features(text):
    n=norm(text); out={}
    for key,(positive,negative) in FEATURES.items():
        positive_hit=any(re.search(p,n) for p in positive)
        negative_hit=any(re.search(p,n) for p in negative)
        out[key]=False if negative_hit else True if positive_hit else None
    return out

def extract_energy_rating(value):
    """Read a Belgian EPC/PEB class from listing text or accessible image metadata."""
    text=str(value or '')
    patterns=(
        r'\b(?:epc|peb)(?:\s*[/&-]\s*(?:epc|peb))?\s*(?:(?:label|class|klasse|classe|rating|score)\s*)?[\s:=\-\[\]()]{0,10}([a-g])(?=[^a-z]|$)(\s*\+{1,2})?',
        r'\b(?:energy|energie)(?:[- _](?:label|class|klasse|rating|score))?\s*[:=\-\[]?\s*([a-g])(?=[^a-z]|$)(\s*\+{1,2})?',
        r'\b(?:classe\s+(?:énergétique|energetique)|energy\s+(?:class|label|rating)|energieklasse|energielabel)\s*[:=\-]?\s*([a-g])(?=[^a-z]|$)(\s*\+{1,2})?',
        r'\b(?:epc|peb|energy[-_ ](?:label|class)|energie[-_ ](?:label|klasse))[-_ /]+([a-g])\.(?:svg|png|jpe?g|webp)(?:\?|\b)',
    )
    for pattern in patterns:
        match=re.search(pattern,text,re.I)
        if match:
            rating=match.group(1).upper()
            return rating+((match.group(2) or '').strip() if match.lastindex and match.lastindex>=2 else '')
    direct=re.fullmatch(r'\s*([a-g])\s*(\+{1,2})?\s*',text,re.I)
    return direct.group(1).upper()+(direct.group(2) or '') if direct else None


def normalize_listing(row, mode, today=None, prior=None):
    today=today or datetime.now(TZ).date().isoformat(); prior=prior or {}
    row=dict(row); row['transaction']=mode
    parsed=urlparse(str(row.get('url') or ''))
    row['url']=str(row.get('url') or '') if parsed.scheme=='https' and parsed.netloc else ''
    row['id']=str(row.get('id') or (norm(row.get('source'))+'-'+re.sub(r'[^a-zA-Z0-9]+','-',str(row.get('url','')).rstrip('/').split('/')[-1]).lower()))
    row['price']=number_or_none(row.get('price')); row['fees']=number_or_none(row.get('fees')); row['area']=number_or_none(row.get('area')); row['bedrooms']=number_or_none(row.get('bedrooms'))
    row['photos']=valid_photos(row.get('photos') or [])
    row['features']={**extract_features((row.get('title') or '')+' '+(row.get('summary') or '')),**(row.get('features') or {})}
    text=norm((row.get('title') or '')+' '+(row.get('summary') or '')+' '+(row.get('location') or ''))
    row['condition']=row.get('condition') or next((label for terms,label in ((('to renovate','needs renovation','à rénover','à renover','à rafraîchir','te renoveren','renovatie nodig'),'renovation'),(('renovated','rénové','renove','gerenoveerd','refurbished'),'renovated'),(('good condition','bon état','bon etat','goede staat'),'good')) if any(norm(t) in text for t in terms)),None)
    row['construction']=row.get('construction') or ('new' if any(norm(t) in text for t in ('new build','new construction','neuf','nieuwbouw','nouvelle construction')) else 'existing' if any(norm(t) in text for t in ('existing property','existing building','bâtiment existant','batiment existant','bestaande woning')) else None)
    row['occupancy']=row.get('occupancy') or ('vacant' if any(norm(t) in text for t in ('vacant','libre à l acte','libre a l acte','vrij bij akte')) else 'occupied' if any(norm(t) in text for t in ('occupied','loué','loue','verhuurd','currently rented')) else None)
    energy_text=' '.join(str(row.get(k) or '') for k in ('energyRating','energyText','summary','title','location'))
    row['energyRating']=extract_energy_rating(energy_text)
    brussels_places=('brussels','bruxelles','woluwe','ixelles','schaerbeek','etterbeek','evere','uccle','auderghem','anderlecht','forest','ganshoren','jette','koekelberg','molenbeek','saint gilles','saint josse','sint agatha','watermael','berchem sainte')
    flemish_places=('flanders','vlaanderen','antwerp','antwerpen','gent','ghent','leuven','brugge','bruge','hasselt','mechelen','malines','kortrijk','courtrai','aalst','alost','oostende','ostend','genk','sint niklaas','turnhout','roeselare','waregem','tienen','vilvoorde','dendermonde')
    walloon_places=('wallonia','wallonie','wallon','liège','liege','namur','charleroi','mons','tournai','verviers','arlon','wavre','la louvière','bastogne','marche en famenne','nivelles','dinant','soignies','gembloux')
    region=('PEB · Bruxelles' if any(norm(x) in text for x in brussels_places) else 'EPC · Flandre' if any(norm(x) in text for x in flemish_places) else 'PEB · Wallonie' if any(norm(x) in text for x in walloon_places) else None)
    postal=re.sub(r'\D','',str(row.get('postalCode') or row.get('location') or ''))[:4]
    try:postal_number=int(postal)
    except (ValueError,TypeError):postal_number=None
    if postal_number and 1000<=postal_number<=1299:region='PEB · Bruxelles'
    elif postal_number and (1500<=postal_number<=3999 or 8000<=postal_number<=9999):region='EPC · Flandre'
    elif postal_number and (1300<=postal_number<=1499 or 4000<=postal_number<=7999):region='PEB · Wallonie'
    row['energyRegion']=row.get('energyRegion') or (region if row['energyRating'] else None)
    floor=re.search(r'\b(?:floor|étage|etage|verdieping)\s*[:#]?\s*(\d{1,2})\b',text,re.I)
    row['floor']=number_or_none(row.get('floor')) if row.get('floor') is not None else (int(floor.group(1)) if floor else None)
    pub=parse_publication_date(row.get('publicationDate'))
    old=prior.get(row['id'],{})
    row['firstDiscovered']=old.get('firstDiscovered') or row.get('firstDiscovered') or today
    row['publicationDate']=pub['value'] or row['firstDiscovered']
    row['publicationDateOrigin']='source' if pub['value'] else 'firstDiscovered'
    row['publicationDateUncertain']=pub['uncertain'] if pub['value'] else False
    row['lastObserved']=today
    row['sourceModified']=row.get('sourceModified') or None
    row['photos']=valid_photos(row.get('photos') or [])
    if mode=='sale':
        row['renovationOverride']=old.get('renovationOverride') or row.get('renovationOverride')
    return row


def number_or_none(value):
    if value is None or value=='': return None
    try:
        number=float(str(value).replace(',','.'))
        return int(number) if number.is_integer() else number
    except (ValueError,TypeError):return None


def valid_photos(values):
    result=[]
    if isinstance(values,str): values=[values]
    for url in values:
        if not isinstance(url,str):continue
        u=html.unescape(url.strip())
        parsed=urlparse(u)
        if parsed.scheme!='https' or not parsed.netloc:continue
        if re.search(r'logo|icon|avatar|placeholder|sprite|flag|badge|favicon|blank|no[-_]?image|nopic',u,re.I):continue
        if u not in result:result.append(u)
    return result[:12]


# Belgian 2025-26 published order-of-magnitude per-m² renovation bands; base references are excl. VAT.
RENOVATION_RATES={'ready':(0,250),'cosmetic':(400,800),'partial':(800,1500),'full':(1500,2500)}
RENOVATION_REFERENCE={'name':'Immolytics Belgium Renovation Cost Calculator','url':'https://www.immolytics.be/en/tools/calculateur-renovation','asOf':'2025-2026','bandsEURm2':{'ready':[0,250],'cosmetic':[400,800],'partial':[800,1500],'full':[1500,2500]},'note':'Belgian market-average bands. “Move-in ready” 0–250 €/m² is an editable application planning assumption, not a quoted published band. Other bands are scenarios, not quotes.'}
COMPONENT_REFERENCE={'name':'RenovPro Belgium renovation price guide','url':'https://renovpro.be/totaalrenovatie/kosten/','asOf':'2025','note':'Published indicative item ranges include 6% VAT in the source; normalized to excluding VAT before applying the selected VAT assumption. Item bands are informational and not added to the global scenario.'}
COMPONENT_RATES={'finishes':(80,160),'kitchen':(8000,20000),'bathroom':(8000,20000),'electricity':(80,150),'plumbing':(60,120),'heating':(6000,15000),'insulation':(150,250)}
COMPONENT_TERMS={'finishes':('flooring to replace','new flooring','parquet à remplacer','parquet a remplacer','peinture à refaire','peinture a refaire','vloeren vernieuwen'),'kitchen':('kitchen to replace','kitchen needs renovation','cuisine à rénover','cuisine a renover','keuken te vernieuwen'),'bathroom':('bathroom to replace','bathroom needs renovation','salle de bain à rénover','salle de bain a renover','badkamer te vernieuwen'),'electricity':('rewire','electricity needs renovation','électricité à refaire','electricite a refaire','elektriciteit vernieuwen'),'plumbing':('plumbing to replace','plumbing needs renovation','plomberie à refaire','plomberie a refaire','leidingen vernieuwen'),'heating':('heating to replace','heating needs renovation','chauffage à remplacer','verwarming vernieuwen'),'insulation':('insulation to install','needs insulation','isolation à prévoir','isolation a prevoir','isolatie nodig')}


def renovation_estimate(listing, criteria, override=None):
    """Return transparent user-selected scenario, not an inspection or defect diagnosis."""
    if override and isinstance(override,dict) and number_or_none(override.get('low')) is not None and number_or_none(override.get('high')) is not None:
        low=max(0,number_or_none(override['low'])); high=max(low,number_or_none(override['high']))
        return {'low':low,'high':high,'source':'manual','confidence':'user override','scenario':False,'breakdown':[],'note':'Estimation manuelle conservée.'}
    area=number_or_none(listing.get('area')); scope=criteria.get('renovationScope','cosmetic')
    if area is None or area<=0 or scope not in RENOVATION_RATES:
        return {'low':None,'high':None,'source':'unknown','confidence':'unknown','scenario':False,'breakdown':[],'note':'Budget rénovation à confirmer'}
    lo,hi=RENOVATION_RATES[scope]
    custom_low=number_or_none(criteria.get('renovationRateLow'));custom_high=number_or_none(criteria.get('renovationRateHigh'))
    if custom_low is not None and custom_high is not None and custom_high>=custom_low:lo,hi=custom_low,custom_high
    vat=number_or_none(criteria.get('vatPct'))
    if vat is None:vat=21
    # Convert the ex-VAT reference bands to the user's explicitly selected assumed rate.
    low=round(area*lo*(1+vat/100)); high=round(area*hi*(1+vat/100))
    contingency=max(0,min(50,number_or_none(criteria.get('contingencyPct')) if number_or_none(criteria.get('contingencyPct')) is not None else 15))
    low=round(low*(1+contingency/100)); high=round(high*(1+contingency/100))
    text=norm((listing.get('title') or '')+' '+(listing.get('summary') or ''))
    explicit=[k for k,terms in COMPONENT_TERMS.items() if any(norm(term) in text for term in terms)]
    label='scenario' if not explicit else 'application estimate informed by ad wording'
    breakdown=[]
    for key in explicit:
        a,b=COMPONENT_RATES[key]
        # RenovPro component references are inclusive of 6% VAT; normalize to ex-VAT first.
        a,b=round(a/1.06),round(b/1.06)
        if key in ('kitchen','bathroom','heating'):cl,ch=a,b
        else:cl,ch=round(area*a),round(area*b)
        breakdown.append({'item':key,'low':round(cl*(1+vat/100)),'high':round(ch*(1+vat/100)),'basis':'published indicative unit prices; informational and not additive'})
    confidence='high uncertainty' if not explicit else 'high uncertainty; property not inspected'
    # An explicitly poor regional certificate raises uncertainty only; it never asserts hidden work.
    if listing.get('energyRating') in ('F','G','F+','G+'): confidence += '; weak disclosed energy label warrants verification; no works inferred'
    evidence=[]
    if listing.get('condition'):evidence.append('État déclaré dans l’annonce : '+str(listing['condition'])+'.')
    if listing.get('energyRating'):evidence.append('Label '+str(listing.get('energyRegion') or 'régional non confirmé')+' '+str(listing['energyRating'])+' : à faire vérifier; aucun travaux d’isolation n’est présumé.')
    if explicit:evidence.append('Travaux explicitement mentionnés : '+', '.join(explicit)+'. Fourchettes informatives non additionnées au scénario global.')
    return {'low':low,'high':high,'source':'application','confidence':confidence,'scenario':not bool(explicit),'scope':scope,'area':area,'rateLow':lo,'rateHigh':hi,'vatPct':vat,'vatNote':'TVA appliquée selon hypothèse choisie. Le taux réduit de 6% est soumis à conditions; 21% sinon.','contingencyPct':contingency,'breakdown':breakdown,'evidence':evidence,'reference':RENOVATION_REFERENCE,'componentReference':COMPONENT_REFERENCE,'note':'Scénario selon surface et hypothèses modifiables; ni inspection, ni devis. Les postes détaillés sont indicatifs, non additionnels à la fourchette globale.'}


def evaluate_listing(row, criteria, mode, override=None):
    reasons=[]; unknown=[]
    price=row.get('price'); area=row.get('area'); beds=row.get('bedrooms')
    min_price=number_or_none(criteria.get('minBudget' if mode=='rent' else 'minPrice')); max_price=number_or_none(criteria.get('maxBudget' if mode=='rent' else 'maxPrice'))
    compare_price=price
    if mode=='rent' and criteria.get('budgetBasis')=='rent_and_charges':
        if price is None or row.get('fees') is None:compare_price=None
        else:compare_price=price+row['fees']
    row['comparisonPrice']=compare_price
    if min_price is not None:
        if compare_price is None:unknown.append('loyer et charges nécessaires au budget inconnus' if mode=='rent' and criteria.get('budgetBasis')=='rent_and_charges' else 'prix inconnu')
        elif compare_price<min_price:reasons.append('prix inférieur au minimum')
    if max_price is not None:
        if compare_price is None:unknown.append('loyer et charges nécessaires au budget inconnus' if mode=='rent' and criteria.get('budgetBasis')=='rent_and_charges' else 'prix inconnu')
        elif compare_price>max_price:reasons.append('prix supérieur au maximum')
    min_area=number_or_none(criteria.get('minArea'));max_area=number_or_none(criteria.get('maxArea'))
    for bound,val,label,op in ((min_area,area,'surface minimale','min'),(max_area,area,'surface maximale','max')):
        if bound is not None:
            if val is None:unknown.append('surface inconnue')
            elif (op=='min' and val<bound) or (op=='max' and val>bound):reasons.append('surface hors critère')
    bd=criteria.get('bedrooms')
    min_beds=number_or_none(str(bd).replace('+',''))
    if bd not in ('',None):
        if beds is None:unknown.append('nombre de chambres inconnu')
        elif (min_beds==0 and beds!=0) or (min_beds>0 and beds<min_beds):reasons.append('type de logement incompatible avec le nombre de chambres')
    subtypes=criteria.get('subtypes') or []
    if subtypes:
        hay=norm((row.get('subtype') or '')+' '+(row.get('title') or '')+' '+(row.get('summary') or ''))
        aliases={'studio':('studio','studette'),'duplex':('duplex',),'penthouse':('penthouse','attique'),'loft':('loft',)}
        matched=any(any(norm(alias) in hay for alias in aliases.get(norm(want), (norm(want),))) for want in subtypes)
        if not matched:
            if row.get('subtype') is None and not any(k in hay for aliaseset in aliases.values() for k in aliaseset):unknown.append('sous-type non précisé')
            else:reasons.append('sous-type incompatible')
    property_type=criteria.get('property','Apartment')
    if property_type not in ('Apartment','Apartment or house',''):
        hay=norm((row.get('title') or '')+' '+(row.get('summary') or ''))
        if 'house' in norm(property_type) and not any(x in hay for x in ('maison','house','woning')):reasons.append('type maison incompatible')
    for key,selected in (('energyRating',criteria.get('energyRating','any')),):
        if selected not in ('any','',None):
            value=row.get(key)
            if value is None:unknown.append('classe énergétique non précisée')
            elif norm(value)!=norm(selected):reasons.append('classe énergétique incompatible')
    for feature,wanted in (criteria.get('features') or {}).items():
        if wanted not in (True,False,'true','false'):continue
        desired=wanted is True or wanted=='true'; actual=(row.get('features') or {}).get(feature)
        if actual is None:unknown.append(f'{feature} non précisé')
        elif bool(actual)!=desired:reasons.append(f'{feature} absent' if desired else f'{feature} présent')
    for key,selected,unknown_label,failed_label in (
        ('furnished',criteria.get('furnished','any'),'ameublement non précisé','ameublement incompatible'),
        ('construction',criteria.get('construction','any'),'type de construction non précisé','type de construction incompatible'),
        ('condition',criteria.get('condition','any'),'état non précisé','état incompatible'),
        ('occupancy',criteria.get('occupancy','any'),'occupation non précisée','occupation incompatible'),
    ):
        if selected not in ('any','indifferent','',None):
            value=row.get('features',{}).get(key) if key=='furnished' else row.get(key)
            if value is None:unknown.append(unknown_label)
            elif key=='furnished':
                expected=selected in ('furnished','meublé','gemeubileerd')
                if bool(value)!=expected:reasons.append(failed_label)
            elif norm(value)!=norm(selected):reasons.append(failed_label)
    if mode=='sale' and number_or_none(criteria.get('maxCondoFees')) is not None:
        if row.get('fees') is None:unknown.append('charges de copropriété non précisées')
        elif row['fees']>number_or_none(criteria['maxCondoFees']):reasons.append('charges de copropriété au-dessus du maximum')
    for field,cap in (('floorMin',None),('floorMax',None)):
        value=number_or_none(criteria.get(field))
        if value is not None:
            if row.get('floor') is None:unknown.append('étage non précisé')
            elif field=='floorMin' and row['floor']<value:reasons.append('étage inférieur au minimum')
            elif field=='floorMax' and row['floor']>value:reasons.append('étage supérieur au maximum')
    recency=number_or_none(criteria.get('publicationDays'))
    if recency is not None:
        if row.get('publicationDate') is None:unknown.append('date de publication inconnue; récence non vérifiable')
        else:
            try:
                if (date.today()-date.fromisoformat(row['publicationDate'])).days>recency:reasons.append('annonce plus ancienne que la période choisie')
                if row.get('publicationDateUncertain'):unknown.append('date de publication relative, récence approximative')
            except ValueError:unknown.append('date de publication invalide')
    if criteria.get('mustHaves'):
        for requirement in re.split(r'[,;\n]',criteria.get('mustHaves','')):
            requirement=norm(requirement)
            if requirement and requirement not in norm((row.get('title') or '')+' '+(row.get('summary') or '')):unknown.append(f'{requirement} à confirmer')
    move=norm(criteria.get('moveDate',''))
    if mode=='rent' and move and move not in ('sans preference','indifferent','flexible','any','no preference'):
        availability=norm(row.get('availability',''))
        if any(x in move for x in ('immediat','immediately','asap','maintenant')):
            if not any(x in availability for x in ('immediat','immediately','now')):unknown.append('disponibilité immédiate non confirmée')
        elif not availability or move not in availability:unknown.append('date de disponibilité à confirmer')
    if mode=='sale':
        est=renovation_estimate(row,criteria,override)
        row['renovation']=est
        cap=number_or_none(criteria.get('maxRenovation'));combined=number_or_none(criteria.get('maxCombined'))
        if cap is not None:
            if est['high'] is None:
                (unknown if criteria.get('includeUnknownRenovation') else reasons).append('budget rénovation inconnu' if criteria.get('includeUnknownRenovation') else 'budget rénovation inconnu · exclu du budget confirmé')
            elif est['high']>cap:reasons.append('fourchette haute rénovation au-dessus du maximum')
        if combined is not None:
            if price is None or est['high'] is None:
                (unknown if criteria.get('includeUnknownRenovation') else reasons).append('total achat + rénovation inconnu' if criteria.get('includeUnknownRenovation') else 'total achat + rénovation inconnu · exclu du budget confirmé')
            elif price+est['high']>combined:reasons.append('total achat + rénovation supérieur au maximum')
        cap_m2=number_or_none(criteria.get('maxPricePerM2'))
        if cap_m2 is not None:
            if not area or not price:unknown.append('prix au m² inconnu')
            elif price/area>cap_m2:reasons.append('prix au m² supérieur au maximum')
    exact=not reasons and not unknown
    row['matchState']='confirmed' if exact else 'unknown' if not reasons and unknown else 'failed'
    row['type']='match' if exact else 'wildcard' if not reasons and unknown else 'excluded'
    row['matchReasons']=reasons;row['unknownReasons']=unknown
    row['match']=('Critères confirmés dans les informations disponibles.' if exact else '; '.join(reasons+unknown))
    return row


def best_rows(rows, criteria):
    sort=criteria.get('sort','relevance')
    def k(x):
        if sort=='newest':
            try:ordinal=date.fromisoformat(x.get('publicationDate') or '').toordinal()
            except ValueError:ordinal=0
            return (x.get('publicationDate') is None, -ordinal,x.get('price') or 10**12)
        if sort=='price':return (x.get('price') is None,x.get('price') or 10**12)
        if sort=='area':return (x.get('area') is None,-(x.get('area') or 0))
        return (x.get('matchState')!='confirmed',x.get('price') is None,x.get('price') or 10**12)
    ordered=sorted(rows,key=k)
    if sort!='relevance':return ordered
    # Relevance is a presentation mode: rotate through advertisers so the
    # first page represents the available agencies instead of one large portal.
    spread=[]
    states={}
    for row in ordered:states.setdefault(row.get('matchState'),[]).append(row)
    for state_rows in states.values():
        buckets={}
        for row in state_rows:buckets.setdefault(row.get('source') or 'Autre source',deque()).append(row)
        while buckets:
            for source in list(buckets):
                bucket=buckets[source];spread.append(bucket.popleft())
                if not bucket:del buckets[source]
    return spread
