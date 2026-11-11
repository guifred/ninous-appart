import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from public_site.build import build, sanitize_row, sanitize_status, defaults, write
from scripts.bootstrap_cloud import bootstrap
from agency_parsers import parse_catalogue, pagination
from beach_distance import add_beach_distance, extract_coordinates, extract_detail_address, extract_address_from_text, extract_address_from_url, enrich_coastal_locations
from brussels_agencies import collect_brussels
from gallery_enrichment import enrich_galleries
from energy_detail import extract_detail_energy

class PublicExportTests(unittest.TestCase):
    def test_future_agency_ad_recovers_energielabel_from_original_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write(data/'sale/status.json',{'state':'partial'})
            write(data/'sale/listings.json',[
                {'id':'future-energy','url':'https://agency.example/flat/456','title':'Appartement',
                 'summary':'','location':'1000 Bruxelles','postalCode':'1000','photos':[]}])
            page='<main><p>Appartement avec terrasse.</p><div><span>Energielabel</span><span>B</span></div></main>'
            with patch('gallery_enrichment.DATA',data),patch('gallery_enrichment.CACHE',data/'photo-cache.json'),\
                 patch('gallery_enrichment.source_robots_ok',return_value=True),\
                 patch('gallery_enrichment.fetch',return_value=page),patch('gallery_enrichment.time.sleep'):
                result=enrich_galleries(modes=('sale',),limit=1)
            row=json.loads((data/'sale/listings.json').read_text())[0]
            self.assertEqual(result['inspected'],1)
            self.assertEqual((row['energyRating'],row['energyRegion']),('B','PEB · Bruxelles'))

    def test_original_flemish_energy_labels_are_read_from_detail_pages(self):
        self.assertEqual(extract_detail_energy('<tr><td>EPC label</td><td><img src="/epc_label/epc_c.png"></td></tr>'),'C')
        self.assertEqual(extract_detail_energy('<div><div>EPC</div><div class="epc-value"><span class="ei-icon ei-icon-c"></span></div></div>'),'C')
        self.assertEqual(extract_detail_energy('<div>Energielabel: A</div>'),'A')
        self.assertEqual(extract_detail_energy('<p>EPC: 286 (Label C).</p>'),'C')
        self.assertIsNone(extract_detail_energy('<p>EPC: 286 kWh/m².</p>'))

    def test_future_coastal_agency_ad_gets_distance_on_daily_detail_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write(data/'coast/status.json',{'state':'source-error'})
            write(data/'coast/listings.json',[
                {'id':'future','url':'https://agency.example/flat/123','title':'Appartement te koop',
                 'summary':'','location':'8620 Nieuwpoort','photos':[]}])
            page='<div class="property-map" data-long="2.71352" data-lat="51.1461"></div>'
            with patch('gallery_enrichment.DATA',data),patch('gallery_enrichment.CACHE',data/'photo-cache.json'),\
                 patch('gallery_enrichment.source_robots_ok',return_value=True),\
                 patch('gallery_enrichment.fetch',return_value=page),\
                 patch('gallery_enrichment.time.sleep'),patch('beach_distance.persist_geocodes'):
                result=enrich_galleries(modes=('coast',),limit=1)
            row=json.loads((data/'coast/listings.json').read_text())[0]
            self.assertEqual(result['inspected'],1)
            self.assertGreater(row['beachDistanceM'],0)
            self.assertEqual(row['beachDistanceBasis'],'straight-line-estimate')

    def test_failed_coastal_host_does_not_stop_other_agencies(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write(data/'coast/status.json',{'state':'partial'})
            write(data/'coast/listings.json',[
                {'id':'one','url':'https://one.example/flat','title':'Flat','location':'8620 Nieuwpoort','photos':[]},
                {'id':'two','url':'https://two.example/flat','title':'Flat','location':'8620 Nieuwpoort','photos':[]}])
            page='<div class="property-map" data-long="2.71352" data-lat="51.1461"></div>'
            def fetch(url):
                if 'one.example' in url:raise OSError('temporary failure')
                return page
            with patch('gallery_enrichment.DATA',data),patch('gallery_enrichment.CACHE',data/'photo-cache.json'),\
                 patch('gallery_enrichment.source_robots_ok',return_value=True),\
                 patch('gallery_enrichment.fetch',side_effect=fetch),\
                 patch('gallery_enrichment.time.sleep'),patch('beach_distance.persist_geocodes'):
                result=enrich_galleries(modes=('coast',),limit=2)
            rows=json.loads((data/'coast/listings.json').read_text())
            self.assertEqual(result['inspected'],1)
            self.assertGreater(next(row for row in rows if row['id']=='two')['beachDistanceM'],0)

    def test_requested_brussels_sites_are_checked_even_after_failed_audit(self):
        sites=[{'name':'Agency A','website':'https://a.example/','enabled':False,'auditStatus':'unavailable'},
               {'name':'Agency B','website':'https://b.example/','enabled':False,'auditStatus':'unavailable'}]
        def collect(site,mode,criteria):
            return [],{'source':site['name'],'ok':True,'found':0}
        with patch('brussels_agencies.seed',return_value=sites),patch('brussels_agencies.restricted_agency_domains',return_value=set()),patch('brussels_agencies.collect_site',side_effect=collect):
            rows,status=collect_brussels('rent',{},workers=2)
        self.assertEqual(rows,[])
        self.assertEqual({s['source'] for s in status},{'Agency A','Agency B'})

    def test_coastal_distance_uses_ad_text_and_published_map_coordinates(self):
        row={'title':'Appartement op 300 m van het strand','summary':''}
        add_beach_distance(row)
        self.assertEqual((row['beachDistanceM'],row['beachDistanceBasis']),(300,'listing-text'))
        html='<div class="property-map" data-long="2.71352" data-lat="51.1461"></div>'
        coordinates=extract_coordinates(html)
        self.assertEqual(coordinates,(51.1461,2.71352))
        mapped={'title':'Appartement','summary':'','latitude':coordinates[0],'longitude':coordinates[1]}
        add_beach_distance(mapped)
        self.assertGreater(mapped['beachDistanceM'],0)
        self.assertEqual(mapped['beachDistanceBasis'],'straight-line-estimate')

    def test_coastal_detail_prefers_property_position_over_other_cards(self):
        page='''<a class="card" data-id="other" data-lat="51.0601" data-lon="3.1051"></a>
        <script type="application/ld&#x2B;json">{"@type":"RealEstateListing","mainEntity":{"@type":"Apartment","geo":{"latitude":51.1461,"longitude":2.71352}}}</script>'''
        self.assertEqual(extract_coordinates(page),(51.1461,2.71352))
        self.assertEqual(extract_coordinates('<a href="http://maps.google.com/maps?ll=51.1100539,2.7622898">plan</a>'),(51.1100539,2.7622898))

    def test_portanic_residence_is_located_without_a_street_address_in_the_ad(self):
        row={'title':'Appartement in Residentie Portanic te Nieuwpoort','summary':'',
             'location':'8620 Nieuwpoort'}
        add_beach_distance(row)
        self.assertEqual(row['beachLocationBasis'],'verified-residence')
        self.assertEqual(row['beachDistanceM'],1750)
        self.assertNotIn('beachWalkMinutes',row)

    def test_coastal_address_in_description_locates_other_ads_in_same_residence(self):
        self.assertEqual(extract_address_from_text('Studio te koop Nieuwpoort Franslaan 100 27m²'),'Franslaan 100')
        self.assertEqual(extract_address_from_url('https://agency.test/nieuwpoort/onze-lieve-vrouwstraat-43-3/7583003'),'Onze Lieve Vrouwstraat 43')
        self.assertEqual(extract_detail_address('<a href="http://maps.google.com/?q=Franslaan+100">Franslaan 100, 8620 Nieuwpoort</a>'),'Franslaan 100')
        rows=[{'title':'Appartement Santhooft','summary':'Henegouwenstraat 17 E02.05 Santhooft, 8620 Nieuwpoort','location':'8620 Nieuwpoort'},
              {'title':'Res. Santhooft 0502','summary':'Residentie Santhooft C 0502','location':'8620 Nieuwpoort'}]
        with patch('beach_distance._geocode',return_value=(51.15,2.72)),patch('beach_distance.persist_geocodes'):
            enrich_coastal_locations(rows)
        self.assertEqual(rows[0]['streetAddress'],'Henegouwenstraat 17')
        self.assertEqual(rows[1]['beachLocationBasis'],'matched-residence')
        self.assertEqual(rows[0]['beachDistanceM'],rows[1]['beachDistanceM'])

    def test_coastal_agency_card_keeps_asking_price_and_district(self):
        card="""<a class='pand-wrapper' href='/detail/te-koop-appartement-middelkerke/7699972'>
        <img data-src='https://example.be/flat.jpg'>
        Residentie: 2000 · 58 m² · Middelkerke - Appartement · € 350 000
        </a>"""
        rows=parse_catalogue(card,'https://www.becue.be/te-koop','sale',
                             {'name':'Bécue','website':'https://www.becue.be','coastal':True})
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['price'],350000)
        self.assertEqual(rows[0]['location'],'8430 Middelkerke')

    def test_coastal_catalogue_follows_numbered_and_head_pagination(self):
        html="""<a class='yw-page-btn' href='/aanbod/te-koop?page=2'>2</a>
        <link rel='next' href='/aanbod/te-koop?page=3'>"""
        self.assertEqual(pagination(html,'https://example.be/aanbod/te-koop'),[
            'https://example.be/aanbod/te-koop?page=2',
            'https://example.be/aanbod/te-koop?page=3'])

    def test_personal_fields_and_error_paths_are_not_exported(self):
        row={'id':'one','title':'Appartement','url':'https://example.be/ad/one','price':950,'renovationOverride':{'low':123},'privateNote':'SECRET','features':{'terrace':True,'secret':'SECRET'},'photos':['https://example.be/room.jpg']}
        clean=sanitize_row(row)
        self.assertNotIn('renovationOverride',clean)
        self.assertNotIn('SECRET',json.dumps(clean))
        status=sanitize_status({'lastRun':'2026-10-22T10:00:00+02:00','error':'/Users/PRIVATE/path','sources':[{'source':'Agency','ok':False,'domain':'agency.be','reason':'PRIVATE','token':'SECRET'},{'source':'Other','domain':'PRIVATE/path'}]})
        self.assertNotIn('PRIVATE',json.dumps(status));self.assertNotIn('SECRET',json.dumps(status))
        self.assertEqual(status['sources'][0]['domain'],'agency.be')
        self.assertNotIn('domain',status['sources'][1])

    def test_build_uses_neutral_preferences_preserves_dates_and_excludes_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);data=folder/'data';site=folder/'site';state=folder/'state'
            for m in ('rent','sale','coast'):
                write(data/m/'criteria.json',{'maxBudget':1234,'private':'SECRET'})
                write(data/m/'listings.json',[{'id':'active','url':'https://example.be/a','title':'Appartement','location':'1050 Ixelles','price':950,'area':80,'bedrooms':2,'firstDiscovered':'2026-10-01','photos':[]},{'id':'stale','stale':True,'firstDiscovered':'2026-09-01'}])
                write(data/m/'status.json',{'lastRun':'2026-10-22T10:00:00+02:00','state':'partial'})
            files=build(site,data,state)
            manifest=json.loads((site/'data/manifest.json').read_text())
            self.assertEqual(manifest['config']['defaults']['rent']['maxBudget'],'')
            for m in ('rent','sale','coast'):
                rows=json.loads((site/'data'/files[m]).read_text())['items']
                self.assertEqual([r['id'] for r in rows],['active'])
                self.assertEqual(rows[0]['firstDiscovered'],'2026-10-01')
                self.assertEqual(len(json.loads((state/(m+'.json')).read_text())['items']),2)
            html=(site/'index.html').read_text()
            self.assertNotIn('src="/app.js"',html);self.assertIn('src="api.js"',html)
            self.assertFalse((site/'data/rent/criteria.json').exists())
            self.assertIn('De Panne',manifest['config']['defaults']['coast']['areas'])

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
