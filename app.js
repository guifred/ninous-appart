const MODES=['rent','sale','coast'];
const featureNames={terrace:'Terrasse',balcony:'Balcon',garden:'Jardin',parking:'Parking / garage',lift:'Ascenseur',cellar:'Cave',accessible:'Accessible PMR',petsAllowed:'Animaux acceptés',furnished:'Meublé'};
const scopeNames={ready:'Prêt à emménager',cosmetic:'Rafraîchissement / cosmétique',partial:'Rénovation partielle',full:'Rénovation complète'};
const componentNames={finishes:'Finitions',kitchen:'Cuisine',bathroom:'Salle de bain',electricity:'Électricité',plumbing:'Plomberie',heating:'Chauffage',insulation:'Isolation'};
const brusselsCommunes=[['Anderlecht','1070'],['Auderghem','1160'],['Berchem-Sainte-Agathe','1082'],['Bruxelles-Ville','1000'],['Etterbeek','1040'],['Evere','1140'],['Forest','1190'],['Ganshoren','1083'],['Ixelles','1050'],['Jette','1090'],['Koekelberg','1081'],['Molenbeek-Saint-Jean','1080'],['Saint-Gilles','1060'],['Saint-Josse-ten-Noode','1210'],['Schaerbeek','1030'],['Uccle','1180'],['Watermael-Boitsfort','1170'],['Woluwe-Saint-Lambert','1200'],['Woluwe-Saint-Pierre','1150']];
const coastCommunes=[['De Panne','8660'],['Koksijde','8670'],['Nieuwpoort','8620'],['Middelkerke','8430'],['Oostende','8400'],['Bredene','8450'],['De Haan','8420'],['Blankenberge','8370'],['Zeebrugge','8380'],['Knokke-Heist','8300']];
const foldArea=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
let mode='rent',criteria={},modeCriteria={rent:{},sale:{},coast:{}},page=1,pageSize=24,total=0,excludedLoaded=false,currentView='list',mapInstance=null,mapLayer=null;
let favorites=(()=>{try{return JSON.parse(localStorage.getItem('ninou-favorites-v1')||'[]')}catch{return []}})();
const $=id=>document.getElementById(id),esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const sourceHomepages={Immovlan:'immovlan.be',Biddit:'biddit.be','Easy Properties':'easyproperties.be','Red Immobilier':'redimmobilier.be',Sorimo:'sorimo.be','Régie Foncière de Bruxelles':'regiefonciere.bruxelles.be'};
let sourceCountsForMode={rent:[],sale:[],coast:[]},sourceStatusForMode={rent:[],sale:[],coast:[]},hiddenStaleForMode={rent:0,sale:0,coast:0};
function sourceUrl(name,domain){const host=domain||sourceHomepages[name];return typeof host==='string'&&/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(host)?'https://'+host:null}
function renderSourceCoverage(){
 const container=$('sourceCoverage'),counts=new Map(sourceCountsForMode[mode]||[]),grouped=new Map();
 for(const row of sourceStatusForMode[mode]||[]){if(!row?.source)continue;const item=grouped.get(row.source)||{name:row.source,domain:null,ok:false,partial:false,found:0,failed:false};item.domain ||= row.domain;item.ok ||= row.ok===true;item.partial ||= row.partial===true;item.failed ||= row.ok===false;item.found+=Number(row.found)||0;grouped.set(row.source,item)}
 for(const [name] of counts)if(!grouped.has(name))grouped.set(name,{name,domain:null,ok:true,partial:false,found:0,failed:false});
 const all=[...grouped.values()].sort((a,b)=>(counts.get(b.name)||0)-(counts.get(a.name)||0)||a.name.localeCompare(b.name,'fr'));
 const matching=all.filter(x=>counts.get(x.name)>0),checked=all.filter(x=>!counts.get(x.name)&&x.ok),unavailable=all.filter(x=>!x.ok);
 const chip=x=>{const count=counts.get(x.name)||0,url=sourceUrl(x.name,x.domain),label=esc(x.name)+(count?'<span class="source-count">'+count+'</span>':'');return url?'<a class="source-chip" href="'+esc(url)+'" target="_blank" rel="noopener noreferrer" title="Site de '+esc(x.name)+'">'+label+' <span aria-hidden="true">↗</span></a>':'<span class="source-chip">'+label+'</span>'};
 const detail=(title,items,extraClass='')=>items.length?'<details class="source-details '+extraClass+'"><summary>'+title+' <strong>'+items.length+'</strong></summary><div class="source-chips">'+items.map(chip).join('')+'</div></details>':'';
 if(!all.length){container.hidden=true;container.innerHTML='';return}
 const stale=hiddenStaleForMode[mode]||0;
 container.innerHTML='<div class="source-heading"><div><span class="source-kicker">TRANSPARENCE DES RÉSULTATS</span><h3>Agences et sites consultés</h3></div><span class="source-total">'+all.length+' source'+(all.length>1?'s':'')+'</span></div>'+
  '<p class="source-explain">'+(matching.length?'Ces sites proposent des annonces qui correspondent à vos filtres. Le nombre indique les annonces correspondantes par site.':'Aucun site ne propose actuellement d’annonce correspondant à vos filtres.')+'</p>'+
  (matching.length?'<div class="source-chips">'+matching.map(chip).join('')+'</div>':'')+
  detail('Sites vérifiés sans annonce correspondante',checked)+detail('Sites indisponibles lors de la dernière collecte',unavailable,'source-unavailable')+
  (stale?'<p class="source-stale">'+stale+' annonce'+(stale>1?'s':'')+' non vérifiée'+(stale>1?'s':'')+' masquée'+(stale>1?'s':'')+'.</p>':'');
 container.hidden=false;
}
const money=v=>v===null||v===undefined?'—':Number(v).toLocaleString('fr-BE',{maximumFractionDigits:0})+' €';
const val=v=>v===null||v===undefined?'':v;
function toast(text,error=false){const t=$('toast');t.textContent=text;t.style.background=error?'#9d423c':'#26392e';t.classList.add('show');setTimeout(()=>t.classList.remove('show'),2700)}
function setMode(next,hash=true){mode=MODES.includes(next)?next:'rent';page=1;excludedLoaded=false;document.querySelectorAll('.mode-tab').forEach(b=>{const on=b.dataset.mode===mode;b.classList.toggle('active',on);b.setAttribute('aria-selected',String(on))});if(hash)history.replaceState(null,'','#'+mode);$('collectionLabel').textContent=mode==='rent'?'ANNONCES À LOUER':mode==='coast'?'APPARTEMENTS ET MAISONS À VENDRE À LA MER':'ANNONCES À VENDRE';$('heroKicker').textContent=mode==='rent'?'VOTRE RECHERCHE · LOCATION':mode==='coast'?'VOTRE RECHERCHE · CÔTE BELGE':'VOTRE RECHERCHE · ACHAT';$('heroTitle').textContent=mode==='rent'?'À louer à Bruxelles':mode==='coast'?'À acheter à la mer':'À acheter à Bruxelles';$('matchTitle').textContent=mode==='rent'?'Les annonces qui vous correspondent':'Les biens qui respectent votre budget';$('resultsSub').textContent=mode==='rent'?'Les annonces les plus proches de vos envies.':'Prix, surface et budget rénovation estimatif.';document.title='Ninou’s appart · '+(mode==='coast'?'Côte belge':'Bruxelles');document.querySelector('.brand em').textContent=mode==='coast'?'Côte belge':'Bruxelles';document.querySelector('.footer span').textContent='Ninou’s appart · Votre recherche immobilière '+(mode==='coast'?'à la côte belge':'à Bruxelles');loadMode()}
document.querySelectorAll('.mode-tab').forEach(b=>b.onclick=()=>setMode(b.dataset.mode));
function field(label,key,type='text',placeholder='',attrs=''){return '<div class="field"><label for="f-'+key+'">'+label+'</label><input id="f-'+key+'" name="'+key+'" type="'+type+'" placeholder="'+placeholder+'" '+attrs+'></div>'}
function selectField(label,key,options){return '<div class="field"><label for="f-'+key+'">'+label+'</label><select id="f-'+key+'" name="'+key+'">'+options.map(x=>'<option value="'+esc(x[0])+'">'+esc(x[1])+'</option>').join('')+'</select></div>'}
function rangeFields(label,key1,key2,placeholder1,placeholder2){return '<div class="field"><label>'+label+'</label><div class="range"><input id="f-'+key1+'" name="'+key1+'" type="number" min="0" placeholder="'+placeholder1+'"><span>—</span><input id="f-'+key2+'" name="'+key2+'" type="number" min="0" placeholder="'+placeholder2+'"></div></div>'}
function municipalityField(){const coastal=mode==='coast',label=coastal?'Communes de la côte belge':'Communes de Bruxelles',places=coastal?coastCommunes:brusselsCommunes;return '<div class="field"><div class="field-label">'+label+'</div><div class="municipality-actions"><button type="button" data-area-all>Tout sélectionner</button><button type="button" data-area-none>Tout effacer</button></div><div class="municipality-list" role="group" aria-label="'+label+'">'+places.map(([name,postal])=>'<label class="choice"><input type="checkbox" name="areas" value="'+esc(name)+'" data-postal="'+postal+'">'+esc(name)+'</label>').join('')+'</div><small>Cochez une ou plusieurs communes pour votre recherche.</small></div>'}
function featureFields(){return '<div class="field"><label>Équipements et critères</label>'+Object.entries(featureNames).filter(([k])=>mode==='rent'||k!=='furnished').map(([key,name])=>'<div class="range" style="margin:5px 0"><span style="flex:1;font-size:10px">'+name+'</span><select name="feature-'+key+'" aria-label="'+name+'"><option value="">Indifférent</option><option value="true">Oui</option><option value="false">Non</option></select></div>').join('')+'</div>'}
function subtypeFields(){return '<div class="field"><label for="f-property">Type principal</label><select id="f-property" name="property"><option value="Apartment">Appartement</option><option value="House">Maison</option><option value="Apartment or house">Appartement ou maison</option></select><small>Les studios, duplex, penthouses et lofts restent des appartements.</small></div><div class="field"><label>Sous-types souhaités <small>(aucun = tous)</small></label><div class="check-grid">'+['Studio','Duplex','Penthouse','Loft'].map(x=>'<label class="choice"><input type="checkbox" name="subtypes" value="'+x+'">'+x+'</label>').join('')+'</div></div>'}
function renderCriteriaForm(c){criteria=c||{};let x='';x+=municipalityField();x+=rangeFields(mode==='rent'?'Loyer mensuel (€)':'Prix demandé (€)',mode==='rent'?'minBudget':'minPrice',mode==='rent'?'maxBudget':'maxPrice','Minimum','Maximum');x+=rangeFields('Surface habitable (m²)','minArea','maxArea','Min.','Max.');x+=selectField('Chambres','bedrooms',[['','Indifférent'],['0','Studio (0)'],['1','1+'],['2+','2+'],['3+','3+'],['4+','4+']]);x+=subtypeFields();x+=featureFields();x+='<details class="advanced"><summary>Critères avancés</summary>';
 if(mode==='rent'){
  x+=selectField('Budget calculé sur','budgetBasis',[['rent','Loyer seul'],['rent_and_charges','Loyer + charges mensuelles connues']]);
  x+=selectField('Meublé','furnished',[['any','Indifférent'],['furnished','Meublé'],['unfurnished','Non meublé']]);
  x+=field('Date d’emménagement','moveDate','text','Flexible ou JJ/MM/AAAA');
  x+=field('Indispensables (séparés par virgule)','mustHaves','text','Ex. terrasse, animaux');
 }else{
  x+=field('Prix maximum par m² (€)','maxPricePerM2','number','€/m² maximum','min="0"');
  x+=field('Charges mensuelles de copropriété maximum (€)','maxCondoFees','number','€/mois maximum','min="0"');
  x+=selectField('Construction','construction',[['any','Indifférent'],['new','Neuf / nouvelle construction'],['existing','Existant']]);
  x+=selectField('État déclaré','condition',[['any','Indifférent'],['good','Bon état'],['renovated','Rénové'],['renovation','À rénover']]);
  x+=selectField('Occupation','occupancy',[['any','Indifférent'],['vacant','Libre / vacant'],['occupied','Occupé / loué']]);
 }
 x+=rangeFields('Étage','floorMin','floorMax','Min.','Max.');
 x+=selectField('Classe énergétique (indicative)','energyRating',[['any','Indifférent'],['A','A'],['B','B'],['C','C'],['D','D'],['E','E'],['F','F'],['G','G']]);
 x+=field('Publication au cours des derniers jours','publicationDays','number','Indifférent','min="1" max="3650"');
 x+='</details>';
 if(mode!=='rent'){
  x+='<div class="renovation-settings"><h3>Budget travaux · critère clé</h3>';
  x+=selectField('Scénario de rénovation','renovationScope',Object.entries(scopeNames));
  x+=rangeFields('Hypothèse de coût par m² (hors TVA)','renovationRateLow','renovationRateHigh','Minimum €/m²','Maximum €/m²');
  x+='<small>Valeurs modifiables. Les fourchettes source sont des scénarios indicatifs, pas un devis.</small>';
  x+=rangeFields('Maximum rénovation / total achat + travaux (€)','maxRenovation','maxCombined','Budget travaux','Total maximum');
  x+='<label class="choice"><input type="checkbox" name="includeUnknownRenovation">Inclure les budgets travaux inconnus pour vérification</label>';
  x+=field('Provision imprévus (%)','contingencyPct','number','15','min="0" max="50"');
  x+=selectField('TVA supposée sur travaux','vatPct',[['21','21 % · hypothèse prudente'],['6','6 % · sous conditions']]);
  x+='<small>Le 6 % n’est appliqué que comme hypothèse choisie; l’éligibilité doit être confirmée. La classe énergie et l’état déclaré signalent des vérifications à demander; aucune réparation cachée n’est déduite.</small></div>';
 }
 if(mode!=='coast')x+='<div class="field"><label><input type="checkbox" name="nearby"> Inclure les communes voisines</label></div>';
 $('criteriaFields').innerHTML=x;
 const f=$('criteriaForm');Object.entries(c).forEach(([k,v])=>{const el=f.elements.namedItem(k);if(el&&el.type!=='checkbox'&&!(el instanceof RadioNodeList))el.value=val(v)});
 const savedAreas=Array.isArray(c.areas)?c.areas:String(c.areas||'').split(/[,;\n]/).map(s=>s.trim()).filter(Boolean);f.querySelectorAll('[name="areas"]').forEach(el=>{el.checked=savedAreas.some(a=>foldArea(a)===foldArea(el.value)||String(a).includes(el.dataset.postal))});
 f.querySelector('[data-area-all]').onclick=()=>f.querySelectorAll('[name="areas"]').forEach(el=>el.checked=true);f.querySelector('[data-area-none]').onclick=()=>f.querySelectorAll('[name="areas"]').forEach(el=>el.checked=false);
 if(c.nearby!==false&&f.elements.nearby)f.elements.nearby.checked=true;
 if(c.includeUnknownRenovation&&f.elements.includeUnknownRenovation)f.elements.includeUnknownRenovation.checked=true;
 if(mode!=='rent'){
  const rates={ready:[0,250],cosmetic:[400,800],partial:[800,1500],full:[1500,2500]},scope=f.elements.renovationScope?.value||'cosmetic';
  if(f.elements.renovationRateLow&&val(c.renovationRateLow)==='')f.elements.renovationRateLow.value=rates[scope][0];
  if(f.elements.renovationRateHigh&&val(c.renovationRateHigh)==='')f.elements.renovationRateHigh.value=rates[scope][1];
  f.elements.renovationScope?.addEventListener('change',()=>{f.elements.renovationRateLow.value=rates[f.elements.renovationScope.value][0];f.elements.renovationRateHigh.value=rates[f.elements.renovationScope.value][1]});
 }
 (Array.isArray(c.subtypes)?c.subtypes:[]).forEach(v=>{const el=[...f.querySelectorAll('[name="subtypes"]')].find(e=>e.value===v);if(el)el.checked=true});
 const features=c.features||{};Object.entries(featureNames).forEach(([k])=>{const el=f.elements.namedItem('feature-'+k);if(el)el.value=features[k]===true?'true':features[k]===false?'false':''});
}
function collectCriteria(){const f=$('criteriaForm'),c={...criteria};for(const el of f.querySelectorAll('[name]')){const k=el.name;if(k.startsWith('feature-'))continue;if(k==='subtypes'||k==='areas')continue;if(k==='nearby'||k==='includeUnknownRenovation')c[k]=el.checked;else if(el.type==='number')c[k]=el.value===''?'':Number(el.value);else c[k]=el.value}
 c.areas=[...f.querySelectorAll('[name="areas"]:checked')].map(e=>e.value).join(', ');c.subtypes=[...f.querySelectorAll('[name="subtypes"]:checked')].map(e=>e.value);c.features={};Object.keys(featureNames).forEach(k=>{const el=f.elements.namedItem('feature-'+k);if(el&&el.value!=='')c.features[k]=el.value==='true'});return c}
