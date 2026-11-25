// One shared highlight follows the native router's selected entry.
const glassNavigation=(()=>{
 const doc=nativeDocument,reduced=matchMedia('(prefers-reduced-motion: reduce)');let sidebar,capsule,animation,resize,frame=0,lastKey='';
 const css=doc.createElement('style');css.textContent=`
 .sidebar.glass-navigation{isolation:isolate}
 .sidebar.glass-navigation .nav-item{position:relative;z-index:1}
 .sidebar.glass-navigation .nav-item.active{background:transparent!important;box-shadow:none!important;border-color:transparent!important}
 .sidebar .nav-glass-capsule{position:absolute;left:0;top:0;z-index:0;pointer-events:none;box-sizing:border-box;border-radius:999px;border:1px solid color-mix(in srgb,var(--text-primary,#333) 13%,transparent);background:color-mix(in srgb,var(--bg-tertiary,#eee) 70%,transparent);backdrop-filter:blur(18px) saturate(145%);-webkit-backdrop-filter:blur(18px) saturate(145%);box-shadow:inset 0 1px 0 #ffffffaa,inset 0 -1px 0 #ffffff28,0 3px 12px #00000008;transform-origin:center}
 @media(prefers-reduced-motion:reduce){.sidebar .nav-glass-capsule{animation:none!important}}
 `;doc.head.append(css);
 function update(){frame=0;const next=doc.querySelector('.sidebar');if(!next){resize?.disconnect();sidebar=null;capsule=null;lastKey='';return;}
  if(sidebar!==next){animation?.cancel();resize?.disconnect();sidebar=next;sidebar.classList.add('glass-navigation');capsule=doc.createElement('span');capsule.className='nav-glass-capsule';capsule.setAttribute('aria-hidden','true');sidebar.prepend(capsule);resize=new ResizeObserver(schedule);resize.observe(sidebar);lastKey='';}
  const target=doc.documentElement.hasAttribute('data-account-console')?sidebar.querySelector('#account-console-nav'):sidebar.querySelector('.nav-item.active');
  if(!target){capsule.hidden=true;lastKey='';return;}const b=target.getBoundingClientRect(),s=sidebar.getBoundingClientRect();if(!b.width||!b.height){capsule.hidden=true;lastKey='';return;}
  const x=b.left-s.left+sidebar.scrollLeft,y=b.top-s.top+sidebar.scrollTop,key=[target.getAttribute('href'),x,y,b.width,b.height].join(':');if(key===lastKey)return;
  const previous=capsule.getBoundingClientRect(),had=!!lastKey&&!capsule.hidden;animation?.cancel();capsule.hidden=false;capsule.style.width=b.width+'px';capsule.style.height=b.height+'px';const end=`translate(${x}px,${y}px)`;capsule.style.transform=end;
  if(had&&!reduced.matches){const px=previous.left-s.left+sidebar.scrollLeft,py=previous.top-s.top+sidebar.scrollTop,dx=x-px,dy=y-py,vertical=Math.abs(dy)>=Math.abs(dx),stretch=1+Math.min(.28,Math.hypot(dx,dy)/500);animation=capsule.animate([
   {transform:`translate(${px}px,${py}px) scale(${previous.width/b.width},${previous.height/b.height})`,offset:0},
   {transform:`translate(${px+dx*.6}px,${py+dy*.6}px) scale(${vertical?.97:stretch},${vertical?stretch:.97})`,offset:.46},
   {transform:`translate(${x}px,${y}px) scale(${vertical?1.02:.97},${vertical?.97:1.02})`,offset:.8},
   {transform:end,offset:1}],{duration:460,easing:'cubic-bezier(.22,.7,.2,1)'});}
  lastKey=key;
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(update);}
 new MutationObserver(schedule).observe(doc.getElementById('root'),{childList:true,subtree:true,attributes:true,attributeFilter:['class','aria-current']});
 doc.addEventListener('scroll',schedule,true);window.addEventListener('resize',schedule);window.addEventListener('popstate',schedule);window.addEventListener('hashchange',schedule);reduced.addEventListener('change',()=>{animation?.cancel();schedule();});schedule();return {schedule};
})();
