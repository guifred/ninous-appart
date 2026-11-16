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
from energy_detail import extract_detail_energy, energy_badge_images, _ocr_rating, _ocr_text
from agency_parsers import Tree
from model import normalize_listing
from model import extract_energy_rating
from coast_agencies import parse_beguin_detail, collect_beguin

class PublicExportTests(unittest.TestCase):
    def test_new_nieuwpoort_agencies_keep_photos_and_epc(self):
        listing='https://immodekaai.be/nl/aanbod/4481438/appartement-te-koop-in-8620-nieuwpoort'
        page=f'''<div class="estate-item"><a href="{listing}"><img src="https://thumbs.zabun.be/abc=/600x400/filters:image-format(pjpg)/3530/photo.jpg/Foobar"><img src="/img/energy/epc/a.svg" alt="epc waarde a"></a><a href="{listing}">Appartement te koop 1 slaapkamer(s) 8620 Nieuwpoort € 210.000</a></div>'''
        site={'name':'Immo de Kaai','website':'https://immodekaai.be','coastal':True}
        rows=parse_catalogue(page,'https://immodekaai.be/nl/te-koop','sale',site)
        self.assertEqual(len(rows),1)
        normalized=normalize_listing(rows[0],'coast')
        self.assertEqual(normalized['energyRating'],'A')
        self.assertEqual(len(normalized['photos']),1)
        self.assertEqual(extract_energy_rating('alt="epc waarde aplus"'),'A+')
        beguin='''<meta property="og:title" content="Appartement met 3 slpk"><meta property="og:image" content="https://example.be/flat.jpg"><input name="propertyAddress" value="Henegouwenstraat 10, 8620 NIEUWPOORT"><span>€ 285.000</span><div>Bewoonbare oppervlakte 55m² Aantal slaapkamers 3 EPC B</div>'''
        row=parse_beguin_detail(beguin,'https://www.immobeguin.be/te-koop/8620-nieuwpoort/appartement/flat-76271','https://www.immobeguin.be')
        self.assertEqual((row['price'],row['location'],row['energyRating']),(285000,'8620 Nieuwpoort','B'))

    def test_beguin_daily_sitemap_limits_collection_to_selected_city(self):
        home='https://www.immobeguin.be'
        sitemap=home+'/sitemaps-1-section-properties-1-sitemap-p1.xml'
        target=home+'/te-koop/8620-nieuwpoort/appartement/flat-76271'
        other=home+'/te-koop/8400-oostende/appartement/flat-98765'
        pages={home+'/sitemaps-1-sitemap.xml':f'<sitemapindex><sitemap><loc>{sitemap}</loc></sitemap></sitemapindex>',
               sitemap:f'<urlset><url><loc>{target}</loc></url><url><loc>{other}</loc></url></urlset>',
               target:'<meta property="og:title" content="Appartement"><input name="propertyAddress" value="Henegouwenstraat 10, 8620 NIEUWPOORT"><span>€ 285.000</span><p>EPC B</p>'}
        with patch('coast_agencies._robots',return_value=(True,'')),\
             patch('coast_agencies._fetch',side_effect=lambda url:(pages[url],{})) as fetch,\
             patch('coast_agencies.time.sleep'):
            rows,status=collect_beguin({'areas':'Nieuwpoort','property':'Apartment or house'},home)
        self.assertTrue(status['ok'])
        self.assertEqual((len(rows),rows[0]['energyRating']),(1,'B'))
        self.assertNotIn(other,[call.args[0] for call in fetch.call_args_list])

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
        self.assertEqual(extract_detail_energy('<div><span>EPC Label</span><span><img src="/assets/epc-label-b.svg"></span></div>'),'B')
        self.assertEqual(extract_detail_energy('<dl><dt>EPC label</dt><dd><svg><text>C</text></svg></dd></dl>'),'C')
        self.assertEqual(extract_detail_energy('<p>EPC: 286 (Label C).</p>'),'C')
        self.assertIsNone(extract_detail_energy('<p>EPC: 286 kWh/m².</p>'))
        # Immo Group-S publishes the class as an opaque Omnicasa badge image.
        group_s='''<div class="caption">Energie certificaat</div><div class="content">
          <div class="field">EPC No.20210412-0002400295-RES-1</div>
          <div class="field"><div class="name">E-peil</div><div class="value">0</div></div>
          <div class="field"><div class="name">EPC</div><div class="sep">:</div><div class="value">188 kWh/m&sup2;.jaar</div></div>
          <div class="field"><div class="name">EPC label</div><div class="sep">:</div><div class="value"><img src="https://epclabel.omnicasa.com/images/EPClabel/peb_10003.png" title="EPClabel"></div></div>
          </div>'''
        self.assertEqual(extract_detail_energy(group_s),'B')
        self.assertIsNone(extract_detail_energy('<div>EPC : 188 kWh/m².jaar</div>'))

    def test_epc_badge_with_opaque_image_name_uses_visual_reading(self):
        page='<div><span>EPC label :</span><img src="/uploads/certificate-4821.png" alt="EPC"></div>'
        with patch('energy_detail.read_energy_image',return_value='B') as read:
            self.assertEqual(extract_detail_energy(page,'https://agency.example/property/1'),'B')
        read.assert_called_once_with('https://agency.example/uploads/certificate-4821.png')
        self.assertEqual(_ocr_rating('EPC\nB'),'B')
        self.assertEqual(_ocr_rating('B'),'B')
        self.assertEqual(energy_badge_images(Tree('<img src="/uploads/room.png" alt="Living room">').root,'https://agency.example/'),[])

    def test_tesseract_output_is_used_when_available(self):
        completed=type('Completed',(),{'returncode':0,'stdout':'EPC\nB'})()
        with patch('energy_detail.shutil.which',return_value='/usr/bin/tesseract'),\
             patch('energy_detail.subprocess.run',return_value=completed) as run:
            self.assertEqual(_ocr_rating(_ocr_text('/tmp/epc.png')),'B')
        self.assertEqual(run.call_args.args[0],['tesseract','/tmp/epc.png','stdout','--psm','6'])

    def test_daily_enrichment_adds_epc_class_found_only_in_badge_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=Path(tmp);write(data/'coast/status.json',{'state':'partial'})
            write(data/'coast/listings.json',[{'id':'epc-image','url':'https://agency.example/flat/123',
                'title':'Appartement','location':'8620 Nieuwpoort','postalCode':'8620','photos':[],
                'beachDistanceM':250}])
            page='<div><span>EPC label :</span><img src="/uploads/certificate-4821.png" alt="EPC"></div>'
            with patch('gallery_enrichment.DATA',data),patch('gallery_enrichment.CACHE',data/'photo-cache.json'),\
                 patch('gallery_enrichment.source_robots_ok',return_value=True),\
                 patch('gallery_enrichment.fetch',return_value=page),\
                 patch('energy_detail.read_energy_image',return_value='B'),\
                 patch('gallery_enrichment.time.sleep'):
                enrich_galleries(modes=('coast',),limit=1)
            row=json.loads((data/'coast/listings.json').read_text())[0]
            self.assertEqual((row['energyRating'],row['energyRegion']),('B','EPC · Flandre'))

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
