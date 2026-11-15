/* Cloudflare Workers Module - public stock-symbol quote proxy only.
 * Do not add brokerage credentials or portfolio values to requests.
 * Allowed web origin is the owner's GitHub Pages hostname.
 */
const ALLOWED_ORIGIN = 'https://winterous-bot.github.io';
const FIELDS = 'f12,f13,f14,f2,f3,f4,f5,f6,f18,f124';
function json(data, status=200, origin=ALLOWED_ORIGIN) {
 return new Response(JSON.stringify(data), {
  status,
  headers:{'content-type':'application/json; charset=utf-8','access-control-allow-origin':origin,
           'vary':'Origin','cache-control':'no-store','x-content-type-options':'nosniff'}
 });
}
function secid(code) {
 if (/^[569]\d{5}$/.test(code)) return '1.'+code;
 if (/^[03]\d{5}$/.test(code)) return '0.'+code;
 return null;
}
function sanitize(payload,wanted) {
 const diff=payload?.data?.diff;
 const rows=Array.isArray(diff)?diff:(diff&&typeof diff==='object'?Object.values(diff):[]);
 const result={};
 for(const r of rows){
  const code=String(r?.f12||'');
  const price=Number(r?.f2);
  if(!wanted.has(code)||!Number.isFinite(price)||price<=0)continue;
  const num=v=>(v===null||v==='-'||v==='')?null:(Number.isFinite(Number(v))?Number(v):null);
  const ts=Number(r?.f124);
  result[code]={price,change:num(r.f3),change_yuan:num(r.f4),name:String(r.f14||code).slice(0,50),
   volume_hands:num(r.f5),turnover_yuan:num(r.f6),
   trade_at:Number.isInteger(ts)&&ts>1577836800&&ts<2082758400?new Date(ts*1000).toISOString():null};
 }
 return result;
}
async function getUpstream(codes, hostname) {
 const params=new URLSearchParams({fltt:'2',invt:'2',secids:codes.map(secid).join(','),fields:FIELDS,_:String(Date.now())});
 const url='https://'+hostname+'/api/qt/ulist.np/get?'+params.toString();
 const response=await fetch(url,{headers:{'Accept':'application/json','Referer':'https://quote.eastmoney.com/'},redirect:'follow',signal:AbortSignal.timeout(10000)});
 if(!response.ok)throw new Error('HTTP '+response.status);
 const body=await response.json();
 const result=sanitize(body,new Set(codes));
 if(!Object.keys(result).length)throw new Error('报价为空');
 return result;
}
export default {
 async fetch(request) {
  const origin=request.headers.get('Origin');
  if(origin && origin!==ALLOWED_ORIGIN)return json({error:'Origin forbidden'},403);
  if(request.method==='OPTIONS')return new Response(null,{status:204,headers:{'access-control-allow-origin':ALLOWED_ORIGIN,'access-control-allow-methods':'GET, OPTIONS','access-control-allow-headers':'content-type','vary':'Origin'}});
  if(request.method!=='GET')return json({error:'Method not allowed'},405);
  const url=new URL(request.url);
  if(url.pathname!=='/quotes')return json({error:'Use GET /quotes?symbols=600487,002475'},404);
  const input=(url.searchParams.get('symbols')||'').split(',').filter(Boolean);
  const codes=[...new Set(input)];
  if(!codes.length||codes.length>100||codes.some(code=>!secid(code)))return json({error:'Invalid symbols (1–100 supported mainland A-share codes)'},400);
  try {
   let quotes;
   try{quotes=await getUpstream(codes,'push2.eastmoney.com');}
   catch(_){quotes=await getUpstream(codes,'push2delay.eastmoney.com');}
   return json({source:'东方财富网页行情·按需代理',updated_at:new Date().toISOString(),
    count:Object.keys(quotes).length,requested:codes.length,quotes});
  }catch(_){return json({error:'行情上游暂不可用；请稍后重试或使用GitHub收盘快照'},502);}
 }
};
