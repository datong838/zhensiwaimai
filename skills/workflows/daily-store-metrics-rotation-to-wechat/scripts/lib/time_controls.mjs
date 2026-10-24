export function uniqueGoodsGroup(groups){
 const expected=['今日实时','昨日','近7日','近30日','自定义'];
 const matches=groups.filter(g=>g.visible&&g.labels.length===expected.length&&expected.every((v,i)=>g.labels[i]===v));
 if(matches.length!==1)throw Error('goods-time-group-not-unique');
 return matches[0].index;
}
