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
