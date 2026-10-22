"""Agency identity from explicit listing metadata, never inferred from ad prose."""
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
import json
import re

DIRECT_AGENCIES = {
    'Sorimo': ('https://cdn.webulous.io/sites/31UG0RNJZA/images/logo_main.png?170720260337', 'https://www.sorimo.be'),
    'Easy Properties': ('https://easyproperties.be/wp-content/uploads/2021/08/favicon.svg', 'https://easyproperties.be'),
    'Red Immobilier': ('https://www.redimmobilier.be/images/redimmobilier.png', 'https://www.redimmobilier.be'),
}

def image_url(value, base):
    if isinstance(value, dict):
        value = value.get('contentUrl') or value.get('url')
    if not isinstance(value, str) or not value.strip():
        return None
    url = urljoin(base, value.strip())
    parsed = urlsplit(url)
    return url if parsed.scheme == 'https' and parsed.hostname and not parsed.username else None

def structured_brand(node, base):
    if not isinstance(node, dict):
        return {}
    for key in ('seller', 'broker', 'realEstateAgent', 'provider'):
        agent = node.get(key)
        if not isinstance(agent, dict):
            continue
        logo = image_url(agent.get('logo'), base)
        name = agent.get('name')
        if logo or isinstance(name, str):
            return {k: v for k, v in {'agencyName': name if isinstance(name, str) else None,
                    'agencyLogo': logo, 'agencyWebsite': image_url(agent.get('url'), base)}.items() if v}
    offers = node.get('offers')
    if isinstance(offers, dict):
        return structured_brand(offers, base)
    return {}

def logo_attributes(attrs, base):
    marker = ' '.join(str(attrs.get(k, '')) for k in ('class', 'id', 'src', 'data-src'))
    if not re.search(r'(?:agency|agent|customer|realtor|broker).*logo|logo.*(?:agency|agent|customer|realtor|broker)|/agency/', marker, re.I):
        return {}
    logo = image_url(attrs.get('data-src') or attrs.get('src'), base)
    if not logo:
        return {}
    name = re.sub(r'\blogo\b', '', attrs.get('alt', ''), flags=re.I).strip(' -:')
    return {'agencyLogo': logo, **({'agencyName': name} if name else {})}

class BrandParser(HTMLParser):
    def __init__(self, base):
        super().__init__(); self.base = base; self.brand = {}; self.script = None; self.blocks = []
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'img' and not self.brand.get('agencyLogo'):
            self.brand.update(logo_attributes(attrs, self.base))
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.script = []
    def handle_data(self, data):
        if self.script is not None: self.script.append(data)
    def handle_endtag(self, tag):
        if tag == 'script' and self.script is not None:
            self.blocks.append(''.join(self.script)); self.script = None

def parse_branding(page, base):
    parser = BrandParser(base); parser.feed(page)
    for block in parser.blocks:
        try: stack = [json.loads(block)]
        except (ValueError, TypeError): continue
        while stack:
            node = stack.pop()
            if isinstance(node, list): stack.extend(node)
            elif isinstance(node, dict):
                candidate=node.get('url') or node.get('@id')
                if not isinstance(candidate,str) or urlsplit(urljoin(base,candidate)).path.rstrip('/') == urlsplit(base).path.rstrip('/'):
                    parser.brand.update(structured_brand(node, base))
                if isinstance(node.get('@graph'), list): stack.extend(node['@graph'])
    return parser.brand

def with_branding(row):
    if row.get('source') in DIRECT_AGENCIES:
        logo, website = DIRECT_AGENCIES[row['source']]
        row.setdefault('agencyName', row['source']); row.setdefault('agencyLogo', logo)
        row.setdefault('agencyWebsite', website)
    return row
