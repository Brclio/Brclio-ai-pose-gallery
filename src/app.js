'use strict';
const META=__META__;
const D=__DATA__;
const UI=__UI_I18N__;
const POSE_I18N=__POSE_I18N__;
const ANG=['正面','上から','下から','横','斜め'];
const LINES=META.lines;
const LANGS=['zh','en','ja'];
const LOCALES={zh:'zh-CN',en:'en',ja:'ja-JP'};
const STORAGE_KEY='pose-gallery-language';
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const normalize=s=>String(s).normalize('NFKC').toLocaleLowerCase().trim();
const catOf=d=>(d.分類||'').trim();
const keyOf=d=>d.系統+'|'+d.ポーズ番号;
function initialLanguage(){
  const query=new URLSearchParams(location.search).get('lang');
  if(LANGS.includes(query))return query;
  try{const saved=localStorage.getItem(STORAGE_KEY);if(LANGS.includes(saved))return saved}catch{}
  return 'zh';
}
let lang=initialLanguage();
const S={line:'',cat:'',ang:'',q:'',view:'pose'};
const t=(key,values={})=>UI[lang].labels[key].replace(/\{(\w+)\}/g,(_,name)=>String(values[name]??''));
const label=(kind,key)=>UI[lang][kind][key]??key;
const fmt=n=>Number(n).toLocaleString(LOCALES[lang]);
const quantity=(kind,n)=>t(kind+'Count'+(n===1?'One':''),{n:fmt(n)});
const poseName=d=>lang==='ja'?d.ポーズ名:POSE_I18N[keyOf(d)][lang];
const POSES=[],PMAP=new Map();
D.forEach(d=>{
  const key=keyOf(d);
  if(!PMAP.has(key)){const p={key,series:d.系統,number:d.ポーズ番号,category:catOf(d),a:{},items:[]};PMAP.set(key,p);POSES.push(p)}
  const p=PMAP.get(key);p.items.push(d);if(!p.a[d.アングル])p.a[d.アングル]=d;
});
POSES.sort((a,b)=>LINES.indexOf(a.series)-LINES.indexOf(b.series)||a.number.localeCompare(b.number));
POSES.forEach(p=>{p.order=ANG.map(a=>p.a[a]).filter(Boolean)});
const SHOWN=LINES.filter(l=>D.some(d=>d.系統===l));
// Index every language together so changing language never invalidates a search.
const SEARCH=new Map(D.map(d=>[d.id,normalize([
  d.ポーズ名,d.id,d.ポーズ番号,d.系統,catOf(d),d.アングル,
  ...['zh','en'].flatMap(l=>[POSE_I18N[keyOf(d)][l],UI[l].lines[d.系統],UI[l].categories[catOf(d)],UI[l].angles[d.アングル]])
].join(' '))]));
let VIEWLIST=[],M={i:0,d:null},previousFocus=null,qt;
function hit(d){return (!S.line||d.系統===S.line)&&(!S.cat||catOf(d)===S.cat)&&(!S.ang||d.アングル===S.ang)&&(!S.q||SEARCH.get(d.id).includes(S.q))}
function drawTabs(){
  const entries=[['',t('all'),D.length,POSES.length],...SHOWN.map(l=>[l,label('lines',l),D.filter(d=>d.系統===l).length,POSES.filter(p=>p.series===l).length])];
  $('#tabs').innerHTML=entries.map(([value,text,n,np])=>`<button class="tab" role="tab" data-v="${esc(value)}" aria-selected="${S.line===value}">${esc(text)}<em>${esc(t('tabCount',{images:quantity('image',n),poses:quantity('pose',np)}))}</em></button>`).join('');
}
function drawCats(){
  const categories=[...new Set(D.filter(d=>!S.line||d.系統===S.line).map(catOf).filter(Boolean))].sort((a,b)=>label('categories',a).localeCompare(label('categories',b),LOCALES[lang]));
  $('#cat').innerHTML=`<option value="">${esc(t('allCategories'))}</option>`+categories.map(c=>`<option value="${esc(c)}"${c===S.cat?' selected':''}>${esc(label('categories',c))}</option>`).join('');
}
function drawAngles(){
  $('#ang').innerHTML=['',...ANG].map(a=>`<button data-v="${a}" aria-pressed="${S.ang===a}">${esc(a?label('angles',a):t('allAngles'))}</button>`).join('');
}
function draw(){
  if(S.view==='pose'){
    const poses=POSES.filter(p=>p.items.some(hit));
    VIEWLIST=poses.map(p=>({p,d:(S.ang&&p.a[S.ang])||p.order[0]}));
    $('#count').textContent=t('showPoses',{poses:quantity('pose',poses.length),images:quantity('image',poses.reduce((n,p)=>n+p.items.filter(hit).length,0))});
    $('#grid').innerHTML=VIEWLIST.map(({p,d},i)=>`<article class="card" tabindex="0" data-i="${i}" aria-label="${esc(poseName(d))}">
      <div class="ph"><img loading="lazy" decoding="async" src="${esc(d.サムネ)}" alt="${esc(poseName(d))}"><div class="badge"><span>${esc(p.number)}</span></div></div>
      <div class="meta"><h3>${esc(poseName(d))}</h3><div class="id">${esc(label('lines',p.series))}・${esc(p.number)}</div>${p.category?`<div class="cat">${esc(label('categories',p.category))}</div>`:''}</div>
      <div class="strip">${ANG.filter(a=>p.a[a]).map(a=>{const x=p.a[a],name=label('angles',a);return `<button data-a="${a}" class="${x===d?'on':''}" title="${esc(name)}" aria-label="${esc(name)}"><img loading="lazy" decoding="async" src="${esc(x.サムネ)}" alt="${esc(name)}"><span>${esc(name)}</span></button>`}).join('')}</div></article>`).join('');
  }else{
    const images=D.filter(hit);VIEWLIST=images.map(d=>({p:PMAP.get(keyOf(d)),d}));
    $('#count').textContent=t('showImages',{images:quantity('image',images.length)});
    $('#grid').innerHTML=VIEWLIST.map(({d},i)=>`<article class="card" tabindex="0" data-i="${i}" aria-label="${esc(poseName(d))}"><div class="ph"><img loading="lazy" decoding="async" src="${esc(d.サムネ)}" alt="${esc(poseName(d))}"><div class="badge"><span>${esc(label('angles',d.アングル))}</span></div></div><div class="meta"><h3>${esc(poseName(d))}</h3><div class="id">${esc(d.id)}</div><div class="cat">${esc(label('lines',d.系統))}${catOf(d)?'・'+esc(label('categories',catOf(d))):''}</div></div></article>`).join('');
  }
  if(!VIEWLIST.length)$('#grid').innerHTML=`<div class="empty" style="grid-column:1/-1"><b>${esc(t(D.length?'emptyMatch':'emptyGallery'))}</b>${D.length?esc(t('emptyHint')):''}</div>`;
  const filters=[S.cat,S.ang].filter(Boolean).length+(S.view==='card'?1:0);$('#fn').textContent=filters||'';
}
function translateStatic(){
  document.documentElement.lang=lang==='zh'?'zh-CN':lang;
  document.title=t('title');
  $$('[data-i18n]').forEach(el=>{el.textContent=t(el.dataset.i18n)});
  $$('[data-i18n-aria]').forEach(el=>el.setAttribute('aria-label',t(el.dataset.i18nAria)));
  $$('[data-i18n-list]').forEach(el=>{el.innerHTML=UI[lang][el.dataset.i18nList].map(text=>`<li>${esc(text)}</li>`).join('')});
  $$('[data-lang]').forEach(button=>button.setAttribute('aria-pressed',button.dataset.lang===lang));
  $('#q').placeholder=t('search');
}
function changeLanguage(next){
  if(!LANGS.includes(next)||next===lang)return;
  clearTimeout(qt);S.q=normalize($('#q').value);
  const current=M.d,wasOpen=$('#modal').classList.contains('open');
  const anchor=wasOpen?VIEWLIST[M.i]:null;
  lang=next;
  try{localStorage.setItem(STORAGE_KEY,lang)}catch{}
  // Keep explicit language links consistent with a later user selection.
  try{const url=new URL(location.href);if(url.searchParams.has('lang')){url.searchParams.set('lang',lang);history.replaceState(null,'',url)}}catch{}
  translateStatic();drawTabs();drawCats();drawAngles();draw();
  if(wasOpen){const i=VIEWLIST.findIndex(it=>S.view==='pose'?it.p.key===anchor.p.key:it.d.id===anchor.d.id);if(i>=0){M={i,d:current};showM()}else closeM()}
}
$$('[data-lang]').forEach(button=>button.addEventListener('click',()=>changeLanguage(button.dataset.lang)));
$('#tabs').onclick=e=>{const button=e.target.closest('.tab');if(!button)return;S.line=button.dataset.v;S.cat='';drawTabs();drawCats();draw()};
$('#ang').onclick=e=>{const button=e.target.closest('button');if(!button)return;S.ang=button.dataset.v;drawAngles();draw()};
$('#view').onclick=e=>{const button=e.target.closest('button');if(!button)return;S.view=button.dataset.v;[...$('#view').children].forEach(x=>x.setAttribute('aria-pressed',x===button));draw()};
$('#cat').onchange=e=>{S.cat=e.target.value;draw()};
$('#q').oninput=e=>{clearTimeout(qt);qt=setTimeout(()=>{S.q=normalize(e.target.value);draw()},120)};
function previewAngle(e){
  const button=e.target.closest('.strip button');if(!button)return;
  const card=button.closest('.card'),item=VIEWLIST[+card.dataset.i];
  item.d=item.p.a[button.dataset.a];
  const img=card.querySelector('.ph img');img.src=item.d.サムネ;img.alt=poseName(item.d)+' '+label('angles',item.d.アングル);
  card.querySelectorAll('.strip button').forEach(x=>x.classList.toggle('on',x===button));
}
$('#grid').addEventListener('mouseover',previewAngle);
$('#grid').addEventListener('focusin',previewAngle);
$('#grid').addEventListener('click',e=>{const card=e.target.closest('.card');if(!card)return;const item=VIEWLIST[+card.dataset.i],button=e.target.closest('.strip button');openM(+card.dataset.i,button?item.p.a[button.dataset.a]:item.d)});
$('#grid').addEventListener('keydown',e=>{if(e.target.closest('button'))return;if(e.key==='Enter'||e.key===' '){const card=e.target.closest('.card');if(card){e.preventDefault();openM(+card.dataset.i,VIEWLIST[+card.dataset.i].d)}}});
function setBackgroundInert(value){$$('header.hero,.tools,main,footer').forEach(el=>{el.inert=value})}
function openM(i,d){previousFocus=document.activeElement;M={i,d};$('#modal').classList.add('open');document.body.style.overflow='hidden';setBackgroundInert(true);showM();$('#mclose').focus({preventScroll:true})}
function closeM(){
  $('#modal').classList.remove('open');document.body.style.overflow='';setBackgroundInert(false);
  const target=previousFocus?.isConnected?previousFocus:document.querySelector(`.card[data-i="${M.i}"]`);
  target?.focus({preventScroll:true});
}
function showM(){
  const p=VIEWLIST[M.i].p,d=M.d,img=$('#mimg');
  img.src=d.サムネ;
  const full=new Image();full.onload=()=>{if(M.d===d&&$('#modal').classList.contains('open'))img.src=d.原寸};full.src=d.原寸;
  img.alt=poseName(d)+' '+label('angles',d.アングル);
  $('#mdl').href=d.原寸;$('#mdl').setAttribute('download',d.id+'.png');
  $('#mtitle').textContent=poseName(d);$('#mid').textContent=d.id;
  $('#mang').innerHTML=ANG.filter(a=>p.a[a]).map(a=>{const x=p.a[a],name=label('angles',a);return `<button data-a="${a}" class="${x===d?'on':''}" aria-pressed="${x===d}" aria-label="${esc(name)}"><img src="${esc(x.サムネ)}" alt="${esc(name)}"><span>${esc(name)}</span></button>`}).join('');
  $('#mkv').innerHTML=[['series',label('lines',d.系統)],['poseNumber',d.ポーズ番号],['category',label('categories',catOf(d))],['angle',label('angles',d.アングル)]].filter(([,v])=>v).map(([key,value])=>`<dt>${esc(t(key))}</dt><dd>${esc(value)}</dd>`).join('');
}
function stepA(delta){const order=VIEWLIST[M.i].p.order;M.d=order[(order.indexOf(M.d)+delta+order.length)%order.length];showM()}
function stepP(delta){
  const currentKey=VIEWLIST[M.i].p.key;let next=M.i+delta;
  while(next>=0&&next<VIEWLIST.length&&VIEWLIST[next].p.key===currentKey)next+=delta;
  if(next<0||next>=VIEWLIST.length)return;
  const p=VIEWLIST[next].p;M.i=next;M.d=p.a[M.d.アングル]||VIEWLIST[next].d;showM();
}
$('#mang').onclick=e=>{const button=e.target.closest('button');if(!button)return;M.d=VIEWLIST[M.i].p.a[button.dataset.a];showM();$('#mang').querySelector(`[data-a="${M.d.アングル}"]`).focus({preventScroll:true})};
$('#mprev').onclick=()=>stepA(-1);$('#mnext').onclick=()=>stepA(1);$('#mclose').onclick=closeM;
$('#modal').onclick=e=>{if(e.target.id==='modal')closeM()};
document.addEventListener('keydown',e=>{
  if(!$('#modal').classList.contains('open'))return;
  if(e.key==='Escape'){e.preventDefault();closeM()}
  else if(['ArrowRight','ArrowLeft','ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();if(e.key==='ArrowRight')stepA(1);if(e.key==='ArrowLeft')stepA(-1);if(e.key==='ArrowDown')stepP(1);if(e.key==='ArrowUp')stepP(-1)}
  else if(e.key==='Tab'){
    const items=[...$('#modal').querySelectorAll('button,a[href]')].filter(el=>el.getClientRects().length);
    const first=items[0],last=items[items.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
  }
});
let touchX=null;
$('#mimg').addEventListener('touchstart',e=>{touchX=e.touches[0].clientX},{passive:true});
$('#mimg').addEventListener('touchend',e=>{if(touchX===null)return;const delta=e.changedTouches[0].clientX-touchX;if(Math.abs(delta)>40)stepA(delta<0?1:-1);touchX=null});
$('#mimg').addEventListener('touchcancel',()=>{touchX=null});
$('#ftog').onclick=()=>{const open=$('#more').classList.toggle('open');$('#ftog').setAttribute('aria-expanded',open)};
// Keep the original help popovers and their outside-click behavior.
(()=>{
  const nav=$('#infotabs'),tabs=[...nav.querySelectorAll('.itab')];let current=null;
  const close=back=>{if(!current)return;const button=current;button.setAttribute('aria-expanded','false');$('#'+button.getAttribute('aria-controls')).hidden=true;current=null;if(back)button.focus()};
  const open=button=>{if(current===button){close(true);return}close(false);current=button;button.setAttribute('aria-expanded','true');const panel=$('#'+button.getAttribute('aria-controls'));panel.hidden=false;panel.style.top=innerWidth<=560?(button.getBoundingClientRect().bottom+8)+'px':'';panel.focus({preventScroll:true})};
  tabs.forEach((button,i)=>{button.addEventListener('click',()=>open(button));button.addEventListener('keydown',e=>{if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();const next=tabs[(i+(e.key==='ArrowRight'?1:tabs.length-1))%tabs.length];next.focus();if(current)open(next)}})});
  nav.querySelectorAll('.ipclose').forEach(button=>button.addEventListener('click',()=>close(true)));
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&current){e.stopPropagation();close(true)}},true);
  let swallow=false;
  document.addEventListener('pointerdown',e=>{if(current&&!nav.contains(e.target)){close(false);if(!e.target.closest('[data-lang]')){swallow=true;setTimeout(()=>swallow=false,600)}}},true);
  document.addEventListener('click',e=>{if(swallow){swallow=false;e.preventDefault();e.stopPropagation()}},true);
  addEventListener('scroll',()=>{if(current&&innerWidth<=560)close(false)},{passive:true});
  addEventListener('resize',()=>close(false));
})();
translateStatic();drawTabs();drawCats();drawAngles();draw();
