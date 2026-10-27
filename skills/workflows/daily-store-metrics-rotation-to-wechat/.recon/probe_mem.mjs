import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

// 1) 切换器是否在 main frame
console.log('FRAME_HAS_INPUT=' + await s.mainEval(`(()=>!![...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID'))()`));

// 2) 弹层第二列当前渲染了多少店铺
const domInfo = await s.mainEval(`(()=>{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({err:'closed'});
  const menus=[...dd.querySelectorAll('.cook-cascader-menu')];
  return JSON.stringify({menus:menus.length, items:menus.map(m=>m.querySelectorAll('.cook-cascader-menu-item').length)});
})()`);
console.log('DOM=' + domInfo);

// 3) 挖 Vue 组件树里的门店数据
const vue = await s.mainEval(`(()=>{
  const out={found:false, hints:[]};
  const root=document.querySelector('#app')||document.body;
  const inst=root.__vue__ || (root.__vue_app__ && root.__vue_app__._instance);
  if(!inst){ out.hints.push('no-inst'); }
  // 递归找含大数组的 data
  const seen=new Set();
  const walk=(vm,depth)=>{
    if(!vm||depth>25||seen.has(vm)) return;
    seen.add(vm);
    try{
      for(const k of Object.keys(vm.$data||{})){
        const v=vm.$data[k];
        if(Array.isArray(v)&&v.length>50){
          const f=v[0];
          out.hints.push({where:'data',key:k,len:v.length,sample:JSON.stringify(f).slice(0,300)});
        }
      }
    }catch(e){}
    (vm.$children||[]).slice(0,20).forEach(c=>walk(c,depth+1));
  };
  if(inst) { out.found=true; walk(inst,0); }
  return JSON.stringify(out);
})()`);
console.log('VUE=' + vue);

// 4) 页面里是否有大 JSON 缓存（localStorage/sessionStorage）
const store = await s.mainEval(`(()=>{
  const out=[];
  for(const st of [localStorage, sessionStorage]){
    for(let i=0;i<st.length;i++){
      const k=st.key(i); const v=st.getItem(k)||'';
      if(v.length>5000) out.push({store:st===localStorage?'local':'session',k,len:v.length,head:v.slice(0,120)});
    }
  }
  return JSON.stringify(out.sort((a,b)=>b.len-a.len).slice(0,10));
})()`);
console.log('STORAGE=' + store);

s.cdp.close(); process.exit(0);
