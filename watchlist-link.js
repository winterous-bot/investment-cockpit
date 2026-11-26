'use strict';
(function(root){
 function addButton(x,make){if(!x||typeof x.code!=='string'||!/^\d{6}\.(SH|SZ)$/.test(x.code))return null;const b=make('button','加入观察池','radar-chip company-link');b.type='button';b.onclick=()=>{try{sessionStorage.setItem('northstar-watchlist-handoff-v11',JSON.stringify({code:x.code,name:String(x.name||x.code),industry:String(x.industry||'')}));location.href='./company.html'}catch(_){b.textContent='本机无法保存，请在观察池手动添加'}};return b}
 root.NorthstarWatchlistLink={addButton};
})(window);