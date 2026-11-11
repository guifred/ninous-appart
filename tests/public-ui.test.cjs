const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync('app.js','utf8');
const summary=source.slice(source.indexOf('function conciseSummary('),source.indexOf('function card(',source.indexOf('function conciseSummary(')));
const energy=source.slice(source.indexOf('function energyLabel('),source.indexOf('function conciseSummary(',source.indexOf('function energyLabel(')));
const type=source.slice(source.indexOf('function typeOf('),source.indexOf('function renovationMarkup(',source.indexOf('function typeOf(')));
const context={
  foldArea:s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim(),
  esc:s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;'),
};
vm.runInNewContext(type+energy+summary,context);

test('Every card variant includes the same facts and French summary',()=>{
  const cardSource=source.slice(source.indexOf('function card('),source.indexOf('window.__listingRecords=',source.indexOf('function card(')));
  const cardContext={...context,mode:'coast',typeOf:()=> 'Appartement',isFavorite:()=>false,money:n=>String(n),favoriteKey:()=> 'coast:1',agencyMarkup:()=>'',listingHighlights:()=>'<div class="listing-highlights">Atouts</div>',renovationMarkup:()=>'<div class="reno-simple">Travaux</div>',gemNotes:()=>'<div class="gem-notes">Pépite</div>',dateLabel:()=> 'Aujourd’hui'};
  vm.runInNewContext(cardSource,cardContext);
  const row={id:'1',url:'https://agency.example/1',title:'Appartement',location:'8620 Nieuwpoort',price:200000,photos:[],summary:'Appartement rénové avec terrasse.',condition:'renovated',features:{terrace:true},energyRating:'C',energyRegion:'EPC · Flandre',beachDistanceM:300,beachDistanceBasis:'listing-text'};
  for(const variant of [cardContext.card(row),cardContext.card(row,true,'coast'),cardContext.card(row,false,'coast',true)]){
    assert.match(variant,/<b>Type<\/b>Appartement/);
    assert.match(variant,/<b>État<\/b>Rénové/);
    assert.match(variant,/<b>Énergie<\/b>PEB C \(EPC\)/);
    assert.match(variant,/PEB C \(EPC\)/);
    assert.match(variant,/summary-points/);
    assert.match(variant,/listing-highlights/);
    assert.match(variant,/Plage : env\. 300 m/);
  }
  assert.match(cardContext.card(row,false,'coast',true),/gem-notes/);
});

test('Map groups approximate postal positions without inventing a Brussels coordinate',()=>{
  const mapSource=source.slice(source.indexOf('const geoApprox='),source.indexOf('let restoredView=',source.indexOf('const geoApprox=')));
  const mapContext={...context};
  vm.runInNewContext(mapSource,mapContext);
  const postalA=mapContext.mapPoint({id:'a',postalCode:'8620'});
  const postalB=mapContext.mapPoint({id:'b',postalCode:'8620'});
  const address=mapContext.mapPoint({id:'c',latitude:51.13,longitude:2.75,beachLocationBasis:'verified-address'});
  assert.equal(postalA.kind,'postal');
  assert.equal(address.kind,'address');
  assert.equal(mapContext.mapPoint({id:'unknown',postalCode:'9999'}),null);
  const groups=mapContext.groupMapPoints([postalA,postalB,address],12,(lat,lng)=>({x:lng*100,y:lat*100}));
  assert.equal(groups.length,2);
  assert.equal(groups.find(group=>group.kind==='postal').items.length,2);
});

test('Flemish EPC label is shown as the PEB class',()=>{
  assert.equal(context.energyLabel({energyRating:'C',energyRegion:'EPC · Flandre'}),'PEB C (EPC)');
  assert.equal(context.energyLabel({energyRating:'D+',energyRegion:'PEB · Bruxelles'}),'PEB D+');
});

test('Dutch property facts are presented in French',()=>{
  const result=context.conciseSummary({title:'Woning te koop',summary:'Volledig gerenoveerde woning met terras en zicht op zee.',condition:'renovated',features:{terrace:true}});
  assert.match(result,/Rénové/);
  assert.match(result,/Vue sur la mer/);
  assert.match(result,/Terrasse/);
  assert.doesNotMatch(result,/gerenoveerde|woning|zeezicht/i);
  assert.equal(context.typeOf({title:'Woning te koop'}),'Maison');
});

test('English sale and rental details are translated without copying prose',()=>{
  const sale=context.conciseSummary({summary:'For sale through a life annuity arrangement. The flat has a lift.',features:{lift:true}});
  assert.match(sale,/Vente en viager/);
  assert.match(sale,/Ascenseur/);
  assert.doesNotMatch(sale,/life annuity/i);
  const rent=context.conciseSummary({summary:'Shared apartment with rooms for rent near shops and public transport.',features:{}});
  assert.match(rent,/Colocation ou chambre à louer/);
  assert.match(rent,/Commerces à proximité/);
});