function immowebSearchUrl(c,transaction,area){const property=c.property==='House'?'maison':c.property==='Apartment or house'?'maison-et-appartement':'appartement';const action=transaction==='rent'?'a-louer':'te-koop';const place=area?foldArea(area[0]).replace(/\s+/g,'-')+'/'+area[1]:(transaction==='rent'?'brussels/arrondissement':'bruxelles/arrondissement');const params=new URLSearchParams();const min=transaction==='rent'?c.minBudget:c.minPrice,max=transaction==='rent'?c.maxBudget:c.maxPrice;if(min!==''&&min!==undefined)params.set('minPrice',String(min));if(max!==''&&max!==undefined)params.set('maxPrice',String(max));const beds=String(c.bedrooms??'');if(beds){const count=Number(beds.replace('+',''));if(Number.isFinite(count)){params.set('minBedroomCount',String(count));if(beds==='0')params.set('maxBedroomCount','0');params.set('searchByRooms','1')}}if(c.minArea!==''&&c.minArea!==undefined)params.set('minSurface',String(c.minArea));if(c.maxArea!==''&&c.maxArea!==undefined)params.set('maxSurface',String(c.maxArea));const query=params.toString();return 'https://www.immoweb.be/fr/recherche/'+property+'/'+action+'/'+place+(query?'?'+query:'')}
function renderImmowebChoices(){const c=collectCriteria(),values=String(c.areas||'').split(/[,;\n]/).map(x=>x.trim()).filter(Boolean),places=mode==='coast'?coastCommunes:brusselsCommunes;const areas=values.map(value=>places.find(([name])=>foldArea(name)===foldArea(value))||places.find(([,postal])=>postal===value)).filter(Boolean);const distinct=[...new Map(areas.map(a=>[a[1],a])).values()];const choices=distinct.length?distinct:[null];$('immowebLinks').innerHTML=choices.map(area=>'<a href="'+esc(immowebSearchUrl(c,mode,area))+'" target="_blank" rel="noopener noreferrer">'+(area?esc(area[0]+' · '+area[1]):mode==='coast'?'Côte belge':'Bruxelles · toutes les communes')+' ↗</a>').join('')}
function budgetKeys(){return mode==='rent'?['minBudget','maxBudget',2000,50]:['minPrice','maxPrice',2000000,10000]}
function syncBudgetControls(c=criteria){const [minKey,maxKey,cap,step]=budgetKeys(),lo=$('budgetMinRange'),hi=$('budgetMaxRange');for(const el of [lo,hi]){el.max=String(cap);el.step=String(step)}let min=c[minKey]===''||c[minKey]===undefined?0:Math.max(0,Number(c[minKey])),max=c[maxKey]===''||c[maxKey]===undefined?cap:Math.min(cap,Number(c[maxKey]));if(min>max)min=max;lo.value=String(Math.round(min/step)*step);hi.value=String(Math.round(max/step)*step);$('budgetOutput').textContent=Number(lo.value).toLocaleString('fr-BE')+' – '+Number(hi.value).toLocaleString('fr-BE')+' €';const f=$('criteriaForm');if(f.elements.namedItem(minKey))f.elements.namedItem(minKey).value=min===0?'':String(min);if(f.elements.namedItem(maxKey))f.elements.namedItem(maxKey).value=max===cap?'':String(max)}
function updateBudgetFromRange(changed){const [minKey,maxKey,cap,step]=budgetKeys(),lo=$('budgetMinRange'),hi=$('budgetMaxRange');let min=Number(lo.value),max=Number(hi.value);if(min>max){if(changed==='min')max=min;else min=max}lo.value=String(min);hi.value=String(max);const f=$('criteriaForm');if(f.elements.namedItem(minKey))f.elements.namedItem(minKey).value=min===0?'':String(min);if(f.elements.namedItem(maxKey))f.elements.namedItem(maxKey).value=max===cap?'':String(max);const c=collectCriteria();criteria=c;modeCriteria[mode]=c;$('budgetOutput').textContent=min.toLocaleString('fr-BE')+' – '+max.toLocaleString('fr-BE')+' €';$('saveState').textContent='À enregistrer'}
$('budgetMinRange').addEventListener('input',()=>updateBudgetFromRange('min'));$('budgetMaxRange').addEventListener('input',()=>updateBudgetFromRange('max'));
async function persistCurrentCriteria(){const next=collectCriteria(),r=await fetch('/api/criteria?mode='+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(next)}),d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Le serveur a refusé les critères.');criteria=d.criteria;modeCriteria[mode]=criteria;$('saveState').textContent='Enregistrés';return criteria}
$('criteriaForm').onsubmit=async ev=>{ev.preventDefault();const btn=$('saveBtn');btn.disabled=true;$('saveState').textContent='Enregistrement…';try{await persistCurrentCriteria();await loadListings(true);toast('Critères enregistrés. La collecte les utilisera au prochain lancement.')}catch(e){$('saveState').textContent='Erreur';toast('Échec de l’enregistrement : '+e.message,true)}finally{btn.disabled=false}};
function updateHeroAreas(c){const areas=Array.isArray(c.areas)?c.areas:String(c.areas||'').split(/[,;\n]/).map(s=>s.trim()).filter(Boolean);const areaLabel=areas.length===1?areas[0]:areas.length?areas.length+' communes sélectionnées':'Choisissez vos communes dans « Vos critères »';$('heroMeta').textContent=areaLabel;$('heroMeta').title=areas.join(' · ');const details=[];const price=c[mode==='rent'?'maxBudget':'maxPrice'];if(price!==''&&price!==undefined)details.push((mode==='rent'?'Loyer max. ':'Prix max. ')+money(price));if(c.minArea)details.push('Dès '+c.minArea+' m²');if(c.bedrooms!==''&&c.bedrooms!==undefined)details.push((c.bedrooms==='0'?'Studio':String(c.bedrooms).replace(/\+$/,'')+'+ ch.'));$('heroText').textContent=details.length?details.join(' · '):'Définissez budget, surface et chambres dans « Vos critères ».'}
function saveResultSort(){try{localStorage.setItem('ninou-result-sort-'+mode,$('resultsSort').value)}catch{}}
function restoreResultSort(){const allowed=['relevance','price_asc','price_desc','discovered_desc','discovered_asc','published_desc','published_asc','area_asc','area_desc','bedrooms_asc','bedrooms_desc'];let saved='relevance';try{saved=localStorage.getItem('ninou-result-sort-'+mode)||saved}catch{}$('resultsSort').value=allowed.includes(saved)?saved:'relevance'}
function resultSortQuery(){return encodeURIComponent($('resultsSort').value||'relevance')}
$('resultsSort').addEventListener('change',()=>{saveResultSort();loadListings(true).catch(e=>toast('Tri impossible : '+e.message,true))});
function dateLabel(x){const d=x.publicationDate?new Date(x.publicationDate+'T12:00:00').toLocaleDateString('fr-BE'):'';if(x.publicationDateOrigin==='firstDiscovered')return d?'Date estimée · première détection le '+d:'Date de publication non précisée';const pub=d?((x.publicationDateUncertain?'Publié vers le ':'Publié le ')+d):'Date de publication non précisée';const found=x.firstDiscovered?' · Repéré le '+new Date(x.firstDiscovered+'T12:00:00').toLocaleDateString('fr-BE'):'';return pub+found}
function photoState(photo){let list=[];try{list=JSON.parse(photo.dataset.images||'[]')}catch{}return list.filter(Boolean)}
function showPhoto(photo,index){const list=photoState(photo),img=photo.querySelector('img:not(.agency-logo)');if(!list.length||!img)return;index=(index+list.length)%list.length;photo.dataset.index=String(index);photo.dataset.currentSrc=list[index];img.dataset.index=String(index);img.dataset.requestSrc=list[index];img.hidden=false;photo.querySelector('.photo-fallback').classList.remove('show');img.src=list[index];const count=photo.querySelector('.photo-count');if(count){count.textContent=(index+1)+' / '+list.length;count.hidden=false}photo.querySelectorAll('.photo-nav').forEach(b=>b.hidden=false)}
function photoFailure(img){const photo=img.closest('.photo');if(!photo||img.dataset.requestSrc!==photo.dataset.currentSrc)return;let list=photoState(photo);const failed=Number(photo.dataset.index||0);list.splice(failed,1);photo.dataset.images=JSON.stringify(list);if(list.length)showPhoto(photo,failed%list.length);else{img.hidden=true;photo.querySelector('.photo-fallback').classList.add('show');photo.querySelectorAll('.photo-nav,.photo-count').forEach(el=>el.hidden=true)}}
async function stepPhoto(photo,step){
 if(!photo)return;
 let list=photoState(photo);
 if(list.length>1){showPhoto(photo,Number(photo.dataset.index||0)+step);return}
 if(photo.dataset.galleryLoading==='true'){photo.dataset.pendingStep=String(step);return}
 if(photo.dataset.galleryChecked==='true'){toast('Une seule photo est disponible pour cette annonce.');return}
 photo.dataset.galleryLoading='true';photo.dataset.pendingStep=String(step);
 const count=photo.querySelector('.photo-count');if(count)count.textContent='Chargement…';
 photo.querySelectorAll('.photo-nav').forEach(b=>b.disabled=true);
 try{
  const r=await fetch('/api/photos?mode='+(photo.dataset.transaction||mode)+'&id='+encodeURIComponent(photo.dataset.listingId));
  const d=await r.json();if(!r.ok)throw new Error(d.error||'Galerie inaccessible');
  updateAgencyBrand(photo,d.branding);list=Array.isArray(d.photos)?d.photos:[];
  photo.dataset.images=JSON.stringify(list);photo.dataset.galleryChecked='true';
  if(list.length>1){const direction=Number(photo.dataset.pendingStep||step);showPhoto(photo,direction>0?1:list.length-1)}
  else{if(list.length)showPhoto(photo,0);if(count)count.textContent=list.length?'1 photo':'Photo indisponible';toast('Aucune autre photo disponible pour cette annonce.')}
 }catch(e){if(count)count.textContent=list.length?'1 photo':'Photo indisponible';toast('Galerie indisponible : '+e.message,true)}
 finally{delete photo.dataset.galleryLoading;delete photo.dataset.pendingStep;photo.querySelectorAll('.photo-nav').forEach(b=>b.disabled=false)}
}
function typeOf(x){const s=foldArea(x.title||'');if(s.includes('studio'))return 'Studio';if(s.includes('duplex'))return 'Duplex';if(s.includes('penthouse'))return 'Penthouse';if(s.includes('loft'))return 'Loft';if(x.propertyType==='House'||/\b(?:maison|woning|huis|villa|house)\b/.test(s))return 'Maison';return 'Appartement'}
function renovationMarkup(x){const r=x.renovation||{};if(!r.low&&r.low!==0)return '<div class="reno-simple"><strong>Budget rénovation à confirmer</strong></div>';const agency=x.agencyRenovationEstimate?'<span class="reno-simple-note"> · Estimation de l’agence : '+esc(x.agencyRenovationEstimate)+'</span>':'';const origin=r.source==='agency'?'Estimation de l’agence':r.scenario?'Scénario indicatif':'Estimation indicative';return '<div class="reno-simple"><strong>Rénovation estimée : '+money(r.low)+' – '+money(r.high)+'</strong><span class="reno-simple-note">'+esc(origin)+' · '+esc(scopeNames[r.scope]||'scénario')+' · '+esc(r.confidence||'incertitude élevée')+'</span>'+agency+'</div>'}
function favoriteKey(x,cardMode=mode){return (x.transaction||cardMode)+':'+String(x.id||'')}
function isFavorite(x,cardMode=mode){const key=favoriteKey(x,cardMode);return favorites.some(f=>favoriteKey(f,f.transaction||cardMode)===key)}
function persistFavorites(){try{localStorage.setItem('ninou-favorites-v1',JSON.stringify(favorites))}catch(e){toast('Impossible d’enregistrer les favoris sur cet appareil.',true)}$('favoriteCount').textContent=String(favorites.length)}
let favoritesRenderToken=0;
async function renderFavorites(){const token=++favoritesRenderToken,box=$('favoriteResults'),candidates=favorites.filter(x=>!x.stale),valid=new Set(),fresh=new Map();box.innerHTML='<div class="panel" style="padding:18px">Vérification des annonces enregistrées…</div>';try{for(const tx of MODES){const rows=candidates.filter(x=>(x.transaction||'rent')===tx);for(let i=0;i<rows.length;i+=200){const ids=rows.slice(i,i+200).map(x=>String(x.id||'')).filter(Boolean);if(!ids.length)continue;const r=await fetch('/api/listing-validity?mode='+tx+'&ids='+encodeURIComponent(ids.join(',')));if(!r.ok)throw new Error('Vérification impossible');const d=await r.json();for(const id of d.validIds||[])valid.add(tx+':'+id);for(const row of d.items||[])fresh.set(tx+':'+row.id,row)}}if(token!==favoritesRenderToken)return;favorites=favorites.filter(x=>valid.has(favoriteKey(x,x.transaction||'rent'))).map(x=>({...x,...(fresh.get(favoriteKey(x,x.transaction||'rent'))||{}),savedAt:x.savedAt}));box.innerHTML=favorites.slice().reverse().map(x=>card(x,false,x.transaction||'rent')).join('');$('favoritesEmpty').hidden=favorites.length>0;persistFavorites();observeGalleries(box)}catch{if(token===favoritesRenderToken)box.innerHTML='<div class="panel" style="padding:18px">Impossible de vérifier vos annonces enregistrées pour le moment.</div>'}}
function toggleFavorite(button){const key=button.dataset.favoriteId;const index=favorites.findIndex(f=>favoriteKey(f,f.transaction||mode)===key);if(index>=0){favorites.splice(index,1);toast('Retiré de vos favoris.')}else{const record=window.__listingRecords?.[key];if(!record){toast('Cette annonce ne peut pas être sauvegardée.',true);return}favorites.push({...record,transaction:record.transaction||mode,savedAt:new Date().toISOString()});toast('Annonce ajoutée à vos favoris.')}persistFavorites();button.classList.toggle('is-favorite',index<0);button.setAttribute('aria-label',index<0?'Retirer des favoris':'Ajouter aux favoris');if(currentView==='favorites')renderFavorites()}
function listingHighlights(x,cardMode=mode){const c=modeCriteria[cardMode]||criteria,strengths=[],concerns=[],f=x.features||{},price=x.comparisonPrice??x.price,priceMin=c[cardMode==='rent'?'minBudget':'minPrice'],priceMax=c[cardMode==='rent'?'maxBudget':'maxPrice'],hasPriceBound=(priceMin!==''&&priceMin!==undefined)||(priceMax!==''&&priceMax!==undefined);if(price!==null&&price!==undefined&&hasPriceBound&&(priceMin===''||priceMin===undefined||price>=Number(priceMin))&&(priceMax===''||priceMax===undefined||price<=Number(priceMax)))strengths.push('Dans le budget');const areaMin=c.minArea,areaMax=c.maxArea,hasAreaBound=(areaMin!==''&&areaMin!==undefined)||(areaMax!==''&&areaMax!==undefined);if(x.area!==null&&x.area!==undefined&&hasAreaBound&&(areaMin===''||areaMin===undefined||x.area>=Number(areaMin))&&(areaMax===''||areaMax===undefined||x.area<=Number(areaMax)))strengths.push('Surface conforme');if(c.bedrooms!==''&&c.bedrooms!==undefined&&x.bedrooms!==null&&x.bedrooms!==undefined){const min=Number(String(c.bedrooms).replace('+',''));if((min===0&&x.bedrooms===0)||(min>0&&x.bedrooms>=min))strengths.push('Chambres conformes')}for(const [key,wanted] of Object.entries(c.features||{}))if(wanted===true&&f[key]===true&&featureNames[key])strengths.push(featureNames[key]);if(x.area!==null&&x.area!==undefined&&!strengths.some(v=>v==='Surface conforme'))strengths.push(x.area+' m²');if(x.bedrooms!==null&&x.bedrooms!==undefined&&!strengths.some(v=>v==='Chambres conformes'))strengths.push(x.bedrooms===0?'Studio':x.bedrooms+' ch.');if(!strengths.length&&x.matchState==='confirmed')strengths.push('Correspond à vos critères');const failures=[...(x.matchReasons||[])],unknown=[...(x.unknownReasons||[])];if(failures.length)concerns.push(...failures);if(unknown.length)concerns.push(...unknown);if(cardMode==='rent'&&(x.fees===null||x.fees===undefined))concerns.push('Charges non précisées');if(!x.energyRating)concerns.push('PEB à vérifier sur l’annonce');else if(['E','F','G'].includes(String(x.energyRating).toUpperCase()))concerns.push(energyLabel(x));if(cardMode!=='rent'){const state=foldArea(x.condition||'');if(state.includes('renov'))concerns.push('État déclaré : à rénover');if(!x.renovation||x.renovation.high===null||x.renovation.high===undefined)concerns.push('Budget travaux à confirmer')}if(x.occupancy==='occupied')concerns.push('Bien occupé');if(x.stale)concerns.push('Annonce non actualisée récemment');const unique=(items,max)=>[...new Set(items)].slice(0,max),good=unique(strengths,3),watch=unique(concerns,2);return '<div class="listing-highlights"><span class="highlight-strength"><b>Atouts</b> '+esc(good.join(' · ')||'À préciser')+'</span><span class="highlight-caution"><b>À vérifier</b> '+esc(watch.join(' · ')||'Aucun point signalé')+'</span></div>'}
function agencyMarkup(x){
 const name=x.agencyName||x.source||'Annonce';
 const known={'Red Immobilier':'https://www.redimmobilier.be/images/redimmobilier.png','Easy Properties':'https://easyproperties.be/wp-content/uploads/2021/08/favicon.svg'};
 let logo=x.agencyLogo||known[x.source]||'';try{if(new URL(logo).protocol!=='https:')logo=''}catch{logo=''}
 return '<span class="agency-brand" title="'+esc(name)+'">'+(logo?'<img class="agency-logo" src="'+esc(logo)+'" alt="Logo '+esc(name)+'" loading="lazy" decoding="async" referrerpolicy="no-referrer" onerror="this.hidden=true">':'')+'<span class="agency-name">'+esc(name)+'</span></span>';
}
function updateAgencyBrand(photo,branding){if(!branding||!Object.keys(branding).length)return;const mark=photo.querySelector('.agency-brand');if(mark)mark.outerHTML=agencyMarkup(branding);const key=photo.dataset.transaction+':'+photo.dataset.listingId;const row=window.__listingRecords[key];if(row)Object.assign(row,branding)}
function gemNotes(x){const g=x.gem;return '<div class="gem-notes"><span class="gem-label">✦ '+esc(g.label)+'</span><h3>Pourquoi elle retient notre attention</h3><ul>'+g.reasons.map(reason=>'<li>'+esc(reason)+'</li>').join('')+'</ul>'+(g.cautions.length?'<p class="gem-caution"><b>À vérifier</b> · '+esc(g.cautions.join(' · '))+'</p>':'')+'</div>'}
let featuredGemKeys=new Set();
function renderGems(items){featuredGemKeys=new Set(items.map(x=>favoriteKey(x,mode)));$('gemsCount').textContent=items.length?items.length+' biens sélectionnés':'Aucune pépite confirmée';$('gemsSubtitle').textContent=mode==='rent'?'Du cachet, de l’espace ou un loyer intéressant : les visites à envisager en premier.':'Prix, atouts et état annoncé : les biens qui méritent une visite attentive.';$('gemsResults').innerHTML=items.length?items.map(x=>card(x,false,mode,true)).join(''):'<p class="gems-empty">Pas assez d’informations fiables pour retenir une pépite avec ces critères. La sélection se mettra à jour après la prochaine recherche.</p>';observeGalleries($('gemsResults'))}
function energyLabel(x){return 'PEB '+String(x.energyRating||'').toUpperCase()+(String(x.energyRegion||'').startsWith('EPC')?' (EPC)':'')}
function conciseSummary(x){
 const text=foldArea([x.title,x.summary].filter(Boolean).join(' ')),f=x.features||{},points=[];
 const has=pattern=>pattern.test(text),add=value=>{if(value&&!points.includes(value))points.push(value)};
 if(has(/\b(?:viager|life annuity|lijfrente)\b/))add('Vente en viager');
 if(has(/\b(?:colocation|co living|cohousing|shared (?:apartment|house|flat)|room(?:s)? for rent|chambre(?:s)? a louer|kot)\b/))add('Colocation ou chambre à louer');
 if(x.occupancy==='occupied'||has(/\b(?:currently rented|op heden verhuurd|bien loue|verhuurd op jaarbasis)\b/))add('Bien actuellement occupé ou loué');
 if(x.condition==='renovation'||has(/\b(?:te renoveren|needs renovation|a renover)\b/))add('Travaux de rénovation à prévoir');
 else if(x.condition==='renovated'||has(/\b(?:gerenoveerd|volledig vernieuwd|fully renovated|entierement renove)\b/))add('Rénové');
 else if(has(/\b(?:instapklaar|move in ready|pret a emmenager)\b/))add('Prêt à emménager');
 if(x.construction==='new'||has(/\b(?:nieuwbouw|new build|construction neuve)\b/))add('Construction neuve');
 if(has(/\b(?:zeezicht|zicht op zee|sea view|vue sur (?:la )?mer|vue mer)\b/)&&!has(/\b(?:geen zeezicht|no sea view|sans vue mer)\b/))add('Vue sur la mer');
 const equipment=Object.entries({terrace:'Terrasse',balcony:'Balcon',garden:'Jardin',parking:'Parking / garage',lift:'Ascenseur',cellar:'Cave',furnished:'Meublé'}).filter(([key])=>f[key]===true).map(([,label])=>label);
 if(equipment.length)add(equipment.slice(0,3).join(' · '));
 if(has(/\b(?:cuisine (?:super )?equipee|equipped kitchen|ingerichte keuken|uitgeruste keuken)\b/))add('Cuisine équipée');
 if(has(/\b(?:gelijkvloers|rez de chaussee|ground floor)\b/))add('Rez-de-chaussée');
 const near='(?:proche|pres|a proximite|nabij|vlakbij|near|walking distance|op wandelafstand)';
 if(new RegExp(near+'.{0,60}(?:commerc|winkel|shop|store)').test(text))add('Commerces à proximité');
 if(new RegExp(near+'.{0,60}(?:transport|tram|metro|bus|station|gare|openbaar vervoer)').test(text))add('Transports à proximité');
 return points.length?'<ul class="summary-points">'+points.slice(0,3).map(point=>'<li>'+esc(point)+'</li>').join('')+'</ul>':'';
}
function card(x,suggestion=false,cardMode=mode,gem=false){const photos=Array.isArray(x.photos)?x.photos:[],src=photos[0]||'',title=typeOf(x),saved=isFavorite(x,cardMode),price=x.displayPrice??x.price,priceText=price===null||price===undefined?'Prix à confirmer':money(price),subtitle=x.priceLabel||(cardMode==='rent'?'loyer mensuel demandé':'prix affiché');const address=x.streetAddress?[x.streetAddress,x.location].filter(Boolean).join(', '):(x.location||'Belgique');const fact=(label,value)=>'<span class="visual-fact"><b>'+label+'</b>'+esc(value)+'</span>';let facts=fact('Type',title);if(x.area!==null&&x.area!==undefined)facts+=fact('Surface',x.area+' m²');if(x.bedrooms!==null&&x.bedrooms!==undefined)facts+=fact('Chambres',x.bedrooms===0?'Studio':String(x.bedrooms));if(x.bathrooms!==null&&x.bathrooms!==undefined)facts+=fact('Salles de bain',String(x.bathrooms));const state=x.condition==='renovated'?'Rénové':x.condition==='renovation'?'À rénover':x.condition==='good'?'Bon état':x.construction==='new'?'Neuf':'';if(state)facts+=fact('État',state);if(x.energyRating)facts+='<span class="energy-pill" title="'+esc(x.energyRegion||'Classe annoncée sur la fiche')+'"><b>Énergie</b>'+esc(energyLabel(x))+'</span>';if(x.constructionYear)facts+=fact('Année',String(x.constructionYear));const photo='<div class="photo visual-photo" data-listing-url="'+esc(x.url)+'" data-images="'+esc(JSON.stringify(photos))+'" data-index="0" data-current-src="'+esc(src)+'" data-listing-id="'+esc(x.id)+'" data-transaction="'+esc(cardMode)+'">'+'<img loading="lazy" decoding="async" referrerpolicy="no-referrer" '+(src?'src="'+esc(src)+'" data-request-src="'+esc(src)+'"':'hidden')+' alt="Photo de '+esc(title.toLowerCase())+' à '+esc(address)+'" onerror="photoFailure(this)">'+'<div class="photo-fallback '+(!src?'show':'')+'">Photo indisponible</div><div class="cover-shade"></div><a class="cover-link" href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer" aria-label="Voir l’annonce de '+esc(address)+'"></a><div class="cover-top">'+agencyMarkup(x)+'<button class="favorite-heart '+(saved?'is-favorite':'')+'" type="button" data-favorite-id="'+esc(favoriteKey(x,cardMode))+'" aria-label="'+(saved?'Retirer des favoris':'Ajouter aux favoris')+'" title="'+(saved?'Retirer des favoris':'Ajouter aux favoris')+'">♥</button></div><div class="cover-info"><span class="cover-address">⌖ '+esc(address)+'</span><strong class="cover-price">'+esc(priceText)+'</strong><span class="cover-title">'+esc(title)+(x.bedrooms===0?' · studio':'')+'</span><small class="cover-price-note">'+esc(subtitle)+'</small></div>'+(src||x.url?'<button type="button" class="photo-nav prev" aria-label="Photo précédente" data-photo-step="-1">‹</button><button type="button" class="photo-nav next" aria-label="Photo suivante" data-photo-step="1">›</button><span class="photo-count" aria-live="polite">'+(photos.length>1?'1 / '+photos.length:'1 photo')+'</span>':'')+'</div>';const match=suggestion?'<div class="match-note">À vérifier : '+esc([...(x.matchReasons||[]),...(x.unknownReasons||[])].join(' · ')||x.match||'information manquante')+'</div>':'';const summary=conciseSummary(x);const budget=cardMode!=='rent'?renovationMarkup(x):'';const beach=cardMode==='coast'?'<div class="beach-distance">🏖 '+(x.beachDistanceM!=null?('Plage : env. '+(x.beachDistanceM<1000?x.beachDistanceM+' m':(x.beachDistanceM/1000).toLocaleString('fr-BE',{maximumFractionDigits:1})+' km')+(x.beachDistanceBasis==='listing-text'?' (selon l’annonce)':' à vol d’oiseau')+(x.beachWalkMinutes?' · env. '+x.beachWalkMinutes+' min à pied':'')):x.beachWalkMinutes?('Plage : '+x.beachWalkMinutes+' min à pied (selon l’annonce)'):(x.beachProximityClaim?'Plage proche selon l’annonce · distance à confirmer':'Distance de la plage à confirmer'))+'</div>':'';const foot=cardMode==='rent'?(x.fees===null||x.fees===undefined?'Charges non précisées':'Charges mensuelles : '+money(x.fees)):'Prix au m² : '+(x.price&&x.area?money(Math.round(x.price/x.area))+'/m²':'non calculable');const featured=!gem&&featuredGemKeys.has(favoriteKey(x,cardMode));return '<article class="listing visual-listing '+(suggestion?'suggested':'')+(gem?' gem-card':'')+'"><div class="visual-media">'+photo+'</div><div class="listing-body">'+(featured?'<span class="gem-list-badge" aria-label="Sélectionné comme pépite">✦ Pépite</span>':'')+'<div class="visual-facts">'+facts+'</div>'+(listingHighlights(x,cardMode)+summary+budget+match+(gem?gemNotes(x):''))+beach+'<div class="date-line">'+esc(dateLabel(x))+(x.stale?' · Source temporairement indisponible':'')+'</div><div class="listing-footer"><span>'+esc((cardMode==='rent'?'À louer':'À vendre')+' · '+foot)+'</span><a href="'+esc(x.url)+'" target="_blank" rel="noopener noreferrer">Voir l’annonce ↗</a></div></div></article>'}
window.__listingRecords={};
window.photoFailure=photoFailure;
const photoGestures=new WeakMap();document.addEventListener('click',ev=>{const b=ev.target.closest('[data-photo-step]');if(b){ev.preventDefault();stepPhoto(b.closest('.photo'),Number(b.dataset.photoStep))}});
const galleryQueue=[];let galleryActive=0;function queueGallery(photo){if(!photo||photo.dataset.galleryPrefetch==='true'||photo.dataset.galleryChecked==='true'||photoState(photo).length>1||!photo.dataset.listingUrl)return;photo.dataset.galleryPrefetch='true';photo.dataset.galleryLoading='true';galleryQueue.push(photo);drainGalleries()}async function drainGalleries(){while(galleryActive<2&&galleryQueue.length){const photo=galleryQueue.shift();if(!photo.isConnected){delete photo.dataset.galleryLoading;continue}galleryActive++;try{const r=await fetch('/api/photos?mode='+(photo.dataset.transaction||mode)+'&id='+encodeURIComponent(photo.dataset.listingId));const d=await r.json();if(r.ok&&Array.isArray(d.photos)){updateAgencyBrand(photo,d.branding);photo.dataset.images=JSON.stringify(d.photos);photo.dataset.galleryChecked='true';if(d.photos.length){const img=photo.querySelector('img:not(.agency-logo)');if(img&&!photo.dataset.currentSrc){img.hidden=false;img.src=d.photos[0];img.dataset.requestSrc=d.photos[0];photo.dataset.currentSrc=d.photos[0];photo.querySelector('.photo-fallback').classList.remove('show')}if(d.photos.length>1)showPhoto(photo,Number(photo.dataset.pendingStep||0)>0?1:Number(photo.dataset.pendingStep||0)<0?d.photos.length-1:0);else{const count=photo.querySelector('.photo-count');if(count)count.textContent='1 photo'}}else{const fallback=photo.querySelector('.photo-fallback');fallback.classList.add('show');photo.querySelectorAll('.photo-nav,.photo-count').forEach(el=>el.hidden=true)}}else{photo.dataset.galleryPrefetch='failed';const count=photo.querySelector('.photo-count');if(count)count.textContent='1 photo'}}catch{photo.dataset.galleryPrefetch='failed';const count=photo.querySelector('.photo-count');if(count)count.textContent='1 photo'}finally{delete photo.dataset.galleryLoading;galleryActive--;drainGalleries()}}}
let galleryObserver=null;
function observeGalleries(root){
 if(galleryObserver)galleryObserver.disconnect();
 const photos=[...document.querySelectorAll('.visual-photo')].filter(p=>photoState(p).length<2&&p.dataset.galleryChecked!=='true'&&p.dataset.galleryPrefetch!=='true');
 if(!('IntersectionObserver'in window))return;
 if(!galleryObserver)galleryObserver=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){galleryObserver.unobserve(entry.target);queueGallery(entry.target)}},{rootMargin:'100px 0px'});
 photos.forEach(p=>galleryObserver.observe(p));
}
document.addEventListener('pointerdown',ev=>{const p=ev.target.closest('.photo');if(p&&!ev.target.closest('button')){photoGestures.set(p,{x:ev.clientX,y:ev.clientY});try{ev.target.setPointerCapture(ev.pointerId)}catch{}}});
document.addEventListener('pointerup',ev=>{const p=ev.target.closest('.photo'),start=p&&photoGestures.get(p);if(!start)return;photoGestures.delete(p);const dx=ev.clientX-start.x,dy=ev.clientY-start.y;if(Math.abs(dx)>45&&Math.abs(dx)>Math.abs(dy)){ev.preventDefault();p.dataset.suppressSwipeClick='true';stepPhoto(p,dx<0?1:-1)}});
document.addEventListener('click',ev=>{const p=ev.target.closest('.photo');if(p?.dataset.suppressSwipeClick==='true'){ev.preventDefault();ev.stopPropagation();delete p.dataset.suppressSwipeClick}},true);
window.saveOverride=async btn=>{const box=btn.closest('.override'),inputs=box.querySelectorAll('input');try{const r=await fetch('/api/override?mode='+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:box.dataset.id,low:inputs[0].value,high:inputs[1].value})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Échec');toast('Votre fourchette est enregistrée.');await loadListings(true)}catch(e){toast('Impossible d’enregistrer : '+e.message,true)}};
window.clearOverride=async btn=>{const box=btn.closest('.override');try{const r=await fetch('/api/override?mode='+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:box.dataset.id,clear:true})});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'Échec');await loadListings(true)}catch(e){toast(e.message,true)}};
let listingRequest=0;
async function loadListings(reset=false){const request=++listingRequest,requestMode=mode;if(reset){page=1;$('results').innerHTML=''}const r=await fetch('/api/listings?mode='+mode+'&section=matches&page='+page+'&pageSize='+pageSize+'&sortBy='+resultSortQuery());if(!r.ok){const err=await r.json().catch(()=>({}));throw new Error(err.error||'Lecture des annonces impossible')}const d=await r.json();if(request!==listingRequest||requestMode!==mode)return d;total=d.total;if(page===1){sourceCountsForMode[mode]=d.sourceCounts||[];hiddenStaleForMode[mode]=d.hiddenStale||0;renderSourceCoverage()}for(const x of [...(d.items||[]),...(d.suggestionItems||[]),...(d.gemItems||[])])window.__listingRecords[favoriteKey(x,mode)]={...x,transaction:mode};if(page===1){renderGems(d.gemItems||[]);$('results').innerHTML=d.items.map(x=>card(x)).join('');const suggestions=d.suggestionItems||[];$('suggestionResults').innerHTML=suggestions.length?suggestions.map(x=>card(x,true)).join(''):'<p class="suggestions-empty">Aucun bien à considérer en plus pour l’instant.</p>';$('matchCount').textContent=d.matches;$('excludedCount').textContent=d.excluded;$('results').insertAdjacentHTML('afterend','')}
 else $('results').insertAdjacentHTML('beforeend',d.items.map(x=>card(x)).join(''));$('moreBtn').hidden=page*pageSize>=total;const pageCount=Math.ceil(total/pageSize),shown=Math.min(page*pageSize,total),remainingPages=Math.max(0,pageCount-page),remainingItems=Math.max(0,total-shown);$('paginationProgress').textContent=total?`Annonces 1–${shown} sur ${total.toLocaleString('fr-BE')} · Page ${page} sur ${pageCount}${remainingPages?` · ${remainingPages} page${remainingPages>1?'s':''} restante${remainingPages>1?'s':''} (${remainingItems.toLocaleString('fr-BE')} annonces)`: ' · Toutes les annonces affichées'}`:'Aucune annonce à afficher';$('emptyState')?.remove();observeGalleries($('listingView'));if(currentView==='map'&&page===1)refreshMap();if(currentView==='favorites')renderFavorites();if(page===1&&!d.items.length)$('results').innerHTML='<div class="panel" style="padding:22px;font-size:11px">Aucune correspondance confirmée pour le moment. Consultez les suggestions ou ajustez les critères.</div>';return d}
