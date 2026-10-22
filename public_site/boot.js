/* Static-site controls: search the shared catalogue without starting a scrape. */
$('runBtn').textContent='Appliquer les filtres';
$('runBtn').onclick=async()=>{const button=$('runBtn');button.disabled=true;try{await persistCurrentCriteria();await loadListings(true);updateHeroAreas(criteria);toast('Recherche mise à jour.')}catch(e){toast(e.message,true)}finally{button.disabled=false;button.textContent='Appliquer les filtres'}};
$('criteriaForm').onsubmit=async ev=>{ev.preventDefault();const button=$('saveBtn');button.disabled=true;try{await persistCurrentCriteria();await loadListings(true);updateHeroAreas(criteria);toast('Tes critères sont enregistrés dans ce navigateur.')}catch(e){toast(e.message,true)}finally{button.disabled=false}};

setInterval(async()=>{if(document.hidden)return;try{if(await window.refreshPublicCatalogue()){await loadListings(true);await loadStatus();await refreshLastRunHeader(true)}}catch{}},60000);
