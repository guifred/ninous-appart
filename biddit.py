"""Low-rate adapter for Biddit's public Belgian notarial-sale catalogue.

Only the public catalogue endpoint is used. No account, bidding endpoint,
challenge, or private endpoint is accessed. Biddit has no rental inventory.
"""
from __future__ import annotations

from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import json
import re
import ssl
import time


ROOT = 'https://www.biddit.be'
SEARCH_PATH = '/api/eco/search-service/lot/_landing'
UA = 'NinousAppartementFinder/0.1 (personal use; public listing checks)'
PAGE_SIZE = 30  # Biddit caps the public endpoint at 30 even when asked for more.
MAX_PAGES = 60   # Bound each run, including unusual catalogue growth.
DELAY = 1.1
TIMEOUT = 20


def _robots_allows(url: str) -> bool:
    robots_url = ROOT + '/robots.txt'
    req = Request(robots_url, headers={'User-Agent': UA, 'Accept': 'text/plain'})
    with urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as response:
        if response.status != 200:
            raise RuntimeError('Biddit robots.txt could not be verified; collection paused.')
        parser = RobotFileParser(robots_url)
        parser.parse(response.read().decode('utf-8', errors='replace').splitlines())
    return parser.can_fetch(UA, url)


def _get_page(page: int) -> dict:
    url = ROOT + SEARCH_PATH + '?' + urlencode({'page': page, 'pageSize': PAGE_SIZE})
    req = Request(url, headers={
        'User-Agent': UA,
        'Accept': 'application/json',
    })
    for attempt in range(3):
        try:
            with urlopen(req, timeout=TIMEOUT, context=ssl.create_default_context()) as response:
                if response.status != 200:
                    raise RuntimeError(f'Biddit catalogue returned HTTP {response.status}')
                payload = json.loads(response.read().decode('utf-8', errors='replace'))
            if not isinstance(payload, dict) or not isinstance(payload.get('content'), list):
                raise ValueError('Biddit returned an unsupported public catalogue response.')
            return payload
        except HTTPError as exc:
            if exc.code not in (408, 425, 429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError) as exc:
            if attempt == 2:
                raise
        time.sleep(0.6 * (2 ** attempt))
    raise RuntimeError('Biddit catalogue request retries exhausted.')


def _localized(value) -> str:
    if isinstance(value, str):
        return unescape(value).strip()
    if isinstance(value, dict):
        for lang in ('fr', 'nl', 'en', 'de'):
            if isinstance(value.get(lang), str) and value[lang].strip():
                return unescape(value[lang]).strip()
    return ''


def _amount(value):
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (ValueError, TypeError, AttributeError):
        return None


def _energy(prop):
    for key in ('energeticClassRBC', 'energeticClassRW', 'energeticClassRF'):
        value = prop.get(key)
        if isinstance(value, str) and re.fullmatch(r'CLASS_[A-G](?:_PLUS)?', value):
            return value[6:].replace('_PLUS', '+')
    return None


