import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from public_site.build import build, sanitize_row, sanitize_status, defaults, write
from scripts.bootstrap_cloud import bootstrap

class PublicExportTests(unittest.TestCase):
    def test_personal_fields_and_error_paths_are_not_exported(self):
        row={'id':'one','title':'Appartement','url':'https://example.be/ad/one','price':950,'renovationOverride':{'low':123},'privateNote':'SECRET','features':{'terrace':True,'secret':'SECRET'},'photos':['https://example.be/room.jpg']}
        clean=sanitize_row(row)
        self.assertNotIn('renovationOverride',clean)
        self.assertNotIn('SECRET',json.dumps(clean))
        status=sanitize_status({'lastRun':'2026-10-22T10:00:00+02:00','error':'/Users/PRIVATE/path','sources':[{'source':'Agency','ok':False,'reason':'PRIVATE','token':'SECRET'}]})
        self.assertNotIn('PRIVATE',json.dumps(status));self.assertNotIn('SECRET',json.dumps(status))

    def test_build_uses_neutral_preferences_preserves_dates_and_excludes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=folder/'data';site=folder/'site';state=folder/'state'
            for m in ('rent','sale'):
                write(data/m/'criteria.json',{'maxBudget':1234,'private':'SECRET'})
                write(data/m/'listings.json',[{'id':'active','url':'https://example.be/a','title':'Appartement','location':'1050 Ixelles','price':950,'area':80,'bedrooms':2,'firstDiscovered':'2026-10-01','photos':[]},{'id':'stale','stale':True,'firstDiscovered':'2026-09-01'}])
                write(data/m/'status.json',{'lastRun':'2026-10-22T10:00:00+02:00','state':'partial'})
            files=build(site,data,state)
            manifest=json.loads((site/'data/manifest.json').read_text())
            self.assertEqual(manifest['config']['defaults']['rent']['maxBudget'],'')
            for m in ('rent','sale'):
                rows=json.loads((site/'data'/files[m]).read_text())['items']
                self.assertEqual([r['id'] for r in rows],['active'])
                self.assertEqual(rows[0]['firstDiscovered'],'2026-10-01')
                self.assertEqual(len(json.loads((state/(m+'.json')).read_text())['items']),2)
            html=(site/'index.html').read_text()
            self.assertNotIn('src="/app.js"',html);self.assertIn('src="api.js"',html)
            self.assertFalse((site/'data/rent/criteria.json').exists())

    def test_cloud_bootstrap_does_not_touch_local_preferences(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'false'}):
            with self.assertRaises(RuntimeError):bootstrap()

    def test_cloud_bootstrap_restores_history_and_collects_broadly(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict('os.environ',{'GITHUB_ACTIONS':'true'}):
            root=Path(tmp)
            write(root/'public-data/rent.json',{'items':[{'id':'x','firstDiscovered':'2026-01-02'}],'status':{}})
            bootstrap(root)
            self.assertEqual(json.loads((root/'data/rent/listings.json').read_text())[0]['firstDiscovered'],'2026-01-02')
            criteria=json.loads((root/'data/rent/criteria.json').read_text())
            self.assertEqual(criteria['property'],'Apartment or house');self.assertEqual(criteria['maxBudget'],'')
