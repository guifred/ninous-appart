"""Read the advertised EPC/PEB class from text, badges and certificate images."""
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import threading

from agency_parsers import Tree, Node, clean
from model import extract_energy_rating

LABEL = re.compile(r'(?:epc|peb)(?:[\s_-]+(?:label|klasse|class|classe))?|energielabel|energieklasse|energy\s+(?:label|class)',re.I)
_VISION_LOCK=threading.Lock()
_VISION_UNAVAILABLE=False


def _node_evidence(node):
    nodes=[node,*node.all()]
    return ' '.join([node.text()]+[str(value) for part in nodes for value in part.attrs.values()])


def energy_badge_images(root,page_url):
    """Find only images identified as an energy label by their own or nearby markup."""
    if not page_url:return []
    candidates=[]
    for node in root.all():
        if node.tag!='img':continue
        own=' '.join(str(value) for value in node.attrs.values())
        parent=node.parent
        nearby=' '.join((parent.text(),str(parent.attrs))) if parent else ''
        if not LABEL.search(own) and not (len(nearby)<240 and LABEL.search(nearby)):
            continue
        value=next((node.attrs.get(key) for key in ('data-src','data-lazy-src','src','data-original') if node.attrs.get(key)),None)
        if not value and node.attrs.get('srcset'):value=node.attrs['srcset'].split(',')[0].strip().split()[0]
        if not value:continue
        url=urljoin(page_url,value)
        parsed=urlsplit(url)
        if parsed.scheme=='https' and parsed.hostname and not re.search(r'\.svg$',parsed.path,re.I) and url not in candidates:
            candidates.append(url)
    return candidates[:2]


def _vision_binary():
    global _VISION_UNAVAILABLE
    if _VISION_UNAVAILABLE:return None
    script=Path(__file__).resolve().parent/'scripts/ocr_energy.swift'
    if not script.exists() or not shutil.which('swiftc'):return None
    digest=hashlib.sha256(script.read_bytes()).hexdigest()[:12]
    path=Path(tempfile.gettempdir())/('ninou-energy-ocr-'+digest)
    if path.exists():return path
    with _VISION_LOCK:
        if path.exists():return path
        temporary=path.with_name(path.name+'.building')
        try:result=subprocess.run(['swiftc','-module-cache-path',str(Path(tempfile.gettempdir())/'ninou-swift-modules'),str(script),'-o',str(temporary)],capture_output=True,text=True,timeout=150)
        except (OSError,subprocess.TimeoutExpired):
            _VISION_UNAVAILABLE=True;return None
        if result.returncode!=0:
            _VISION_UNAVAILABLE=True;return None
        temporary.replace(path)
    return path


def _ocr_text(image_path):
    command=None
    if shutil.which('tesseract'):
        command=['tesseract',str(image_path),'stdout','--psm','6']
    elif sys.platform=='darwin':
        binary=_vision_binary()
        if binary:command=[str(binary),str(image_path)]
    if not command:return ''
    result=subprocess.run(command,capture_output=True,text=True,timeout=20)
    return result.stdout if result.returncode==0 else ''


def _ocr_rating(text):
    rating=extract_energy_rating(text)
    if rating:return rating
    letters=re.findall(r'(?<![A-Z])([A-G](?:\+{1,2})?)(?![A-Z])',text.upper())
    return letters[0] if len(set(letters))==1 and len(text)<80 else None


def _flemish_residential_label_from_score(root):
    """Read a displayed Flemish EPC label when its badge image has an opaque URL.

    Flemish residential labels on certificates issued since 2019 use fixed
    score bands. Only use the band when the page also advertises an EPC label;
    a bare score can belong to an older certificate without an official label.
    """
    content=clean(root.text())
    if not re.search(r'\bEPC\s*label\s*:',content,re.I):return None
    match=re.search(r'\bEPC\s*:\s*(-?\d{1,4})\s*kWh\s*/\s*m\s*[²2]',content,re.I)
    if not match:return None
    score=int(match.group(1))
    if score<=0:return 'A+'
    if score<=100:return 'A'
    if score<=200:return 'B'
    if score<=300:return 'C'
    if score<=400:return 'D'
    if score<=500:return 'E'
    return 'F'


@lru_cache(maxsize=256)
def read_energy_image(url):
    """OCR a small public EPC badge, only when its image URL allows crawling."""
    try:
        from scraper import source_robots_ok
        parsed=urlsplit(url)
        if not source_robots_ok(parsed.scheme+'://'+parsed.netloc,url):return None
        request=Request(url,headers={'User-Agent':'NinousAppartementFinder/0.3 (personal use; public pages only)'})
        with urlopen(request,timeout=15) as response:
            if not response.headers.get('Content-Type','').lower().startswith('image/'):return None
            image=response.read(2_000_001)
        if not image or len(image)>2_000_000:return None
        suffix=Path(parsed.path).suffix.lower()
        with tempfile.NamedTemporaryFile(suffix=suffix if suffix in ('.png','.jpg','.jpeg','.webp','.gif','.tiff') else '.png') as file:
            file.write(image);file.flush()
            return _ocr_rating(_ocr_text(file.name))
    except (OSError,ValueError,subprocess.TimeoutExpired):return None


def extract_detail_energy(page,page_url=None):
    """Return a published class; a kWh figure alone is not a class."""
    # Property descriptions often disclose the label without a separate table.
    from beach_distance import listing_description
    rating=extract_energy_rating(listing_description(page))
    if rating:return rating
    root=Tree(page).root
    for node in root.all():
        if node.tag in ('p','li','td','th','span','div') and len(node.children)<=3:
            sentence=clean(node.text())
            limit=1500 if node.tag in ('p','li') else 100
            if len(sentence)<=limit:
                rating=extract_energy_rating(sentence)
                if rating:return rating
        label=clean(node.text())
        if len(label)>40 or not LABEL.fullmatch(label):continue
        if re.search(r'gemene\s+delen|parties\s+communes|shared|ref',label,re.I):continue
        parent=node.parent
        if not parent:continue
        siblings=parent.children
        try:index=siblings.index(node)
        except ValueError:continue
        following=next((part for part in siblings[index+1:] if isinstance(part,Node)),None)
        if following:
            rating=extract_energy_rating(label+' '+_node_evidence(following))
            if rating:return rating
        # Some layouts put the label and value in adjacent rows instead.
        if parent.parent:
            peers=parent.parent.children
            try:index=peers.index(parent)
            except ValueError:continue
            following=next((part for part in peers[index+1:] if isinstance(part,Node)),None)
            if following:
                rating=extract_energy_rating(label+' '+_node_evidence(following))
                if rating:return rating
    for image_url in energy_badge_images(root,page_url):
        rating=read_energy_image(image_url)
        if rating:return rating
    return _flemish_residential_label_from_score(root)
