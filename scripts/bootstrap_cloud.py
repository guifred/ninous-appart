"""Initialize a disposable CI workspace from sanitized shared collection state."""
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from public_site.build import defaults, read, write


def bootstrap(root=ROOT):
    if os.environ.get('GITHUB_ACTIONS')!='true':
        raise RuntimeError('Initialisation réservée au serveur GitHub ; tes critères locaux sont protégés.')
    config=read(root/'public_site/agencies.json',{})
    for name,value in config.items():
        if name not in ('brussels-sources.json','sites.json','requested-agencies.json'):raise ValueError('Registre inconnu')
        write(root/'data/agencies'/name,value)
    for mode,criteria in defaults().items():
        # Collect broadly once; each visitor filters the shared catalogue locally.
        criteria['property']='Apartment or house'
        state=read(root/'public-data'/(mode+'.json'),{'items':[],'status':{}})
        write(root/'data'/mode/'criteria.json',criteria)
        write(root/'data'/mode/'listings.json',state['items'])
        write(root/'data'/mode/'status.json',state['status'])

if __name__=='__main__':bootstrap()