def _listing(item, include_houses=False):
    row = item.get('content') if isinstance(item, dict) else None
    if not isinstance(row, dict):
        return None
    props = row.get('properties') or []
    if not props or not isinstance(props[0], dict):
        return None
    prop = props[0]
    prop_type = str(prop.get('propertyType') or '').upper()
    if prop_type != 'APARTMENT' and not (include_houses and prop_type == 'HOUSE'):
        return None

    reference = str(row.get('referenceCode') or row.get('reference') or '').strip()
    lot_id = str(row.get('lotId') or '').strip()
    if not reference or not reference.isdigit() or not lot_id:
        return None
    url = f'{ROOT}/fr/catalog/detail/{reference}'
    address = prop.get('address') or {}
    postal = str(address.get('postalCode') or '').strip()
    city = _localized(address.get('municipality'))
    street = _localized(address.get('street'))
    location = ' '.join(x for x in (postal, city) if x).strip() or city or 'Belgique'
    title = _localized(prop.get('title')) or ('Maison' if prop_type == 'HOUSE' else 'Appartement')
    method = str(row.get('handlingMethod') or '').upper()
    is_auction = 'PUBLIC_SALE' in method
    display_price = None
    price = None
    price_label = 'Prix affiché'
    if is_auction:
        current = _amount(row.get('currentPrice'))
        starting = _amount(row.get('startingPrice') or row.get('initialStartingPrice'))
        display_price = current if current is not None else starting
        price_label = 'Enchère actuelle' if current is not None else 'Mise à prix'
    else:
        price = _amount(row.get('sellingPrice'))
        display_price = price

    photo = prop.get('picture') or {}
    photos = [photo.get('bucketUrlMedium')] if isinstance(photo, dict) else []
    photos = [x for x in photos if isinstance(x, str) and x.startswith('https://')]
    geo = row.get('geoLocation') or {}
    publication = row.get('firstPublicationDateTime')
    try:
        publication = datetime.fromisoformat(str(publication).replace('Z', '+00:00')).date().isoformat()
    except (TypeError, ValueError):
        publication = None
    status = str(row.get('publicSaleStatus') or '').replace('_', ' ').lower()
    auction_info = 'Vente notariale via Biddit'
    if is_auction:
        auction_info = 'Vente publique notariale par enchères'
    elif method:
        auction_info = 'Vente notariale en ligne'
    if status:
        auction_info += ' · statut : ' + status
    if row.get('biddingEndDateTime'):
        auction_info += ' · échéance des enchères : ' + str(row['biddingEndDateTime'])[:10]

    return {
        'id': f'biddit-{reference}', 'source': 'Biddit', 'sourceType': 'portal',
        'url': url, 'title': title, 'location': location, 'postalCode': postal or None,
        'streetAddress': ' '.join(x for x in (street, str(address.get('estateNumber') or '')) if x).strip() or None,
        'price': price, 'displayPrice': display_price, 'priceLabel': price_label,
        'area': _amount(prop.get('livingSurfaceArea')),
        'bedrooms': _amount(prop.get('numberOfBedrooms')),
        'energyRating': _energy(prop), 'energyText': _energy(prop),
        'latitude': _amount(geo.get('lat')), 'longitude': _amount(geo.get('lon')),
        'photos': photos, 'publicationDate': publication,
        'summary': auction_info + '. ' + title,
        'saleType': 'auction' if is_auction else 'private-sale',
        'condition': title if re.search(r'renov|à rénover|te renoveren', title, re.I) else None,
        'availability': status or None,
    }


def parse_catalogue_page(payload, include_houses=False):
    """Parse one fixture or public response page without performing I/O."""
    return [row for item in payload.get('content', [])
            if (row := _listing(item, include_houses=include_houses)) is not None]


def collect_biddit(mode='sale', include_houses=False):
    if mode != 'sale':
        return [], {'source': 'Biddit', 'ok': True, 'found': 0, 'transaction': mode,
                    'note': 'Biddit publie des ventes, pas de locations.'}
    endpoint = ROOT + SEARCH_PATH
    if not _robots_allows(endpoint):
        raise PermissionError('Biddit catalogue endpoint is disallowed by robots.txt.')
    first = _get_page(0)
    total_pages = max(1, min(int(first.get('totalPages') or 1), MAX_PAGES))
    rows = parse_catalogue_page(first, include_houses)
    errors = []
    checked_pages = 1
    for page in range(1, total_pages):
        time.sleep(DELAY)
        try:
            payload = _get_page(page)
            rows.extend(parse_catalogue_page(payload, include_houses))
            checked_pages += 1
            if not payload.get('content'):
                break
        except Exception as exc:
            errors.append({'page': page, 'error': str(exc)[:200]})
            break
    partial = bool(errors) or int(first.get('totalPages') or 1) > MAX_PAGES
    result = {
        'source': 'Biddit', 'ok': True, 'transaction': 'sale', 'found': len(rows),
        'pages': checked_pages, 'totalPagesAvailable': int(first.get('totalPages') or 1),
        'catalogueListingsAvailable': int(first.get('totalElements') or 0),
        'partial': partial, 'errors': errors,
        'note': 'Catalogue public des ventes notariales; seules les annonces appartement' +
                ('s et maisons' if include_houses else 's') +
                ' sont retenues. Les mises à prix d’enchères restent des montants indicatifs, pas un prix de vente garanti.',
    }
    return rows, result
