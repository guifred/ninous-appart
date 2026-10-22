"""Explainable shortlist from the saved adverts, not an appraisal of market value."""
from collections import defaultdict
from statistics import median
import re
from model import number_or_none, evaluate_listing

def postal(row):
    match=re.search(r'\b\d{4}\b',str(row.get('postalCode') or row.get('location') or ''))
    return match[0] if match else None

def apartment(row):
    value=' '.join(str(row.get(k) or '') for k in ('propertyType','title','url')).lower()
    return any(word in value for word in ('apartment','appartement','studio','duplex','penthouse','loft')) and not any(word in value for word in ('/maison/','/house/'))

def select_gems(items,criteria,mode,limit=5):
    """Prefer confirmed matches, then at most one unresolved criterion; never failed ones."""
    from scraper import source_area_matches
    pool=[];seen=set();area_cache={}
    for original in items:
        row=dict(original)
        if row.get('stale') or not apartment(row):continue
        location=row.get('location') or ''
        if location not in area_cache:area_cache[location]=source_area_matches(criteria,location)
        if not area_cache[location]:continue
        price=number_or_none(row.get('price'));area=number_or_none(row.get('area'))
        if price is None or price<=0 or area is None or area<=0:continue
        if row.get('saleType')=='auction' or row.get('priceType')=='auction_start' or any(w in str(row.get('priceLabel') or '').lower() for w in ('enchère','mise à prix','starting')):continue
        key=(row.get('url') or row.get('id') or '').split('#')[0].rstrip('/')
        unit=(str(row.get('streetAddress') or '').lower(),postal(row),price,area,row.get('bedrooms'))
        key=unit if unit[0] and unit[1] else key
        if key in seen:continue
        seen.add(key)
        pool.append(row)
    neighbourhoods=defaultdict(list)
    for row in pool:
        if postal(row):neighbourhoods[postal(row)].append(row)
    ranked=[]
    for row in pool:
        evaluate_listing(row,criteria,mode,row.get('renovationOverride'))
        if row.get('matchState')=='failed' or row.get('matchReasons'):continue
        unknown=row.get('unknownReasons') or []
        if len(unknown)>1:continue
        price=float(row['price']);area=float(row['area']);bedrooms=number_or_none(row.get('bedrooms'))
        score=0;reasons=[];cautions=list(unknown)
        peers=[]
        for other in neighbourhoods.get(postal(row),[]):
            beds=number_or_none(other.get('bedrooms'))
            if other is row or bedrooms is None or beds is None or abs(beds-bedrooms)>1:continue
            if .65*area<=float(other['area'])<=1.5*area:peers.append(float(other['price'])/float(other['area']))
        comparison=None
        if len(peers)>=4:
            reference=median(peers);discount=1-(price/area)/reference
            # Very low prices need verification and do not dominate the shortlist.
            if discount>.45:cautions.append('Prix au m² inhabituellement bas : vérifier le montant et les conditions');score-=12
            elif discount>=.05:
                pct=round(discount*100);score+=min(28,discount*100)
                reasons.append(f'{pct} % sous le prix au m² médian de {len(peers)} annonces comparables dans la commune')
            comparison={'count':len(peers),'medianPerM2':round(reference,2),'listingPerM2':round(price/area,2)}
        f=row.get('features') or {}
        for feature,points,label in [('terrace',10,'Terrasse annoncée'),('garden',10,'Jardin annoncé'),('balcony',5,'Balcon annoncé'),('parking',5,'Parking annoncé'),('lift',4,'Ascenseur annoncé'),('cellar',3,'Cave annoncée')]:
            if f.get(feature) is True:score+=points;reasons.append(label)
        energy=str(row.get('energyRating') or '').upper().rstrip('+')
        if energy in ('A','B','C'):
            score+={'A':12,'B':9,'C':5}[energy];reasons.append('Classe énergétique '+str(row['energyRating'])+' annoncée')
        elif energy in ('F','G'):score-=10;cautions.append('PEB '+energy+' : consommation et travaux à examiner')
        elif not energy:cautions.append('Classe énergétique à confirmer')
        if bedrooms is not None and bedrooms>0 and area/bedrooms>=35:
            score+=8;reasons.append(f'{area:g} m² pour {bedrooms:g} chambres')
        if mode=='rent':
            fees=number_or_none(row.get('fees'))
            if fees is None:cautions.append('Charges mensuelles non précisées')
            else:score+=3;reasons.append(f'Charges précisées : {fees:g} €/mois')
        else:
            if row.get('condition') in ('good','renovated'):score+=8;reasons.append('Bon état déclaré' if row['condition']=='good' else 'Rénovation déclarée')
            if row.get('condition')=='renovation':score-=7;cautions.append('Travaux à chiffrer avant toute décision')
            if row.get('occupancy')=='occupied':score-=5;cautions.append('Bien occupé : conditions à vérifier')
            renovation=row.get('renovation') or {}
            if renovation.get('scenario'):cautions.append('Budget travaux fondé sur un scénario indicatif')
        if not reasons:reasons.append(f'{area:g} m² · prix demandé {price:,.0f} €'.replace(',',' '))
        if row.get('matchState')=='confirmed':reasons.append('Correspond à tes critères enregistrés')
        row['gem']={'reasons':reasons[:3],'cautions':list(dict.fromkeys(cautions))[:2], 'comparison':comparison,
                    'label':'À regarder de près' if unknown else 'À visiter en priorité','score':round(score,1),'needsReview':bool(unknown)}
        ranked.append(row)
    ranked.sort(key=lambda r:(r['gem']['needsReview'],-r['gem']['score'],float(r['price']),str(r.get('id'))))
    return ranked[:limit]
