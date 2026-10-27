import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../scripts/native_ui_tree.jxa',import.meta.url),'utf8');
function scenario({front=false,focusAfter=0,activateWorks=true,changeDraft=false,diagnostic=false,wrongGroup=false,lateValue=false}={}){
 let keys=0,activations=0,raises=0,reads=0,draft=lateValue?'':'payload',group=wrongGroup?'wrong':'target';
 const node=(role,getValue)=>({role:()=>role,name:()=>null,description:()=>null,value:getValue,
  attributes:{byName:()=>({value:()=>reads++>=focusAfter})}});
 const composer=node(lateValue?'AXTextField':'AXTextArea',()=>draft),title=node('AXTextField',()=>group),window=node('AXWindow',()=> '');
 window.uiElements=[composer,title];window.actions={byName:()=>({perform:()=>{raises++;}})};
 const proc={exists:()=>true,bundleIdentifier:()=> 'com.tencent.WeWorkMac',windows:{byName:()=>window}};
 Object.defineProperty(proc,'frontmost',{get:()=>()=>front,set:v=>{if(activateWorks)front=v;}});
 const se={processes:{byName:()=>proc},keyCode:()=>{keys++;}};
 const ctx=vm.createContext({Application:name=>name==='System Events'?se:{activate:()=>{activations++;if(activateWorks)front=true;}},delay:()=>{if(changeDraft)draft='user draft';if(lateValue)draft='payload';}});
 vm.runInContext(source,ctx);
 const a={type:'key',key:'return',path:[0],expected:{role:'AXTextArea',value:'payload'},guards:[{path:[1],expected:{role:'AXTextField',value:'target'}}]};
 if(lateValue){a.expected.role='AXTextField';a.waitForValue=true;delete a.guards;}
 let error;try{ctx.run([JSON.stringify({actions:diagnostic?[]:[a],maxDepth:0})]);}catch(e){error=e;}
 return {keys,activations,raises,error};
}
let r=scenario({focusAfter:20});assert.equal(r.keys,1);assert.equal(r.activations,1);assert.equal(r.error,undefined);
assert.equal(r.raises,0);
r=scenario({activateWorks:false});assert.equal(r.keys,0);assert.match(String(r.error),/not-frontmost/);
r=scenario({front:true,focusAfter:999});assert.equal(r.keys,0);assert.match(String(r.error),/focus-mismatch/);
r=scenario({front:true,focusAfter:20,changeDraft:true});assert.equal(r.keys,0);assert.match(String(r.error),/target-changed:value/);
r=scenario({wrongGroup:true});assert.equal(r.keys,0);assert.equal(r.activations,0);
r=scenario({diagnostic:true});assert.equal(r.keys,0);assert.equal(r.activations,0);
r=scenario({front:true,lateValue:true});assert.equal(r.keys,1);assert.equal(r.activations,0);assert.equal(r.error,undefined);
console.log(JSON.stringify({ok:true,scenarios:7,realUIActions:0}));
