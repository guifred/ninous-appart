function publicSearchCases(){
 const s=NinouSearch,config={renovationRates:{cosmetic:[400,800]},areaAliases:{ixelles:['1050-elsene','Ixelles'],uccle:['1180-ukkel','Uccle']},nearby:{}};
 const row={id:'one',title:'Appartement',location:'1050 Ixelles',price:1000,fees:null,bedrooms:2,area:80,features:{terrace:true},firstDiscovered:'2026-10-01',publicationDate:'2026-10-01',publicationDateUncertain:false};
 const check=(condition,msg)=>{if(!condition)throw new Error(msg)};
 check(s.evaluate(row,{maxBudget:1200},'rent',config).matchState==='confirmed','Affordable rent');
 check(s.evaluate(row,{maxBudget:900},'rent',config).matchState==='failed','Over budget');
 check(s.evaluate(row,{maxBudget:1200,budgetBasis:'rent_and_charges'},'rent',config).matchState==='unknown','Missing charges stay unknown');
 check(s.evaluate(row,{bedrooms:0},'rent',config).matchState==='failed','Studios filter');
 check(s.evaluate(row,{features:{parking:true}},'rent',config).matchState==='unknown','Missing feature');
 check(s.evaluate(row,{features:{terrace:false}},'rent',config).matchState==='failed','Negative feature');
 check(s.evaluate(row,{publicationDays:5},'rent',config,null,new Date('2026-10-22T12:00:00Z')).matchState==='failed','Publication recency');
 check(s.evaluate({...row,price:200000},{maxCombined:210000},'sale',config).matchState==='failed','Combined purchase budget');
 check(s.evaluate({...row,price:200000},{maxCombined:210000},'sale',config,{low:1000,high:2000}).matchState==='confirmed','Personal estimate');
 check(s.areaMatches(row,{areas:'Ixelles'},config),'Selected commune');
 check(!s.areaMatches(row,{areas:'Uccle'},config),'Other commune excluded');
 check(!s.areaMatches(row,{areas:''},config),'Empty selection');
 const sorted=s.sort([{price:null},{price:50},{price:100}],'price_desc');check(sorted[0].price===100&&sorted[2].price===null,'Unknown price sorted last');
 const gem={score:10,cautions:[],reasons:['Terrasse']};check(s.selectGems([{...row,gem,matchState:'failed',unknownReasons:[]}]).length===0,'Failed match never a gem');
 return '14 matching, sorting and preference checks passed';
}
