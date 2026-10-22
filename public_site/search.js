/* Browser-only matching. No visitor preferences are sent to GitHub or the collector. */
(function(root){
'use strict';
const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const number=v=>v===null||v===undefined||v===''?null:Number.isFinite(Number(v))?Number(v):null;
const clone=v=>JSON.parse(JSON.stringify(v));
function areaMatches(row,c,config){
 const selected=(Array.isArray(c.areas)?c.areas:String(c.areas||'').split(/[,;\n]/)).map(norm).filter(Boolean);
 const codes=new Set(),names=new Set(selected),aliases=config.areaAliases||{};
 for(const selectedName of selected){
  for(const [alias,place] of Object.entries(aliases))if(norm(alias)===selectedName||norm(place[1])===selectedName){
   codes.add(place[0].split('-')[0]);names.add(norm(place[1]));names.add(norm(place[0].split('-').slice(1).join(' ')));
   if(c.nearby)for(const n of (config.nearby||{})[norm(place[1])]||[])for(const [a,p] of Object.entries(aliases))if(norm(p[1])===norm(n)){codes.add(p[0].split('-')[0]);names.add(norm(n))}
  }
 }
 if(codes.has('1000'))for(const code of ['1020','1120','1130'])codes.add(code);
 const location=norm(row.location),postal=String(row.postalCode||row.location||'').match(/\b\d{4}\b/)?.[0];
 return !!((postal&&codes.has(postal))||(location&&[...names].some(n=>location.includes(n))));
}
function renovation(row,c,override,config){
 if(override&&number(override.low)!==null&&number(override.high)!==null)return {...override,source:'manual',scenario:false,breakdown:[],note:'Estimation personnelle enregistrée dans ce navigateur.'};
 const rates=config.renovationRates||{},scope=c.renovationScope||'cosmetic',area=number(row.area);
 if(!area||!rates[scope])return {low:null,high:null,source:'unknown',scenario:false,breakdown:[],note:'Budget rénovation à confirmer'};
 let [lo,hi]=rates[scope];if(number(c.renovationRateLow)!==null&&number(c.renovationRateHigh)!==null){lo=Number(c.renovationRateLow);hi=Number(c.renovationRateHigh)}
 const vat=number(c.vatPct)??21,contingency=Math.min(50,Math.max(0,number(c.contingencyPct)??15));
 const cost=rate=>Math.round(Math.round(area*rate*(1+vat/100))*(1+contingency/100));
 return {low:cost(lo),high:cost(hi),source:'application',scenario:true,scope,area,rateLow:lo,rateHigh:hi,vatPct:vat,contingencyPct:contingency,breakdown:[],evidence:[],reference:config.renovationReference,note:'Scénario selon surface et hypothèses modifiables ; ni inspection, ni devis.'};
}
function evaluate(original,c,mode,config={},override=null,today=new Date()){
 const row=clone(original),reasons=[],unknown=[];
 const price=number(row.price),area=number(row.area),beds=number(row.bedrooms),fees=number(row.fees);
 const text=norm([row.title,row.summary].filter(Boolean).join(' '));
 function bound(value,minimum,maximum,missing,low,high){
  const min=number(minimum),max=number(maximum);
  if(min!==null||max!==null){if(value===null)unknown.push(missing);else{if(min!==null&&value<min)reasons.push(low);if(max!==null&&value>max)reasons.push(high)}}
 }
 row.comparisonPrice=mode==='rent'&&c.budgetBasis==='rent_and_charges'?(price===null||fees===null?null:price+fees):price;
 bound(row.comparisonPrice,c[mode==='rent'?'minBudget':'minPrice'],c[mode==='rent'?'maxBudget':'maxPrice'],'prix ou charges inconnus','prix inférieur au minimum','prix supérieur au maximum');
 bound(area,c.minArea,c.maxArea,'surface inconnue','surface hors critère','surface hors critère');
 const wantedBeds=number(String(c.bedrooms??'').replace('+',''));
 if(wantedBeds!==null){if(beds===null)unknown.push('nombre de chambres inconnu');else if(wantedBeds===0?beds!==0:beds<wantedBeds)reasons.push('nombre de chambres incompatible')}
 const house=/(maison|house|woning|villa)/.test(norm([row.propertyType,row.title,row.url].join(' ')));
 if(c.property==='House'&&!house)reasons.push('type maison incompatible');
 if(c.property==='Apartment'&&house)reasons.push('type appartement incompatible');
 if((c.subtypes||[]).length){
  const subtype=norm(row.subtype)+' '+text,aliases={Studio:['studio','studette'],Duplex:['duplex'],Penthouse:['penthouse','attique'],Loft:['loft']};
  if(!c.subtypes.some(t=>(aliases[t]||[norm(t)]).some(a=>subtype.includes(a))))(row.subtype||Object.values(aliases).flat().some(a=>subtype.includes(a))?reasons:unknown).push('sous-type non précisé ou incompatible');
 }
 for(const [key,selected] of Object.entries(c.features||{})){
  if(![true,false,'true','false'].includes(selected))continue;
  const actual=row.features?.[key],wanted=selected===true||selected==='true';
  if(actual==null)unknown.push(key+' non précisé');else if(Boolean(actual)!==wanted)reasons.push(key+(wanted?' absent':' présent'));
 }
 for(const key of ['energyRating','construction','condition','occupancy','furnished']){
  const selected=c[key];if(selected==null||['','any','indifferent'].includes(selected))continue;
  const actual=key==='furnished'?row.features?.furnished:row[key];
  if(actual==null)unknown.push(key+' non précisé');else if(key==='furnished'?Boolean(actual)!==(selected==='furnished'):norm(actual)!==norm(selected))reasons.push(key+' incompatible');
 }
 bound(number(row.floor),c.floorMin,c.floorMax,'étage non précisé','étage inférieur au minimum','étage supérieur au maximum');
 const recency=number(c.publicationDays);
 if(recency!==null){
  const publication=row.publicationDate||row.firstDiscovered,ts=publication?Date.parse(publication+'T00:00:00Z'):NaN;
  if(!Number.isFinite(ts))unknown.push('date de publication inconnue');else{
   const day=Date.UTC(today.getFullYear(),today.getMonth(),today.getDate());if((day-ts)/86400000>recency)reasons.push('annonce plus ancienne que la période choisie');
   if(row.publicationDateUncertain)unknown.push('date de publication approximative');
  }
 }
 for(const requirement of String(c.mustHaves||'').split(/[,;\n]/).map(norm).filter(Boolean))if(!text.includes(requirement))unknown.push(requirement+' à confirmer');
 const move=norm(c.moveDate),availability=norm(row.availability);
 if(mode==='rent'&&move&&!['sans preference','indifferent','flexible','any','no preference'].includes(move)){
  if(/immediat|immediately|asap|maintenant/.test(move)?!/immediat|immediately|now/.test(availability):!availability.includes(move))unknown.push('date de disponibilité à confirmer');
 }
 if(mode==='sale'){
  bound(fees,null,c.maxCondoFees,'charges de copropriété non précisées','','charges de copropriété au-dessus du maximum');
  row.renovation=renovation(row,c,override,config);
  for(const [cap,value,label] of [[c.maxRenovation,row.renovation.high,'budget rénovation'],[c.maxCombined,price===null||row.renovation.high===null?null:price+row.renovation.high,'total achat + rénovation']]){
   if(number(cap)!==null){if(value===null)(c.includeUnknownRenovation?unknown:reasons).push(label+' inconnu');else if(value>Number(cap))reasons.push(label+' supérieur au maximum')}
  }
  bound(price!==null&&area>0?price/area:null,null,c.maxPricePerM2,'prix au m² inconnu','','prix au m² supérieur au maximum');
 }
 row.matchReasons=[...new Set(reasons)];row.unknownReasons=[...new Set(unknown)];
 row.matchState=reasons.length?'failed':unknown.length?'unknown':'confirmed';row.type={failed:'excluded',unknown:'wildcard',confirmed:'match'}[row.matchState];
 row.match=reasons.length||unknown.length?[...row.matchReasons,...row.unknownReasons].join(' · '):'Critères confirmés dans les informations disponibles.';
 return row;
}
function sort(rows,order='relevance'){
 const fields={price:'price',area:'area',bedrooms:'bedrooms',published:'publicationDate',discovered:'firstDiscovered'};
 let [base,direction]=order.split('_');if(order==='relevance'){base='price';direction='asc'}
 const field=fields[base]||'price';
 const values=r=>['published','discovered'].includes(base)?(r[field]?Date.parse(r[field]):null):number(r[field]);
 const sorted=[...rows].sort((a,b)=>{const av=values(a),bv=values(b);if(av===null||!Number.isFinite(av))return bv===null||!Number.isFinite(bv)?0:1;if(bv===null||!Number.isFinite(bv))return -1;return (av-bv)*(direction==='desc'?-1:1)});
 if(order!=='relevance')return sorted;
 const buckets=new Map();for(const r of sorted){const source=r.source||'Autre';if(!buckets.has(source))buckets.set(source,[]);buckets.get(source).push(r)}
 const result=[];while(buckets.size)for(const [key,bucket] of buckets){result.push(bucket.shift());if(!bucket.length)buckets.delete(key)}return result;
}
function selectGems(rows){return rows.filter(r=>r.gem&&r.matchState!=='failed'&&r.unknownReasons.length<=1).map(r=>({...r,gem:{...r.gem,needsReview:r.matchState==='unknown',label:r.matchState==='unknown'?'À regarder de près':'À visiter en priorité',cautions:[...r.unknownReasons,...r.gem.cautions].slice(0,2)}})).sort((a,b)=>Number(a.gem.needsReview)-Number(b.gem.needsReview)||b.gem.score-a.gem.score||a.price-b.price).slice(0,5)}
root.NinouSearch={norm,number,areaMatches,evaluate,sort,selectGems};
})(globalThis);
