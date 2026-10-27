// Execute the actual JXA source against a fake UI tree; no native UI or network.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../scripts/native_ui_tree.jxa',import.meta.url),'utf8');
function scenario({group='target',draft='payload',keyFailure=false}={}) {
 let keys=0;
 function node(role,value){return {role:()=>role,value:()=>value,name:()=>null,description:()=>null,
  attributes:{byName:()=>({value:()=>true})}};}
 const composer=node('AXTextArea',draft),title=node('AXTextField',group),window=node('AXWindow','');
 window.uiElements=[composer,title];
 const process={exists:()=>true,bundleIdentifier:()=> 'com.tencent.WeWorkMac',
  windows:{byName:()=>window},frontmost:()=>true};
 const se={processes:{byName:()=>process},keyCode:()=>{keys++;if(keyFailure)throw Error('key-outcome-unknown');}};
 const context=vm.createContext({Application:()=>se});vm.runInContext(source,context);
 const action={type:'key',key:'return',path:[0],expected:{role:'AXTextArea',value:'payload'},
  guards:[{path:[1],expected:{role:'AXTextField',value:'target'}}]};
 let result,error;
 try{result=JSON.parse(context.run([JSON.stringify({actions:[action],maxDepth:0})]));}
 catch(e){error=e;}
 return {result,error,keys};
}
for(const changes of [{group:'wrong'},{draft:'user typing'}]){
 const {result,error,keys}=scenario(changes);
 assert.equal(error,undefined);assert.equal(keys,0);
 assert.equal(result.actionRejected,true);assert.deepEqual(result.results,[]);
}
const correct=scenario();assert.equal(correct.error,undefined);assert.equal(correct.keys,1);
assert.equal(correct.result.results[0].ok,true);
const unknown=scenario({keyFailure:true});assert.equal(unknown.keys,1);assert.ok(unknown.error);
assert.equal(unknown.result,undefined);
console.log(JSON.stringify({ok:true,scenarios:4,realUIActions:0}));
