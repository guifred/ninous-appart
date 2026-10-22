const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
function browser(){
 const storage=new Map(),requests=[];
 const items=Array.from({length:205},(_,i)=>({id:String(i+1),title:'Appartement',location:'1050 Ixelles',price:1001+i,area:80,bedrooms:2,photos:['https://agency.example/room.jpg'],source:'Agency',features:{}}));
 const manifest={revision:'one',files:{rent:'rent-test.json',sale:'sale-test.json'},config:{defaults:{rent:{areas:'Ixelles',features:{}},sale:{areas:'Ixelles',features:{}}},areaAliases:{ixelles:['1050-elsene','Ixelles']}};
 const fetch=async input=>{const url=String(input);requests.push(url);assert.ok(url.startsWith('https://guifred.github.io/ninous-appart/data/'));return new Response(JSON.stringify(url.endsWith('manifest.json')?manifest:{items,status:{state:'complete',lastRun:'2026-10-22T10:00:00+02:00'}}))};
 const ctx=vm.createContext({URL,Response,Date,console,location:{href:'https://guifred.github.io/ninous-appart/',origin:'https://guifred.github.io'},document:{currentScript:{src:'https://guifred.github.io/ninous-appart/api.js'}},localStorage:{getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v)},window:{fetch}});
 vm.runInContext(fs.readFileSync('public_site/search.js','utf8'),ctx);vm.runInContext(fs.readFileSync('public_site/api.js','utf8'),ctx);
 return {api:async(path,options)=>(await ctx.window.fetch(path,options)).json(),requests,storage};
}
test('Each visitor has independent criteria and all 205 map markers can be loaded',async()=>{
 const a=browser(),b=browser();
 const saved=await a.api('/api/criteria?mode=rent',{method:'POST',body:JSON.stringify({maxBudget:1005})});assert.equal(saved.ok,true);
 assert.equal((await a.api('/api/listings?mode=rent')).total,5);
 assert.equal((await b.api('/api/listings?mode=rent')).total,205);
 let records=[];for(let p=1;p<=3;p++)records.push(...(await a.api('/api/listings?mode=rent&section=all&pageSize=100&page='+p)).items);
 assert.equal(records.length,205);assert.equal(new Set(records.map(r=>r.id)).size,205);
 assert.equal((await a.api('/api/status?mode=rent')).matchingCount,5);
 assert.equal((await a.api('/api/photos?mode=rent&id=1')).photos.length,1);
 assert.equal((await a.api('/api/listing-validity?mode=rent&ids=1,999')).validIds.join(','),'1');
 assert.ok(a.requests.every(url=>!url.includes('/api/')));
});
test('Invalid budget is rejected and does not change preferences',async()=>{
 const a=browser();const result=await a.api('/api/criteria?mode=rent',{method:'POST',body:JSON.stringify({minBudget:1500,maxBudget:1000})});
 assert.equal(result.ok,false);assert.equal((await a.api('/api/listings?mode=rent')).total,205);
});
