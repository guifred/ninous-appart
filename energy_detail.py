"""Read the advertised EPC/PEB class from a property's detail page."""
import re

from agency_parsers import Tree, Node, clean
from model import extract_energy_rating

LABEL = re.compile(r'(?:epc|peb)(?:\s+(?:label|klasse|class|classe))?|energielabel|energieklasse|energy\s+(?:label|class)',re.I)


def _node_evidence(node):
    nodes=[node,*node.all()]
    return ' '.join([node.text()]+[str(value) for part in nodes for value in part.attrs.values()])


def extract_detail_energy(page):
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
    return None
