/* A small local API for the unchanged UI, backed by versioned static JSON. */
(function(){
'use strict';
window.NINOU_STATIC=true;
const realFetch=window.fetch.bind(window),base=new URL('./',document.currentScript.src),search=NinouSearch;
let manifest=realFetch(new URL('data/manifest.json',base),{cache:'no-cache'}).then(r=>{if(!r.ok)throw new Error('Annonces indisponibles');return r.json()});
const catalogues={},criteria={},overrides={},evaluated={};
const key=(m,type)=>'ninou-public-v1-'+type+'-'+m;
function restore(k,fallback){try{return JSON.parse(localStorage.getItem(k))||fallback}catch{return fallback}}
async function data(mode){if(!catalogues[mode])catalogues[mode]=manifest.then(async m=>{const r=await realFetch(new URL('data/'+m.files[mode],base));if(!r.ok)throw new Error('Catalogue indisponible');return r.json()}).catch(e=>{delete catalogues[mode];throw e});return catalogues[mode]}
async function prefs(mode){const m=await manifest;if(!criteria[mode])criteria[mode]={...m.config.defaults[mode],...restore(key(mode,'criteria'),{})};return criteria[mode]}
function save(mode,type,value){try{localStorage.setItem(key(mode,type),JSON.stringify(value))}catch{throw new Error('Ton navigateur ne permet pas d’enregistrer les préférences.')}delete evaluated[mode]}
async function resultRows(mode){
 if(evaluated[mode])return evaluated[mode];
 const [d,c,m]=await Promise.all([data(mode),prefs(mode),manifest]);overrides[mode]??=restore(key(mode,'overrides'),{});
 const rows=d.items.filter(r=>!r.stale&&search.areaMatches(r,c,m.config)).map(r=>search.evaluate(r,c,mode,m.config,overrides[mode][r.id]));
 evaluated[mode]=rows;return rows;
}
window.refreshPublicCatalogue=async()=>{const r=await realFetch(new URL('data/manifest.json',base),{cache:'no-cache'});if(!r.ok)return false;const next=await r.json(),previous=await manifest;if(next.revision===previous.revision)return false;manifest=Promise.resolve(next);for(const m of ['rent','sale']){delete catalogues[m];delete evaluated[m]}return true};
const response=(obj,status=200)=>new Response(JSON.stringify(obj),{status,headers:{'Content-Type':'application/json'}});
window.fetch=async function(input,options={}){
 const url=new URL(typeof input==='string'?input:input.url,location.href);
 if(url.origin!==location.origin||!url.pathname.startsWith('/api/'))return realFetch(input,options);
 const mode=url.searchParams.get('mode')||'rent';if(!['rent','sale'].includes(mode))return response({error:'Mode inconnu'},400);
 try{
  const method=options.method||'GET',path=url.pathname;
  if(path==='/api/criteria'){
   const current=await prefs(mode);
   if(method==='POST'){
    const payload=JSON.parse(options.body),next={...current,...payload};
    for(const [lo,hi] of [['minBudget','maxBudget'],['minPrice','maxPrice'],['minArea','maxArea'],['floorMin','floorMax'],['renovationRateLow','renovationRateHigh']])if(search.number(next[lo])!==null&&search.number(next[hi])!==null&&Number(next[lo])>Number(next[hi]))throw new Error('Le minimum doit être inférieur au maximum.');
    save(mode,'criteria',next);criteria[mode]=next;return response({ok:true,criteria:next});
   }
   return response(current);
  }
  if(path==='/api/status'){
   const [d,rows]=await Promise.all([data(mode),resultRows(mode)]);
   return response({...d.status,matchingCount:rows.filter(x=>x.matchState==='confirmed').length,progress:{running:false},sources:d.status.sources||[]});
  }
  if(path==='/api/listings'){
   const all=await resultRows(mode),matched=all.filter(r=>r.matchState==='confirmed'),unknown=all.filter(r=>r.matchState==='unknown'),excluded=all.filter(r=>r.matchState==='failed');
   const order=url.searchParams.get('sortBy')||'relevance',section=url.searchParams.get('section')||'matches';
   const suggestions=search.sort(unknown.filter(r=>r.unknownReasons.length===1),order).slice(0,2);
   // The map includes all collected active listings, irrespective of personal filters.
   const source=section==='all'?(await data(mode)).items.filter(r=>!r.stale):section==='excluded'?excluded:section==='suggestions'?suggestions:matched;
   const sorted=search.sort(source,order),page=Math.max(1,Number(url.searchParams.get('page'))||1),size=Math.min(100,Math.max(1,Number(url.searchParams.get('pageSize'))||24));
   const counts={};for(const row of matched)counts[row.source]=(counts[row.source]||0)+1;
   return response({items:sorted.slice((page-1)*size,page*size),total:sorted.length,matches:matched.length,unknown:unknown.length,excluded:excluded.length,page,pageSize:size,hiddenStale:0,sourceCounts:Object.entries(counts).sort((a,b)=>b[1]-a[1]),suggestionItems:suggestions,gemItems:page===1&&section==='matches'?search.selectGems(all):[]});
  }
  if(path==='/api/photos'){const row=(await data(mode)).items.find(r=>String(r.id)===url.searchParams.get('id'));return response({photos:row?.photos||[],branding:row?{agencyName:row.agencyName,agencyLogo:row.agencyLogo}: {}})}
  if(path==='/api/listing-validity'){const ids=new Set((url.searchParams.get('ids')||'').split(','));return response({validIds:(await data(mode)).items.filter(r=>!r.stale&&ids.has(String(r.id))).map(r=>String(r.id))})}
  if(path==='/api/override'&&method==='POST'){
   const payload=JSON.parse(options.body);overrides[mode]??=restore(key(mode,'overrides'),{});
   if(payload.clear)delete overrides[mode][payload.id];else{const low=search.number(payload.low),high=search.number(payload.high);if(low===null||high===null||low<0||high<low)throw new Error('Fourchette invalide');overrides[mode][payload.id]={low,high}}
   save(mode,'overrides',overrides[mode]);return response({ok:true});
  }
  return response({error:'Action indisponible sur le site partagé.'},404);
 }catch(e){return response({ok:false,error:e.message},400)}
};
})();
