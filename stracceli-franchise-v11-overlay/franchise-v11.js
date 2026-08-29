(()=>{'use strict';
const $=(s,p=document)=>p.querySelector(s),$$=(s,p=document)=>[...p.querySelectorAll(s)];
const P=[['la-stracceli','La Stracceli'],['la-pancetta','La Pancetta'],['il-pastrami','Il Pastrami'],['la-bresaola','La Bresaola'],['la-milano','La Milano'],['la-piccante','La Piccante'],['l-agnello','L’Agnello'],['il-tacchino','Il Tacchino'],['il-vitello','Il Vitello'],['il-pollo','Il Pollo']];
const D=[['lurisia-gazzosa','Gazzosa'],['lurisia-limonata','Limonata'],['lurisia-chinotto','Chinotto'],['lurisia-aranciata','Aranciata'],['lurisia-aranciata-rossa','Aranciata Rossa']];
const S=[['straccelito-bueno','Bueno'],['straccelito-speculoos','Spéculoos'],['straccelito-mms','M&M’s'],['straccelito-peanut','Peanut Caramel'],['straccelito-choco','Choco Praliné'],['straccelito-supreme','Suprême']];
const STORAGE='stracceli-franchise-menu-compositions';
const CART='stracceli-fast-v2-cart';
let chosen={p:null,d:null,s:null};
const readComps=()=>{try{return JSON.parse(localStorage.getItem(STORAGE)||'[]')}catch{return[]}};
const writeComps=x=>localStorage.setItem(STORAGE,JSON.stringify(x));
const label=(arr,id)=>arr.find(x=>x[0]===id)?.[1]||id||'';
function safeText(v){return String(v||'').replace(/[<>]/g,'').slice(0,180)}
function fixLurisia(){
 const a=window.STRACCELI_LURISIA||{};
 $$('.bottle').forEach(card=>{const name=card.querySelector('h3')?.textContent?.trim();const img=card.querySelector('img');if(!img)return;if(name==='Aranciata'&&a.aranciata)img.src=a.aranciata;if(name==='Aranciata Rossa'&&a.rossa)img.src=a.rossa;img.onerror=()=>{if(name==='Aranciata'&&a.aranciata)img.src=a.aranciata;if(name==='Aranciata Rossa'&&a.rossa)img.src=a.rossa};});
}
function enhanceNavigation(){
 const addLink=(nav,afterText)=>{if(!nav||nav.querySelector('a[href="#composer"]'))return;const ref=[...nav.querySelectorAll('a')].find(a=>a.textContent.trim().toLowerCase().includes(afterText));const a=document.createElement('a');a.href='#composer';a.textContent='COMPOSER MON MENU';if(ref)ref.after(a);else nav.prepend(a)};
 addLink($('.nav'),'panuoz');addLink($('.mobile-nav nav'),'panuoz');addLink($('.category-nav'),'panuoz');
 const heroA=$('.hero-actions a');if(heroA){heroA.innerHTML='COMMANDER MAINTENANT <b>→</b>';heroA.href='#menu'}
 const heroB=$('.hero-actions button');if(heroB){heroB.textContent='COMPOSER MON MENU';heroB.onclick=e=>{e.preventDefault();document.querySelector('#composer')?.scrollIntoView({behavior:'smooth',block:'start'})}}
 const quick=$('.quick-cart');if(quick)quick.childNodes[0].nodeValue='COMMANDER ';
}
function optionButtons(arr,type){return arr.map(([id,name])=>`<button type="button" class="builder-option" data-builder-type="${type}" data-builder-id="${id}"><span>${name}</span><b>Choisir</b></button>`).join('')}
function insertBuilder(){
 if($('#composer'))return;
 const menu=$('#menu');if(!menu)return;
 const sec=document.createElement('section');sec.id='composer';sec.className='menu-builder';
 sec.innerHTML=`<div class="shell"><div class="builder-head"><div><div class="eyebrow">LA FORMULE À TON GOÛT</div><h2>Compose ton menu.<br><em>En 3 choix.</em></h2></div><div class="builder-pitch">Choisis ton panuozzo, ta Lurisia et ton STRACCELITO. Un parcours rapide, clair et pensé comme une vraie enseigne de restauration rapide.</div></div><div class="builder-steps"><article class="builder-step"><small>ÉTAPE 01</small><h3>Ton Panuozzo</h3><div class="builder-options">${optionButtons(P,'p')}</div></article><article class="builder-step"><small>ÉTAPE 02</small><h3>Ta Lurisia</h3><div class="builder-options">${optionButtons(D,'d')}</div></article><article class="builder-step"><small>ÉTAPE 03</small><h3>Ton STRACCELITO</h3><div class="builder-options">${optionButtons(S,'s')}</div></article></div><div class="builder-summary"><div><strong id="builder-title">Ton menu STRACCELI — 21,90 €</strong><small id="builder-detail">Choisis les 3 éléments pour ajouter ton menu.</small></div><button class="builder-add" id="builder-add" disabled>AJOUTER MON MENU · 21,90 €</button></div></div>`;
 menu.after(sec);
 $$('.builder-option',sec).forEach(b=>b.onclick=()=>{const type=b.dataset.builderType;chosen[type]=b.dataset.builderId;$$(`.builder-option[data-builder-type="${type}"]`,sec).forEach(x=>x.classList.toggle('selected',x===b));updateBuilder()});
 $('#builder-add',sec).onclick=addComposedMenu;updateBuilder();
}
function updateBuilder(){
 const ready=chosen.p&&chosen.d&&chosen.s;const detail=$('#builder-detail'),btn=$('#builder-add');if(detail)detail.textContent=ready?`${label(P,chosen.p)} · Lurisia ${label(D,chosen.d)} · STRACCELITO ${label(S,chosen.s)}`:'Choisis les 3 éléments pour ajouter ton menu.';if(btn)btn.disabled=!ready;
}
function addComposedMenu(){
 if(!(chosen.p&&chosen.d&&chosen.s))return;
 const comp={p:chosen.p,d:chosen.d,s:chosen.s,text:`${label(P,chosen.p)} + Lurisia ${label(D,chosen.d)} + STRACCELITO ${label(S,chosen.s)}`};const list=readComps();list.push(comp);writeComps(list);
 const formula=$('[data-add-id="il-completo"]');if(formula)formula.click();
 const btn=$('#builder-add');if(btn){const old=btn.textContent;btn.textContent='MENU AJOUTÉ ✓';setTimeout(()=>btn.textContent=old,1300)}
 annotateCart();
}
function insertFinalCTA(){
 if($('.franchise-cta'))return;const target=$('#straccelito');if(!target)return;const sec=document.createElement('section');sec.className='franchise-cta';sec.innerHTML=`<div class="shell franchise-cta-inner"><div><h2>Ton STRACCELI.<br>À toi de choisir.</h2><p>Panuozzo, menu composé, Lurisia, STRACCELITO : commande en quelques clics.</p></div><div class="franchise-cta-actions"><button type="button" id="cta-order">COMMANDER MAINTENANT</button><a href="#composer">COMPOSER MON MENU</a></div></div>`;target.after(sec);$('#cta-order').onclick=()=>$('.header-cart')?.click();
 const float=document.createElement('button');float.className='desktop-order-float';float.textContent='COMMANDER MAINTENANT';float.onclick=()=>$('.header-cart')?.click();document.body.append(float);
}
function annotateCart(){
 const comps=readComps();let index=0;$$('.cart-row').forEach(row=>{const h=row.querySelector('h4');if(!h||h.textContent.trim()!=='Il Completo')return;let note=row.querySelector('.franchise-composition');if(!note){note=document.createElement('small');note.className='franchise-composition';note.style.cssText='display:block;margin-top:7px;color:#174b31;font-weight:800;line-height:1.45';h.after(note)}const current=comps.slice(index);note.textContent=current.length?current.map((c,i)=>`Menu ${i+1}: ${c.text}`).join(' · '):'Menu composé';index+=current.length});
 try{const cart=JSON.parse(localStorage.getItem(CART)||'[]');const qty=cart.filter(x=>x.id==='il-completo').reduce((s,x)=>s+(Number(x.qty)||0),0);if(comps.length>qty)writeComps(comps.slice(0,qty))}catch{}
}
function interceptOrders(){
 const native=window.fetch.bind(window);window.fetch=async function(input,init){
   try{const url=typeof input==='string'?input:input?.url||'';if(url.includes('/api/order')&&String(init?.method||'GET').toUpperCase()==='POST'&&init?.body){const body=JSON.parse(init.body),comps=readComps();if(Array.isArray(body.items)&&comps.length){let ci=0;body.items=body.items.map(item=>{if(item.id!=='il-completo')return item;const count=Number(item.qty)||1;const used=comps.slice(ci,ci+count);ci+=count;return {...item,note:safeText(used.map((c,i)=>`Menu ${i+1}: ${c.text}`).join(' | '))}});init={...init,body:JSON.stringify(body)}}}
   }catch(e){}
   const res=await native(input,init);try{const url=typeof input==='string'?input:input?.url||'';if(url.includes('/api/order')&&String(init?.method||'GET').toUpperCase()==='POST'&&res.ok)localStorage.removeItem(STORAGE)}catch(e){}return res;
 };
}
function init(){
 fixLurisia();enhanceNavigation();insertBuilder();insertFinalCTA();interceptOrders();
 const obs=new MutationObserver(()=>{fixLurisia();annotateCart()});const cart=$('.cart-lines');if(cart)obs.observe(cart,{childList:true,subtree:true});const drinks=$('#lurisia-grid');if(drinks)obs.observe(drinks,{childList:true,subtree:true});
 setTimeout(fixLurisia,250);setTimeout(fixLurisia,1000);
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
