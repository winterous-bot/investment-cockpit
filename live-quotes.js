/* Northstar: on-demand watchlist quote polling. No credentials or portfolio amounts transmitted. */
(function () {
'use strict';
const FIELDS = 'f12,f13,f14,f2,f3,f4,f5,f6,f18,f124';
function secid(code) {
 if (!/^\d{6}$/.test(code)) throw new Error('股票代码格式不正确');
 if (/^[569]/.test(code)) return '1.' + code;
 if (/^[03]/.test(code)) return '0.' + code;
 throw new Error('暂不支持该股票交易所代码：' + code);
}
function normalize(payload, requested) {
 const diff = payload?.data?.diff;
 const rows = Array.isArray(diff) ? diff : (diff && typeof diff === 'object' ? Object.values(diff) : []);
 const wanted = new Set(requested);
 const quotes = {};
 for (const row of rows) {
  const symbol = String(row?.f12 || '');
  const price = Number(row?.f2);
  if (!wanted.has(symbol) || !Number.isFinite(price) || price <= 0) continue;
  const num = x => x === null || x === '-' || x === '' ? null : (Number.isFinite(Number(x)) ? Number(x) : null);
  const ts = Number(row?.f124);
  quotes[symbol] = {
   price, change: num(row.f3), change_yuan: num(row.f4),
   name: String(row.f14 || symbol).slice(0, 50),
   volume_hands: num(row.f5), turnover_yuan: num(row.f6),
   trade_at: Number.isInteger(ts) && ts > 1577836800 && ts < 2082758400 ? new Date(ts * 1000).toISOString() : null
  };
 }
 return quotes;
}
async function fetchJSON(url, timeoutMs = 10000) {
 const ctrl = new AbortController();
 const timer = setTimeout(() => ctrl.abort(), timeoutMs);
 try {
  const response = await fetch(url, {cache:'no-store', credentials:'omit', signal:ctrl.signal});
  if (!response.ok) throw new Error('行情服务返回 HTTP ' + response.status);
  return await response.json();
 } finally { clearTimeout(timer); }
}
function directUrl(codes) {
 const url = new URL('https://push2.eastmoney.com/api/qt/ulist.np/get');
 url.searchParams.set('fltt','2'); url.searchParams.set('invt','2');
 url.searchParams.set('fields',FIELDS);
 url.searchParams.set('secids',codes.map(secid).join(','));
 url.searchParams.set('_',String(Date.now()));
 return url.toString();
}
async function fetchBatch(symbols, proxyAddress = '') {
 const codes = [...new Set(symbols.filter(s => /^\d{6}$/.test(s)))];
 if (codes.length === 0) throw new Error('观察池和持仓中没有六位A股代码');
 const unsupported = codes.filter(code => !/^[03569]/.test(code));
 if (unsupported.length) throw new Error('尚不支持行情代码：' + unsupported.join('、'));
 if (codes.length > 100) throw new Error('一次最多查询100只股票');
 const chunks = [];
 for (let i=0; i<codes.length; i+=50) chunks.push(codes.slice(i,i+50));
 const quotes = {}; let provider = '';
 for (const part of chunks) {
  let received = null;
  if (proxyAddress) {
   const base = new URL(proxyAddress);
   if (base.protocol !== 'https:') throw new Error('行情代理地址必须以https://开头');
   const url = new URL('./quotes',base.href.endsWith('/') ? base.href : base.href+'/');
   url.searchParams.set('symbols',part.join(',')); url.searchParams.set('_',String(Date.now()));
   const response = await fetchJSON(url.toString(),12000);
   if (!response?.quotes || typeof response.quotes !== 'object') throw new Error('代理返回格式错误');
   const subset = {};
   for (const code of part) {
    const q = response.quotes[code];
    if (q && Number.isFinite(Number(q.price)) && Number(q.price) > 0) subset[code] = q;
   }
   received = subset; provider = '行情代理按需采集';
  } else {
   try {
    received = normalize(await fetchJSON(directUrl(part),8000),part);
    provider = '东方财富网页行情·浏览器直连';
   } catch (error) {
    throw new Error('浏览器直连行情源失败（可能被跨域策略或网络限制）；请在设置中配置HTTPS行情代理后重试。');
   }
  }
  Object.assign(quotes,received);
 }
 if (Object.keys(quotes).length===0) throw new Error('行情接口没有返回任何有效的股票价格');
 return {quotes, count:Object.keys(quotes).length, requested:codes.length, source:provider, updated_at:new Date().toISOString()};
}
window.NorthstarLiveQuotes = {fetchBatch};
})();
