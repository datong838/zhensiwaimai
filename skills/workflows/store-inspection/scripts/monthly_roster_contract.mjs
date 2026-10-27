const columns={name:'店铺名字',city:'所在城市',status:'店铺状态',member:'是否会员',authorization:'授权状态'};
export function matchesFilterLabel(value,label){
 const text=String(value??'').split('').filter(c=>c.trim()!=='').join('');
 return text===label||new RegExp('^'+label+'[0-9]+家$').test(text);
}
export function headerIndices(headers){
 const result={};
 for(const [key,label] of Object.entries(columns)){
  const hits=headers.flatMap((h,i)=>String(h).trim()===label?[i]:[]);
  if(hits.length!==1)throw Error('roster-header-not-unique:'+label);
  result[key]=hits[0];
 }
 return result;
}
export function parseRosterRows(platform,rows,{allowMissingCity=false}={}){
 if(!['美团外卖','淘宝闪购'].includes(platform))throw Error('roster-platform-invalid');
 return rows.map(r=>{
  const text=k=>typeof r[k]==='string'?r[k].trim():'';
  if(text('status')!=='营业中'||text('member')!=='是'||text('authorization')!=='授权中')throw Error('roster-row-filter-mismatch');
  const name=text('name'),city=text('city');
  if(!name||(!city&&!allowMissingCity))throw Error('roster-identity-missing:'+JSON.stringify({platform,name,city}));
  return {platform,name,city};
 });
}
export function validateRoster(records,proof){
 if(records.some(r=>!r.name||!r.city))throw Error('roster-identity-missing');
 const seen=new Set();
 for(const r of records){const key=JSON.stringify([r.platform,r.name,r.city]);if(seen.has(key))throw Error('roster-duplicate-needs-disambiguation');seen.add(key);}
 return validateObservedCounts(records,proof);
}
export function validateObservedCounts(records,proof){
 for(const platform of ['美团外卖','淘宝闪购']){
  const p=proof[platform];
  if(!p||p.paginationComplete!==true||JSON.stringify(p.filters)!==JSON.stringify(['是会员','营业中','授权中'])||p.total!==records.filter(r=>r.platform===platform).length)throw Error('roster-platform-total-unproved');
 }
 return true;
}