let lastRunHeaderRefreshAt=0;
async function refreshLastRunHeader(force=false){
 const node=$('lastRunHeader');if(!node)return;
 if(!force&&Date.now()-lastRunHeaderRefreshAt<60000)return;
 lastRunHeaderRefreshAt=Date.now();const value=node.querySelector('strong');
 let warning=node.querySelector('.last-run-alert');
 if(!warning){warning=document.createElement('span');warning.className='last-run-alert';warning.hidden=true;node.append(warning)}
 try{
  const rows=await Promise.all(MODES.map(async m=>{
   const r=await fetch('/api/status?mode='+m,{cache:'no-store'});
   if(!r.ok)throw new Error('Statut indisponible');
   return {mode:m,...await r.json()};
  }));
  const latest=rows.filter(x=>x.lastRun&&!Number.isNaN(Date.parse(x.lastRun))).sort((a,b)=>Date.parse(b.lastRun)-Date.parse(a.lastRun))[0];
  const failures=rows.filter(x=>x.state==='source-error');
  warning.hidden=!failures.length;
  warning.textContent='';
  if(failures.length){
   const failed=failures.slice().sort((a,b)=>Date.parse(b.lastAttempt||b.lastRun||0)-Date.parse(a.lastAttempt||a.lastRun||0))[0];
   const at=failed.lastAttempt||failed.lastRun;
   const label=failures.length>1?'plusieurs recherches':failures[0].mode==='rent'?'location':failures[0].mode==='coast'?'achat à la mer':'achat';
   warning.textContent='Échec '+label+(at?' · '+new Date(at).toLocaleString('fr-BE',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'}):'');
   warning.title='La dernière tentative a échoué. Les résultats précédents sont conservés.';
  }
  if(!latest){value.textContent='Aucune collecte';node.title='Aucune collecte enregistrée pour le moment';return}
  const when=new Date(latest.lastRun);
  value.textContent=when.toLocaleString('fr-BE',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'});
  node.title='Dernière mise à jour des annonces · '+(latest.mode==='rent'?'locations':'ventes')+' · '+when.toLocaleString('fr-BE');
 }catch{
  warning.hidden=false;warning.textContent='Statut indisponible';
  warning.title='Impossible de vérifier la dernière collecte.';
  if(value.textContent==='Chargement…')value.textContent='Indisponible';
 }
}
async function loadStatus(){const r=await fetch('/api/status?mode='+mode);if(!r.ok)throw new Error('Statut indisponible');const s=await r.json();sourceStatusForMode[mode]=s.sources||[];renderSourceCoverage();const p=s.progress||{};refreshLastRunHeader();let text='';if(p.running)text='Collecte en cours depuis '+new Date(p.startedAt).toLocaleTimeString('fr-BE',{hour:'2-digit',minute:'2-digit'})+'…';else if(p.ok===false&&p.error)text='La dernière collecte a échoué : '+p.error;else if(s.state==='no-areas')text='Ajoutez une commune ou un code postal pour démarrer.';else if(s.state==='partial')text='Collecte partielle : certains portails ont limité les résultats ou rencontré une erreur. Les anciens résultats sont conservés et signalés.';else if(s.state==='source-error')text=s.error?'La dernière collecte a échoué'+(s.lastAttempt?' le '+new Date(s.lastAttempt).toLocaleString('fr-BE'):'')+'. Les résultats précédents sont conservés.':'Aucune source n’a répondu; les résultats précédents sont conservés.';else text='Dernière collecte : '+(s.lastRun?new Date(s.lastRun).toLocaleString('fr-BE'):'pas encore lancée')+(window.NINOU_STATIC?' · Collectes prévues vers 10 h et 17 h, heure belge.':' · prochaines collectes automatiques à 10 h et 17 h.');
 const directSources=(s.sources||[]).filter(x=>x.domain||x.sourceType==='agency-site');const directOk=directSources.filter(x=>x.ok).length;if(directSources.length)text+=' · '+directOk+' agence(s) directe(s) analysée(s) sur '+directSources.length;$('statusNote').textContent=text;$('statusNote').className='notice '+(p.error||s.state==='source-error'?'error':s.state==='partial'?'partial':'');if(!window.NINOU_STATIC){$('runBtn').disabled=!!p.running;$('runBtn').textContent=p.running?'Recherche…':'Chercher';}return s}
async function loadMode(){const requestedMode=mode;listingRequest++;$('gemsResults').innerHTML='<p class="gems-empty">Recherche des pépites…</p>';$('gemsCount').textContent='Sélection en cours…';$('statusNote').textContent='Chargement…';try{restoreResultSort();const cr=await fetch('/api/criteria?mode='+mode);if(!cr.ok)throw new Error('Critères indisponibles');const loadedCriteria=await cr.json();if(requestedMode!==mode)return;criteria=loadedCriteria;modeCriteria[mode]=criteria;renderCriteriaForm(criteria);syncBudgetControls(criteria);updateHeroAreas(criteria);if($('immowebSearch').open)renderImmowebChoices();await loadListings(true);if(requestedMode!==mode)return;await loadStatus()}catch(e){$('statusNote').textContent='Impossible de charger l’application : '+e.message;$('statusNote').className='notice error'}}
$('moreBtn').onclick=async()=>{const b=$('moreBtn');if(b.disabled)return;b.disabled=true;page++;try{await loadListings(false)}catch(e){page--;toast(e.message,true)}finally{b.disabled=false}};
$('immowebSearch').addEventListener('toggle',ev=>{if(ev.currentTarget.open)renderImmowebChoices()});$('criteriaForm').addEventListener('change',()=>{if($('immowebSearch').open)renderImmowebChoices()});$('criteriaForm').addEventListener('input',()=>{if($('immowebSearch').open)renderImmowebChoices()});
$('runBtn').onclick=async()=>{const b=$('runBtn');b.disabled=true;b.textContent='Lancement…';try{await persistCurrentCriteria();const r=await fetch('/api/run?mode='+mode,{method:'POST'});const d=await r.json();if(!r.ok||!d.ok)throw new Error(d.error||'La recherche ne démarre pas');await loadStatus();let attempts=0;while(attempts++<180){await new Promise(resolve=>setTimeout(resolve,1500));const s=await loadStatus();if(!s.progress?.running){if(s.progress?.ok===false&&s.progress.error)throw new Error(s.progress.error);break}}if(attempts>=180)throw new Error('La recherche dépasse le délai prévu. Consultez son statut plus tard.');await loadListings(true);await refreshLastRunHeader(true);toast('Recherche terminée.')}catch(e){$('statusNote').textContent='La recherche a échoué : '+e.message;$('statusNote').className='notice error';toast('La recherche a échoué.',true)}finally{b.disabled=false;b.textContent='Chercher ici'}};
$('excludedToggle').onclick=async()=>{const box=$('excludedResults');if(!excludedLoaded){try{const r=await fetch('/api/listings?mode='+mode+'&section=excluded&page=1&pageSize=24');const d=await r.json();box.innerHTML=d.items.map(x=>card(x,true)).join('')||'<div class="muted">Aucune annonce écartée enregistrée.</div>';excludedLoaded=true}catch(e){toast('Impossible de charger les annonces écartées.',true)}}box.hidden=!box.hidden};
function setView(view){currentView=view;const ids={list:'listingView',map:'mapView',favorites:'favoriteView'};for(const [key,id] of Object.entries(ids))$(id).hidden=key!==view;for(const [key,id] of Object.entries({list:'listViewTab',map:'mapViewTab',favorites:'favoriteViewTab'})){const on=key===view;$(id).classList.toggle('active',on);$(id).setAttribute('aria-selected',String(on))}try{localStorage.setItem('ninou-view',view)}catch{}if(view==='favorites')renderFavorites();if(view==='map')refreshMap()}
$('listViewTab').onclick=()=>setView('list');$('mapViewTab').onclick=()=>setView('map');$('favoriteViewTab').onclick=()=>setView('favorites');
document.addEventListener('click',ev=>{const heart=ev.target.closest('.favorite-heart');if(heart){ev.preventDefault();ev.stopPropagation();toggleFavorite(heart)}});
const geoApprox={'1000':[50.8467,4.3525],'1020':[50.897,4.35],'1030':[50.867,4.373],'1040':[50.835,4.39],'1050':[50.82,4.38],'1060':[50.83,4.345],'1070':[50.84,4.29],'1080':[50.855,4.32],'1081':[50.86,4.33],'1082':[50.87,4.29],'1083':[50.87,4.31],'1090':[50.88,4.33],'1140':[50.87,4.4],'1150':[50.83,4.43],'1160':[50.81,4.43],'1170':[50.79,4.42],'1180':[50.8,4.34],'1190':[50.81,4.32],'1200':[50.85,4.43],'1210':[50.855,4.37],'2000':[51.22,4.4],'3000':[50.88,4.7],'4000':[50.63,5.57],'5000':[50.47,4.87],'6000':[50.41,4.44],'7000':[50.45,3.95],'8000':[51.21,3.22],'9000':[51.05,3.72],'8660':[51.10,2.59],'8670':[51.11,2.65],'8620':[51.13,2.75],'8430':[51.19,2.82],'8400':[51.23,2.92],'8450':[51.24,2.97],'8420':[51.27,3.03],'8370':[51.31,3.13],'8380':[51.33,3.21],'8300':[51.35,3.29],'8301':[51.34,3.24]};
const mapKinds={address:'Adresse ou résidence repérée',announced:'Position publiée par l’annonce',postal:'Centre du code postal · bien non localisé'};
let mapPoints=[],mapRenderTimer=null;
function mapPoint(x){
 const lat=x.latitude==null||x.latitude===''?NaN:Number(x.latitude),lng=x.longitude==null||x.longitude===''?NaN:Number(x.longitude);
 if(Number.isFinite(lat)&&Number.isFinite(lng)&&lat>=49.4&&lat<=51.6&&lng>=2.4&&lng<=6.4){
  const kind=['verified-address','verified-residence','matched-residence'].includes(x.beachLocationBasis)?'address':'announced';
  return {lat,lng,kind,row:x};
 }
 const postal=String(x.postalCode||x.location||'').match(/\b(\d{4})\b/)?.[1],center=geoApprox[postal];
 return center?{lat:center[0],lng:center[1],kind:'postal',postal,row:x}:null;
}
function groupMapPoints(points,zoom,project){
 const groups=new Map(),cell=zoom>=17?24:84;
 for(const point of points){
  const pixel=project(point.lat,point.lng,zoom);
  const key=point.kind==='postal'?'postal:'+point.postal:point.kind+':'+Math.floor(pixel.x/cell)+':'+Math.floor(pixel.y/cell);
  let group=groups.get(key);
  if(!group){group={kind:point.kind,lat:0,lng:0,items:[]};groups.set(key,group)}
  group.lat+=point.lat;group.lng+=point.lng;group.items.push(point.row);
 }
 return Array.from(groups.values(),group=>({...group,lat:group.lat/group.items.length,lng:group.lng/group.items.length}));
}
function mapListingLink(row){
 const price=row.displayPrice!=null?money(row.displayPrice):row.price!=null?money(row.price):'Prix à confirmer';
 const label=[typeOf(row),row.location,price].filter(Boolean).join(' · ');
 return /^https:\/\//i.test(row.url||'')?'<a href="'+esc(row.url)+'" target="_blank" rel="noopener noreferrer">'+esc(label)+' ↗</a>':'<span>'+esc(label)+'</span>';
}
function renderMapPoints(){
 if(!mapInstance||!mapLayer)return;
 mapLayer.clearLayers();
 const zoom=mapInstance.getZoom();
 const groups=groupMapPoints(mapPoints,zoom,(lat,lng,z)=>mapInstance.project([lat,lng],z));
 for(const group of groups){
  const many=group.items.length>1,row=group.items[0];
  const price=row.displayPrice!=null?money(row.displayPrice):row.price!=null?money(row.price):'Prix à confirmer';
  const label=many?group.items.length+' annonces':price==='Prix à confirmer'?'Voir':price.replace(/\s/g,'');
  const width=many?Math.min(105,Math.max(60,label.length*7+18)):Math.min(108,Math.max(48,label.length*7+18));
  const icon=L.divIcon({className:'apartment-map-marker map-marker-'+group.kind+(many?' map-marker-cluster':''),html:'<span>'+esc(label)+'</span>',iconSize:[width,34],iconAnchor:[width/2,34]});
  const marker=L.marker([group.lat,group.lng],{icon}).addTo(mapLayer);
  const count=many?group.items.length+' annonces':'1 annonce';
  marker.bindPopup(()=>'<div class="map-group-popup"><strong>'+count+' · '+mapKinds[group.kind]+'</strong><div class="map-popup-links">'+group.items.map(mapListingLink).join('')+'</div></div>',{maxWidth:330,maxHeight:300});
  if(many&&group.kind!=='postal'&&zoom<17)marker.on('click',()=>mapInstance.setView([group.lat,group.lng],Math.min(17,zoom+2)));
 }
}
async function refreshMap(){
 if(!window.L){$('mapStatus').textContent='La carte ne se charge pas. Vérifiez votre connexion.';return}
 if(!mapInstance){
  mapInstance=L.map('listingMap').setView([50.85,4.35],10);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(mapInstance);
  mapLayer=L.layerGroup().addTo(mapInstance);
  mapInstance.on('zoomend',()=>{clearTimeout(mapRenderTimer);mapRenderTimer=setTimeout(renderMapPoints,50)});
 }
 setTimeout(()=>mapInstance.invalidateSize(),100);
 $('mapStatus').textContent='Chargement de toutes les annonces…';
 const mapMode=mode;
 try{
  let rows=[],d=null,mapPage=1;
  do{
   const r=await fetch('/api/listings?mode='+mapMode+'&section=all&page='+mapPage+'&pageSize=100&sortBy='+resultSortQuery());
   if(!r.ok)throw new Error('Chargement impossible');
   d=await r.json();rows.push(...(d.items||[]));mapPage++;
  }while(d&&mapPage<=Math.ceil((d.total||0)/100));
  if(mapMode!==mode||currentView!=='map')return;
  mapPoints=rows.map(mapPoint).filter(Boolean);
  const bounds=mapPoints.map(p=>[p.lat,p.lng]);
  renderMapPoints();
  if(bounds.length)mapInstance.fitBounds(bounds,{padding:[30,30],maxZoom:13});
  const counts={address:0,announced:0,postal:0};for(const p of mapPoints)counts[p.kind]++;
  $('mapStatus').textContent=counts.address+' par adresse/résidence · '+counts.announced+' selon la carte de l’annonce · '+counts.postal+' au centre du code postal · '+(rows.length-mapPoints.length)+' sans position. '+rows.length+' annonces collectées.';
 }catch(e){$('mapStatus').textContent='Carte indisponible : '+e.message}
}
let restoredView='list';try{restoredView=localStorage.getItem('ninou-view')||'list'}catch{}if(['list','map','favorites'].includes(restoredView))setView(restoredView);else setView('list');persistFavorites();
window.addEventListener('hashchange',()=>{const next=location.hash.slice(1);if(next!==mode)setMode(next,false)});
setMode(location.hash.slice(1),false);setInterval(()=>refreshLastRunHeader(true),60000);

document.addEventListener('pointerdown',ev=>{const dropdown=$('filterDropdown');if(dropdown?.open&&!dropdown.contains(ev.target))dropdown.open=false;});
