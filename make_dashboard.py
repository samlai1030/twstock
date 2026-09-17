#!/usr/bin/env python3
"""Bake result.json into a single self-contained dashboard HTML (no CDN, no backend)."""
import json, argparse, html, datetime as dt

TPL = r"""<!DOCTYPE html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>台股自動投資策略 · 回測儀表板</title>
<style>
:root{
  --bg:#f7f8fa; --surface:#ffffff; --line:#e3e6ea; --ink:#14161a; --ink2:#4a5159; --ink3:#767f89;
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300;
  --good:#1baf7a; --bad:#e34948; --warn:#d98c0a;
  --shadow:0 1px 2px rgba(0,0,0,.05),0 2px 8px rgba(0,0,0,.04);
}
body.dark{
  --bg:#12151a; --surface:#1a1f27; --line:#2b323c; --ink:#e9edf2; --ink2:#aab4c0; --ink3:#7d8894;
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300;
  --good:#2ec08c; --bad:#f2635f; --warn:#e8a020;
  --shadow:0 1px 2px rgba(0,0,0,.3);
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans TC","PingFang TC","Microsoft JhengHei",sans-serif}
.wrap{max-width:1240px;margin:0 auto;padding:24px 20px 80px}
header{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:6px}
h1{font-size:21px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--ink2);font-size:13px}
.btn{background:var(--surface);border:1px solid var(--line);color:var(--ink2);border-radius:8px;
 padding:7px 12px;font-size:13px;cursor:pointer}
.btn:hover{color:var(--ink);border-color:var(--ink3)}
.card{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:18px;
 box-shadow:var(--shadow);margin-top:18px}
.card h2{font-size:15px;margin:0 0 3px;letter-spacing:-.01em}
.card .hint{color:var(--ink3);font-size:12.5px;margin:0 0 14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(158px,1fr));gap:12px;margin-top:18px}
.kpi{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:14px 16px;box-shadow:var(--shadow)}
.kpi .k{color:var(--ink3);font-size:11.5px;text-transform:uppercase;letter-spacing:.06em}
.kpi .v{font-size:25px;font-weight:600;letter-spacing:-.02em;margin-top:5px;font-variant-numeric:tabular-nums}
.kpi .d{font-size:12px;color:var(--ink3);margin-top:3px}
.pos{color:var(--good)} .neg{color:var(--bad)} .wn{color:var(--warn)}
table{width:100%;border-collapse:collapse;font-size:13px;font-variant-numeric:tabular-nums}
th{text-align:right;color:var(--ink3);font-weight:500;font-size:11.5px;text-transform:uppercase;
 letter-spacing:.05em;padding:7px 9px;border-bottom:1px solid var(--line);white-space:nowrap;
 position:sticky;top:0;z-index:2;background:var(--surface)}
th:first-child,td:first-child{text-align:left}
th .u{font-weight:400;text-transform:none;letter-spacing:0;color:var(--ink3);font-size:10.5px}
th.l,td.l{text-align:left}
/* td must match th's right alignment or every numeric column's header and its
   values point opposite ways; text columns opt out with .l, as th does. (Sam 2026-09-14) */
td{text-align:right;padding:7px 9px;border-bottom:1px solid var(--line)}
td[colspan]{text-align:left}   /* empty-state rows read as prose, not as a number */
tbody tr:hover{background:rgba(127,127,127,.06)}
.scroll{max-height:430px;overflow:auto}
#orders th,#orders td{text-align:center}   /* 委託單：全欄置中 (Sam 2026-08-31) */
.tag{display:inline-block;padding:1.5px 7px;border-radius:999px;font-size:11px;font-weight:600;border:1px solid}
.t-hold{color:var(--ink2);border-color:var(--line)}
.t-cut{color:var(--bad);border-color:var(--bad)}
.t-trim{color:var(--warn);border-color:var(--warn)}
.t-add{color:var(--good);border-color:var(--good)}
.legend{display:flex;gap:16px;flex-wrap:wrap;align-items:center;font-size:12.5px;color:var(--ink2);margin-bottom:8px}
.sw{width:11px;height:11px;border-radius:3px;display:inline-block;margin-right:6px;vertical-align:-1px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:880px){.grid2{grid-template-columns:1fr}}
svg{display:block;width:100%;overflow:visible}
.tip{position:fixed;pointer-events:none;background:var(--surface);border:1px solid var(--line);
 border-radius:8px;padding:8px 10px;font-size:12.5px;box-shadow:0 4px 14px rgba(0,0,0,.16);
 opacity:0;transition:opacity .1s;z-index:99;white-space:nowrap}
.note{background:rgba(217,140,10,.09);border:1px solid rgba(217,140,10,.35);border-radius:10px;
 padding:13px 15px;font-size:13px;color:var(--ink2);margin-top:18px}
.note b{color:var(--ink)}
ul.tight{margin:8px 0 0;padding-left:19px} ul.tight li{margin:5px 0;color:var(--ink2)}
code{background:rgba(127,127,127,.13);padding:1.5px 5px;border-radius:4px;font-size:12px}
.newsitem{padding:9px 0;border-bottom:1px solid var(--line)}
.newsitem a{color:var(--s1);text-decoration:none;font-weight:500}
.newsitem a:hover{text-decoration:underline}
.newsitem .m{color:var(--ink3);font-size:11.5px;margin-top:2px}
</style></head><body>
<div class="wrap">
<header>
 <div>
  <h1 id="title">台股自動投資策略 — 回測儀表板</h1>
  <div class="sub" id="sub"></div>
 </div>
 <div style="display:flex;gap:8px">
  <button class="btn" onclick="dl()">Export CSV</button>
  <button class="btn" onclick="tog()">◐ 深色</button>
 </div>
</header>

<div class="kpis" id="kpis"></div>

<div class="card" id="paramcard">
 <h2>策略參數 · 已做 v0 最佳化驗證</h2>
 <p class="hint" id="paramhint"></p>
 <div id="params"></div>
 <div class="note" id="paramnote" style="margin-top:14px"></div>
</div>

<div class="card">
 <h2>權益曲線 vs 0050 買進持有</h2>
 <p class="hint">兩者皆以 NT$1,000,000 起始、扣除相同交易成本（手續費＋證交稅＋滑價）。▼ 標記為緊急減碼事件。</p>
 <div class="legend">
   <span><i class="sw" style="background:var(--s1)"></i>策略</span>
   <span><i class="sw" style="background:var(--s2)"></i>0050 買進持有</span>
   <span><i class="sw" style="background:var(--bad)"></i>緊急事件</span>
 </div>
 <div id="eq"></div>
</div>

<div class="grid2">
 <div class="card"><h2>回撤 (Drawdown)</h2>
  <p class="hint">距離歷史高點的跌幅；緊急減碼規則以 −12% 為觸發線。</p><div id="dd"></div></div>
 <div class="card"><h2>每週曝險水位</h2>
  <p class="hint">由 0050 相對 MA60 / MA200 的市場狀態決定：risk-on 100%、caution 70%、risk-off 40%。</p><div id="ex"></div></div>
</div>

<div class="card" id="ordcard"><h2>下一個交易日委託單</h2>
 <p class="hint" id="ordhint"></p><div id="orders"></div></div>

<div class="card" id="alloccard"><h2>資產配置（現金 + 持股）</h2>
 <p class="hint" id="allochint"></p>
 <div id="alloc" style="display:grid;grid-template-columns:240px minmax(0,1fr);align-items:center;gap:28px"></div></div>

<div class="card" id="poscard"><h2>目前持倉</h2>
 <p class="hint" id="poshint"></p><div id="positions"></div></div>

<div class="card" id="chipcard"><h2>集保籌碼分佈 — 僅供參考，未計入選股分數</h2>
 <p class="hint" id="chiphint"></p><div id="chips"></div></div>

<div class="note" id="verdict"></div>

<div class="card"><h2>市場背景 — 為什麼輸給 0050</h2>
 <p class="hint">同期個股報酬分布 vs 大盤。看這張圖再看績效，結論會不一樣。</p>
 <div id="ctx"></div></div>

<div class="card"><h2>歸因分析：每個機制值多少</h2>
 <p class="hint">每次只關掉一個機制，用來「定價」該機制的貢獻。<b>這些是診斷，不是候選策略</b> —
  挑同一年表現最好的那組去當成策略，就是過度配適。</p>
 <div id="diag"></div></div>

<div class="card"><h2>本週操作建議</h2>
 <p class="hint" id="lhint"></p>
 <div id="latest"></div></div>

<div class="card" id="hcard"><h2>持股體檢（籌碼 + 部位）</h2>
 <p class="hint" id="hhint"></p><div id="holdings"></div></div>

<div class="card"><h2>每週操作紀錄</h2>
 <p class="hint">每個決策都在週五收盤後產生、下一個交易日開盤成交 — 不使用當日收盤價下單，避免未來函數。</p>
 <div class="scroll"><table id="wk"></table></div></div>

<div class="card"><h2>緊急操作事件</h2>
 <p class="hint">每日檢查（非僅週檢）：個股停損 −12%、移動停損 −15%、大盤單日 −3.5% 或組合回撤 −12% 全數出清。</p>
 <div class="scroll"><table id="ev"></table></div></div>

<div class="card"><h2>成交明細</h2><p class="hint">最近 300 筆。</p>
 <div class="scroll"><table id="tr"></table></div></div>

<div class="card"><h2>市場新聞 — 資訊面</h2>
 <p class="hint" id="nhint"></p>
 <div class="scroll" id="news"></div></div>

<div class="card"><h2>方法與限制</h2>
 <div class="note" id="caveats"></div>
</div>

</div><div class="tip" id="tip"></div>
<script>
const D = __DATA__;
const $=s=>document.querySelector(s), tip=$('#tip');
const nf=n=>n==null?'—':n.toLocaleString('en-US',{maximumFractionDigits:0});
const pf=(n,d=1)=>n==null?'—':(n*100).toFixed(d)+'%';
const sg=n=>n==null?'':(n>0?'pos':(n<0?'neg':''));
const pr=n=>n==null?'—':n.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const esc=s=>String(s==null?'':s).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

if(D.meta.mode==='paper'){$('#title').textContent='台股自動投資策略 — 模擬帳戶 (Paper Trading)';
 document.title='台股策略 · 模擬帳戶';}
$('#sub').innerHTML = `${D.meta.mode==='paper'?'開始日':'回測區間'} `+` ${D.meta.start} → ${D.meta.end} ｜ 本金 NT$${nf(D.meta.capital)} ｜ 產生於 ${D.meta.generated}`+
 (D.meta.inject_date?`<br><span style="color:var(--ink3)">＊ ${D.meta.inject_date} 注資 NT$${nf(D.meta.inject_amt)}（記為存入，非報酬；報酬以時間加權 TWR 計）</span>`:``)+
 ((D.sleeves&&D.sleeves.length)?`<br>`+D.sleeves.map(s=>`<b>${esc(s.label)}</b> NT$${nf(s.value)} <span class="${sg(s.ret)}">(${pf(s.ret)})</span>`).join(' ｜ '):``);

/* ---------- KPI ---------- */
const M=D.metrics, B=D.bench_metrics||{}, T=D.trade_stats;
const excess = (M.total_return||0)-(B.total_return||0);
const hasM = M && M.total_return!=null;
const kpis= !hasM ? [
 ['帳戶狀態','已開立',`本金 NT$${nf(D.meta.capital)}`,''],
 ['起始日',D.meta.start,'決策日（收盤後）',''],
 ['委託成交日',(D.orders&&D.orders.fill_at)||'—','隔日開盤',''],
 ['委託檔數',String((D.orders&&D.orders.rows||[]).length),`等權重上限 ${(D.meta.params||{}).top_n||'?'} 檔`,''],
] : [
 ['總報酬', pf(M.total_return), `NT$${nf(M.end_eq)} 期末`, sg(M.total_return)],
 ['年化報酬 CAGR', pf(M.cagr), `0050: ${pf(B.cagr)}`, sg(M.cagr)],
 ['超額報酬 vs 0050', pf(excess), '同成本基準', sg(excess)],
 ['最大回撤', pf(M.mdd), `${M.mdd_at||''}｜0050: ${pf(B.mdd)}`, 'neg'],
 ['年化波動', pf(M.vol), `Calmar ${(M.calmar||0).toFixed(2)}`, ''],
 ['勝率', pf(T.win_rate), `${T.win}勝 / ${T.lose}敗（${T.n}筆）`, ''],
 ['獲利因子 PF', (T.profit_factor||0).toFixed(2), `總成本 NT$${nf(D.total_cost)}`, (T.profit_factor>1?'pos':'neg')],
];
$('#kpis').innerHTML = kpis.map(k=>
 `<div class="kpi"><div class="k">${k[0]}</div><div class="v ${k[3]}">${k[1]}</div><div class="d">${k[2]}</div></div>`).join('');

/* ---------- strategy params (read live from engine, not hardcoded) ---------- */
(function(){const P=D.meta.params||{},W=D.meta.weights||{};
 if(!Object.keys(P).length){$('#paramcard').style.display='none';return;}
 const pv=v=>v==null?'—':parseFloat((v*100).toFixed(4))+'%';   // -0.08 -> -8%, 0.001425 -> 0.1425%
 const dy=v=>v==null?'—':v+' 日';
 const wt=w=>w==null?'':'（'+(w>0?'+':'')+w+'）';
 const grp=(t,rows)=>`<div style="min-width:210px;flex:1"><div style="color:var(--ink3);font-size:11px;`+
   `text-transform:uppercase;letter-spacing:.06em;margin-bottom:7px">${t}</div><table style="font-size:12.5px">`+
   rows.map(r=>`<tr><td class="l" style="color:var(--ink2);border:none;padding:3px 0">${r[0]}</td>`+
     `<td class="l" style="border:none;padding:3px 0 3px 16px;font-weight:600;font-variant-numeric:tabular-nums">${r[1]}</td></tr>`).join('')
   +`</table></div>`;
 $('#params').innerHTML=`<div style="display:flex;gap:30px;flex-wrap:wrap">`+
  grp('選股 / 部位',[
    ['部位檔數 top_n',P.top_n],
    ['籌碼配置',P.size_mode==='conviction'?'機會÷風險加權':'等權重'],
    ['單檔權重上下限',P.size_mode==='conviction'?(pv(P.conv_min_weight)+' ~ '+pv(P.conv_max_weight)):'—'],
    ['階梯式進出',P.ladder_enable?('最多 '+P.ladder_max_tranches+' 段 · 滿倉門檻 score '+P.ladder_full_score):'—'],
    ['週K線部位微調',P.kline_tilt?('±'+P.kline_win+'週 · 靈敏度 '+P.kline_tilt):'—'],
    ['月K線部位微調',P.mkline_tilt?('±'+P.mkline_win+'月 · 靈敏度 '+P.mkline_tilt):'—'],
    ['交易單位',P.lot_size>1?(nf(P.lot_size)+' 股（整股）'):'零股（1 股）'],
    ['最低股價',pr(P.min_price)],
    ['最低20日成交值中位數','NT$'+nf(P.min_turnover)],
  ])+
  grp('綜合分數訊號（權重）',[
    ['動能（跳過近 '+P.mom_skip+' 日）',dy(P.lookback_mom)+wt(W.mom)],
    ['外資淨買',dy(P.chip_fgn_win)+wt(W.fgn)],
    ['投信淨買',dy(P.chip_tru_win)+wt(W.tru)],
    ['融資增幅',dy(P.margin_win)+wt(W.margin)],
  ])+
  grp('市場水位（0050 代理）',[
    ['趨勢均線','MA'+P.ma_trend+' / MA'+P.ma_slow],
    ['risk-on / caution / off','100% / 70% / 40%'],
  ])+
  grp('風控 / 緊急',[
    ['個股停損',pv(P.stop_loss)],
    ['移動停損',pv(P.trail_stop)],
    ['停損冷卻',dy(P.stop_cooldown)],
    ['大盤單日崩',pv(P.crash_day)],
    ['組合回撤出清',pv(P.crash_dd)],
    ['緊急冷卻',dy(P.emg_cooldown)],
  ])+
  grp('成本假設（單邊）',[
    ['手續費',pv(P.fee_rate)+(P.fee_discount&&P.fee_discount!=1?' ×'+P.fee_discount:'（未打折）')],
    ['證交稅（賣）',pv(P.tax_rate)+' ｜ ETF '+pv(P.tax_rate_etf)],
    ['滑價',pv(P.slippage)],
    ['最低手續費','NT$'+nf(P.min_fee)],
  ])+
 `</div>`;
 $('#paramhint').textContent='以下數值直接讀自目前引擎設定，會隨程式碼更新自動同步 — 不是寫死在儀表板上。';
 $('#paramnote').innerHTML='<b>參數已做 v0 最佳化驗證，刻意保留手設值。</b>'+
  ' 以 MA200 暖身後約 14 個月資料切樣本內（2025-06～2026-01，搜尋）／樣本外（2026-02～2026-08，驗證），隨機搜尋 250 組。'+
  '樣本內最佳者（夏普 5.96／+111%）在樣本外崩壞（夏普 −0.88／−17.5%）；手設參數樣本外夏普 4.39／+67.8%，勝過全部最佳化候選。'+
  '結論：這段資料上最佳化＝過度配適，故保留手設參數 — 不是「還沒最佳化」，是「測過、最佳化沒用」。'+
  '<br><b>週／月K線部位微調</b>：每檔選股再讀近 '+(P.kline_win||8)+' 週與近 '+(P.mkline_win||6)+' 月的K線型態'+
  '（收盤在區間位置、實體/影線、連續性），<b>只調整持有比例、不改變選股</b> — 週線是短線層、月線是較慢的趨勢確認層，'+
  '兩者相乘疊加後仍受單檔上下限約束；型態強者加碼、被上影線壓回者減碼。價格是精準的「當時可得」資料，'+
  '故此微調可誠實回測（與新聞不同）；靈敏度（週 '+(P.kline_tilt||0)+'／月 '+(P.mkline_tilt||0)+'）為手設、未對樣本最佳化。'+
  '<br><b>階梯式進出</b>：信心（綜合分數）越低的選股，越分批建倉 — 分數 ≥ '+(P.ladder_full_score||1.5)+' 一次到滿倉，'+
  '越低則拆成最多 '+(P.ladder_max_tranches||3)+' 段、每週加一段；跌出名單時同樣<b>分批減碼</b>而非一次出清。'+
  '這是「信心不足就先試單、確認再加碼」的操作。<b>但停損／移動停損／緊急出清不受階梯影響 — 風控一律全數立即執行</b>。'+
  '此模式只用當下分數與過往部位狀態，仍為「當時可得」、可誠實回測。'+
  '<br>資訊面（新聞情緒）<b>未進入決策分數</b> — 歷史新聞無法精確對齊「當時可得」時點，硬做情緒分數會造成未來函數並灌水績效；'+
  '故僅作為選股後的<b>人工複核資訊面板</b>，不影響選股、不影響部位權重。';
})();

/* ---------- chart helpers ---------- */
function ax(el,W,H,pad){const s=document.createElementNS('http://www.w3.org/2000/svg','svg');
 s.setAttribute('viewBox',`0 0 ${W} ${H}`);s.setAttribute('height',H);el.appendChild(s);return s;}
function mk(t,a){const e=document.createElementNS('http://www.w3.org/2000/svg',t);
 for(const k in a)e.setAttribute(k,a[k]);return e;}
function showTip(ev,htmlStr){tip.innerHTML=htmlStr;tip.style.opacity=1;
 tip.style.left=Math.min(window.innerWidth-tip.offsetWidth-12,ev.clientX+14)+'px';
 tip.style.top=(ev.clientY-10)+'px';}
function hideTip(){tip.style.opacity=0;}
/* candlestick mini-chart for the picks table -- reused for weekly and monthly candles */
function kchart(cs){if(!cs||cs.length<2)return '<span style="color:var(--ink3)">—</span>';
 const W=76,H=30,pad=2,n=cs.length,bw=Math.max(2,(W-pad*2)/n-1.5);
 let lo=Math.min(...cs.map(k=>k.l)),hi=Math.max(...cs.map(k=>k.h));const sp=(hi-lo)||1;
 const Y=v=>pad+(hi-v)*(H-pad*2)/sp, X=i=>pad+i*(W-pad*2)/n+bw/2;
 let s=`<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" style="vertical-align:middle">`;
 cs.forEach((k,i)=>{const up=k.c>=k.o,col=up?'var(--good)':'var(--bad)';const x=X(i);
  const yb=Y(Math.max(k.o,k.c)),yt=Y(Math.min(k.o,k.c));
  s+=`<line x1="${x}" x2="${x}" y1="${Y(k.h)}" y2="${Y(k.l)}" stroke="${col}" stroke-width="1"/>`;
  s+=`<rect x="${x-bw/2}" y="${yb}" width="${bw}" height="${Math.max(1,yt-yb)}" fill="${col}"/>`;});
 return s+'</svg>';}

/* ---------- equity curve ---------- */
(function(){
 const eq=D.equity, bm=D.bench, W=1200,H=340,P={l:64,r:16,t:14,b:26};
 const el=$('#eq'); el.innerHTML='';
 if(eq.length<2){el.innerHTML='<p class="hint">帳戶剛開立，尚無淨值走勢 — 第一筆成交後開始累積。</p>';return;}
 const s=ax(el,W,H);
 const all=eq.map(d=>d.equity).concat(bm.map(d=>d.equity));
 let lo=Math.min(...all), hi=Math.max(...all); const sp=(hi-lo)||1; lo-=sp*.08; hi+=sp*.08;
 const X=i=>P.l+i*(W-P.l-P.r)/Math.max(1,eq.length-1);
 const Y=v=>P.t+(hi-v)*(H-P.t-P.b)/(hi-lo);
 for(let g=0;g<=4;g++){const v=lo+(hi-lo)*g/4;
  s.appendChild(mk('line',{x1:P.l,x2:W-P.r,y1:Y(v),y2:Y(v),stroke:'var(--line)','stroke-width':1}));
  const t=mk('text',{x:P.l-9,y:Y(v)+4,'text-anchor':'end',fill:'var(--ink3)','font-size':11});
  t.textContent=(v/1e6).toFixed(2)+'M'; s.appendChild(t);}
 // cost-basis (break-even) line. With a mid-stream contribution the invested base
 // steps up on the deposit date, so draw a step, not one flat line, and mark 注資.
 const injI = D.meta.inject_date ? eq.findIndex(d=>d.date>=D.meta.inject_date) : -1;
 const preBase = D.meta.capital - (D.meta.inject_amt||0);
 const baseAt = i => (injI>0 && i<injI) ? preBase : D.meta.capital;
 if(injI>0){
  s.appendChild(mk('line',{x1:X(0),x2:X(injI),y1:Y(preBase),y2:Y(preBase),stroke:'var(--ink3)','stroke-width':1,'stroke-dasharray':'4 4',opacity:.55}));
  s.appendChild(mk('line',{x1:X(injI),x2:X(eq.length-1),y1:Y(D.meta.capital),y2:Y(D.meta.capital),stroke:'var(--ink3)','stroke-width':1,'stroke-dasharray':'4 4',opacity:.55}));
  s.appendChild(mk('line',{x1:X(injI),x2:X(injI),y1:P.t,y2:H-P.b,stroke:'var(--ink3)','stroke-width':1,'stroke-dasharray':'3 3',opacity:.5}));
  const lt=mk('text',{x:X(injI)+5,y:P.t+13,fill:'var(--ink3)','font-size':10.5}); lt.textContent='注資 +NT$'+nf(D.meta.inject_amt); s.appendChild(lt);
 } else {
  s.appendChild(mk('line',{x1:P.l,x2:W-P.r,y1:Y(D.meta.capital),y2:Y(D.meta.capital),
    stroke:'var(--ink3)','stroke-width':1,'stroke-dasharray':'4 4',opacity:.55}));
 }
 const path=a=>a.map((d,i)=>(i?'L':'M')+X(i)+' '+Y(d.equity)).join(' ');
 if(bm.length) s.appendChild(mk('path',{d:path(bm),fill:'none',stroke:'var(--s2)','stroke-width':2,
   'stroke-linejoin':'round'}));
 s.appendChild(mk('path',{d:path(eq),fill:'none',stroke:'var(--s1)','stroke-width':2,'stroke-linejoin':'round'}));
 const idx={}; eq.forEach((d,i)=>idx[d.date]=i);
 (D.events||[]).forEach(e=>{const i=idx[e.date]; if(i==null)return;
  const m=mk('path',{d:`M${X(i)-5} ${Y(eq[i].equity)-13} L${X(i)+5} ${Y(eq[i].equity)-13} L${X(i)} ${Y(eq[i].equity)-4} Z`,
    fill:'var(--bad)',opacity:.9,style:'cursor:pointer'});
  m.addEventListener('mousemove',ev=>showTip(ev,`<b>${e.date}</b> · ${e.kind}<br>${esc(e.detail)}`));
  m.addEventListener('mouseleave',hideTip); s.appendChild(m);});
 const n=Math.min(7,eq.length);
 for(let k=0;k<n;k++){const i=Math.round(k*(eq.length-1)/(n-1));
  const t=mk('text',{x:X(i),y:H-6,'text-anchor':'middle',fill:'var(--ink3)','font-size':11});
  t.textContent=eq[i].date.slice(2,7); s.appendChild(t);}
 const hit=mk('rect',{x:P.l,y:P.t,width:W-P.l-P.r,height:H-P.t-P.b,fill:'transparent',style:'cursor:crosshair'});
 const cross=mk('line',{y1:P.t,y2:H-P.b,stroke:'var(--ink3)','stroke-width':1,opacity:0});
 s.appendChild(cross); s.appendChild(hit);
 hit.addEventListener('mousemove',ev=>{const r=s.getBoundingClientRect();
  const px=(ev.clientX-r.left)*W/r.width; let i=Math.round((px-P.l)*(eq.length-1)/(W-P.l-P.r));
  i=Math.max(0,Math.min(eq.length-1,i));
  cross.setAttribute('x1',X(i));cross.setAttribute('x2',X(i));cross.setAttribute('opacity',.45);
  const b=bm[i]?bm[i].equity:null; const bs=baseAt(i);
  showTip(ev,`<b>${eq[i].date}</b><br>策略 NT$${nf(eq[i].equity)} (${pf(eq[i].equity/bs-1)})`
   +(b?`<br>0050 NT$${nf(b)} (${pf(b/bs-1)})`:'')
   +`<br><span style="color:var(--ink3)">持股 ${eq[i].npos} 檔 ｜ 現金 NT$${nf(eq[i].cash)}</span>`);});
 hit.addEventListener('mouseleave',()=>{hideTip();cross.setAttribute('opacity',0);});
})();

/* ---------- drawdown ---------- */
(function(){const eq=D.equity,W=580,H=200,P={l:52,r:12,t:12,b:24};
 const el=$('#dd');el.innerHTML='';
 if(eq.length<2){el.innerHTML='<p class="hint">尚無資料</p>';return;}
 const s=ax(el,W,H);
 const lo=Math.min(-0.02,...eq.map(d=>d.dd));
 const X=i=>P.l+i*(W-P.l-P.r)/Math.max(1,eq.length-1), Y=v=>P.t+(0-v)*(H-P.t-P.b)/(0-lo);
 for(let g=0;g<=3;g++){const v=lo*g/3;
  s.appendChild(mk('line',{x1:P.l,x2:W-P.r,y1:Y(v),y2:Y(v),stroke:'var(--line)'}));
  const t=mk('text',{x:P.l-8,y:Y(v)+4,'text-anchor':'end',fill:'var(--ink3)','font-size':10.5});
  t.textContent=(v*100).toFixed(Math.abs(lo)<0.05?1:0)+'%';s.appendChild(t);}
 s.appendChild(mk('path',{d:eq.map((d,i)=>(i?'L':'M')+X(i)+' '+Y(d.dd)).join(' ')+
   `L${X(eq.length-1)} ${Y(0)} L${X(0)} ${Y(0)} Z`,fill:'var(--bad)','fill-opacity':.16,
   stroke:'var(--bad)','stroke-width':1.5}));
 // -12% trailing-stop marker: only draw when drawdown actually reaches into range,
 // else (svg overflow:visible) it renders far below the chart as a stray line.
 if(lo<=-0.12){
  s.appendChild(mk('line',{x1:P.l,x2:W-P.r,y1:Y(-0.12),y2:Y(-0.12),stroke:'var(--warn)',
    'stroke-width':1,'stroke-dasharray':'5 4'}));}
})();

/* ---------- exposure ---------- */
(function(){const wk=D.weekly,W=580,H=200,P={l:52,r:12,t:12,b:24};
 const el=$('#ex');el.innerHTML='';const s=ax(el,W,H);
 if(!wk.length){el.innerHTML='<p class="hint">無資料</p>';return;}
 const bw=Math.max(1.5,(W-P.l-P.r)/wk.length-1.5);
 for(let g=0;g<=4;g++){const v=g/4;
  s.appendChild(mk('line',{x1:P.l,x2:W-P.r,y1:P.t+(1-v)*(H-P.t-P.b),y2:P.t+(1-v)*(H-P.t-P.b),stroke:'var(--line)'}));
  const t=mk('text',{x:P.l-8,y:P.t+(1-v)*(H-P.t-P.b)+4,'text-anchor':'end',fill:'var(--ink3)','font-size':10.5});
  t.textContent=(v*100).toFixed(0)+'%';s.appendChild(t);}
 wk.forEach((w,i)=>{const x=P.l+i*(W-P.l-P.r)/wk.length, h=(w.exposure)*(H-P.t-P.b);
  const col=w.exposure>=1?'var(--s3)':(w.exposure>=0.7?'var(--s1)':'var(--warn)');
  const r=mk('rect',{x:x,y:H-P.b-h,width:bw,height:Math.max(1,h),fill:col,rx:2,style:'cursor:pointer'});
  r.addEventListener('mousemove',ev=>showTip(ev,`<b>${w.date}</b><br>${esc(w.regime)}<br>曝險 ${pf(w.exposure,0)} ｜ ${w.picks.length} 檔`));
  r.addEventListener('mouseleave',hideTip); s.appendChild(r);});
})();

/* ---------- latest picks ---------- */
(function(){const L=D.latest;const el=$('#latest');
 if(!L){el.innerHTML='<p class="hint">無</p>';return;}
 $('#lhint').textContent=`決策日 ${L.date} ｜ 市場狀態：${L.regime} ｜ 建議曝險 ${pf(L.exposure,0)}`;
 if(!L.picks||!L.picks.length){
   el.innerHTML=`<div class="note" style="margin:0"><b>目前空手 — 不進場。</b><br>`+
    (L.note?esc(L.note):'本週未產生持股名單')+
    `。緊急出清後設有 ${D.meta.params.emg_cooldown} 個交易日的冷卻期，`+
    `且需等市場回到 risk-on 才會重新建立部位。這是規則設計，不是資料缺漏。</div>`;
   return;}
 el.innerHTML=`<table><thead><tr><th>#</th><th class="l">代號</th><th class="l">名稱</th>
  <th>綜合分數</th><th>目標權重<div class="u">機會÷風險×週K×月K</div></th>
  <th>建倉進度<div class="u">階梯式·段</div></th>
  <th class="l">週K線<div class="u">近${(D.meta.params||{}).kline_win||8}週</div></th><th>週K強度<div class="u">部位微調</div></th>
  <th class="l">月K線<div class="u">近${(D.meta.params||{}).mkline_win||6}月</div></th><th>月K強度<div class="u">部位微調</div></th>
  <th>60日動能</th>
  <th>外資20日<div class="u">佔成交值%</div></th>
  <th>投信10日<div class="u">佔成交值%</div></th>
  <th>資訊面<div class="u">人工複核·未計分</div></th><th class="l">動作</th></tr></thead><tbody>`+
  L.picks.map((p,i)=>`<tr><td>${i+1}</td><td class="l"><b>${esc(p.code)}</b></td><td class="l">${esc(p.name)}</td>
   <td class="${sg(p.score)}">${p.score.toFixed(2)}</td><td><b>${p.weight!=null?pf(p.weight,0):'—'}</b>${p.weight_full!=null&&p.weight<p.weight_full-1e-6?'<div class="u">滿倉 '+pf(p.weight_full,0)+'</div>':''}</td>
   <td>${p.stage?(p.weight_full!=null&&p.weight<p.weight_full-1e-6?'<span style="color:var(--warn,#b7791f)">'+esc(p.stage)+'</span> <span class="u">分批</span>':esc(p.stage)+' <span class="u">滿倉</span>'):'—'}</td>
   <td class="l">${kchart(p.kcandles)}</td>
   <td class="${p.kline?sg(p.kline):''}">${p.kline!=null?(p.kline>0?'+':'')+p.kline.toFixed(2):'—'}</td>
   <td class="l">${kchart(p.mcandles)}</td>
   <td class="${p.kline_m?sg(p.kline_m):''}">${p.kline_m!=null?(p.kline_m>0?'+':'')+p.kline_m.toFixed(2):'—'}</td>
   <td class="${sg(p.mom)}">${pf(p.mom)}</td>
   <td class="${sg(p.fgn)}">${(p.fgn*100).toFixed(1)}</td><td class="${sg(p.tru)}">${(p.tru*100).toFixed(1)}</td>
   <td class="${p.news?sg(p.news):''}">${p.news?(p.news>0?'+':'')+p.news.toFixed(1):'·'}</td>
   <td class="l">${L.buy.includes(p.code)?'<span class="tag t-add">新進</span>':'<span class="tag t-hold">續抱</span>'}</td></tr>`).join('')
  +`</tbody></table>`
  +(L.scale_out&&L.scale_out.length?`<p class="hint" style="margin-top:10px">分批減碼（階梯式退場，非風控急殺）：${L.scale_out.map(s=>esc(s.code)+(s.name?' '+esc(s.name):'')+'（'+esc(s.stage)+'）').join('、')}</p>`:'')
  +(L.sell&&L.sell.length?`<p class="hint" style="margin-top:${L.scale_out&&L.scale_out.length?'4':'10'}px">賣出：${L.sell.map(esc).join('、')}</p>`:'');
})();

/* ---------- holdings ---------- */
(function(){const H=D.holdings,el=$('#holdings');
 if(!H||!H.rows||!H.rows.length){
  $('#hcard').style.display='none'; return;}
 $('#hhint').innerHTML=`資料日 ${H.asof} ｜ 部位總市值 NT$${nf(H.total_value)}`+
   (H.is_example?` ｜ <b style="color:var(--warn)">⚠ 這是範例持股，不是 Sam 的真實部位</b>`:'');
 if(!H.is_example){const w=document.createElement('div');w.className='note';w.style.marginTop='0';
   w.innerHTML='<b>⚠ 這份儀表板含真實持股資料。</b>PixelCloud 沒有存取控制 — '+
     '含真實部位的版本請改放 Collab Files（可設權限），不要發佈到 PixelCloud。';
   $('#hcard').insertBefore(w,$('#holdings'));}
 el.innerHTML=`<table><thead><tr><th class="l">代號</th><th class="l">名稱</th><th>股數</th><th>成本</th>
  <th>現價</th><th>市值</th><th>權重</th><th>損益</th><th>分數<div class="u">全市場排名</div></th>
  <th>外資20日<div class="u">淨買股數</div></th><th>投信20日<div class="u">淨買股數</div></th>
  <th class="l">動作</th><th class="l">警訊</th></tr></thead><tbody>`+
  H.rows.map(r=>`<tr><td class="l"><b>${esc(r.code)}</b></td><td class="l">${esc(r.name)}</td>
   <td>${nf(r.shares)}</td><td>${r.cost??'—'}</td><td>${r.last??'—'}</td><td>${nf(r.value)}</td>
   <td>${pf(r.weight,0)}</td><td class="${sg(r.pnl_pct)}">${pf(r.pnl_pct)}</td>
   <td class="${sg(r.score)}">${r.score.toFixed(2)}<div style="color:var(--ink3);font-size:11px">${r.rank?r.rank+' / '+r.n_uni:''}</div></td>
   <td class="${sg(r.fgn20)}">${nf(r.fgn20)}</td><td class="${sg(r.tru20)}">${nf(r.tru20)}</td>
   <td class="l"><span class="tag t-${r.action.toLowerCase().replace('-ok','')}">${r.action}</span></td>
   <td class="l" style="color:var(--ink3);font-size:12px">${r.flags.map(esc).join('；')||'—'}</td></tr>`).join('')+`</tbody></table>`;
})();

/* ---------- weekly log ---------- */
$('#wk').innerHTML=`<thead><tr><th class="l">決策日</th><th class="l">市場狀態</th><th>曝險</th>
 <th class="l">持有</th><th class="l">買進</th><th class="l">賣出</th></tr></thead><tbody>`+
 D.weekly.slice().reverse().map(w=>`<tr><td class="l">${w.date}</td><td class="l">${esc(w.regime)}</td>
  <td>${pf(w.exposure,0)}</td><td class="l" style="font-size:12px">${w.picks.map(p=>esc(p.code)).join(' ')||'—'}</td>
  <td class="l pos" style="font-size:12px">${(w.buy||[]).map(esc).join(' ')||'—'}</td>
  <td class="l neg" style="font-size:12px">${(w.sell||[]).map(esc).join(' ')||'—'}</td></tr>`).join('')+`</tbody>`;

/* ---------- events ---------- */
$('#ev').innerHTML=`<thead><tr><th class="l">日期</th><th class="l">類型</th><th>檔數</th>
 <th>當日權益</th><th class="l">原因</th></tr></thead><tbody>`+
 (D.events.length?D.events.slice().reverse().map(e=>`<tr><td class="l">${e.date}</td>
  <td class="l"><span class="tag ${e.kind==='EMERGENCY_EXIT'?'t-cut':'t-trim'}">${e.kind}</span></td>
  <td>${e.n}</td><td>NT$${nf(e.equity)}</td><td class="l" style="font-size:12px">${esc(e.detail)}</td></tr>`).join('')
  :'<tr><td colspan="5" style="color:var(--ink3)">回測期間未觸發任何緊急事件</td></tr>')+`</tbody>`;

/* ---------- trades ---------- */
$('#tr').innerHTML=`<thead><tr><th class="l">日期</th><th class="l">代號</th><th class="l">買賣</th>
 <th>股數</th><th>價格</th><th>成本</th><th class="l">原因</th></tr></thead><tbody>`+
 D.trades.slice().reverse().map(t=>`<tr><td class="l">${t.date}</td><td class="l"><b>${esc(t.code)}</b></td>
  <td class="l ${t.side==='BUY'?'pos':'neg'}">${t.side}</td><td>${nf(t.sh)}</td><td>${t.price}</td>
  <td>${nf(t.cost)}</td><td class="l" style="font-size:12px;color:var(--ink3)">${esc(t.why)}</td></tr>`).join('')+`</tbody>`;

/* ---------- news ---------- */
(function(){const N=D.news||[];
 $('#nhint').textContent=`${N.length} 則 · 僅供人工判讀，未進入回測訊號（避免未來函數）`;
 $('#news').innerHTML=N.map(n=>`<div class="newsitem"><a href="${esc(n.link)}" target="_blank" rel="noopener">${esc(n.title)}</a>
  <div class="m">${esc(n.src)} · ${esc(n.pub)}</div></div>`).join('')||'<p class="hint">無</p>';})();

/* ---------- order sheet (paper mode) ---------- */
(function(){const O=D.orders;
 if(!O||!O.rows||!O.rows.length){$('#ordcard').style.display='none';return;}
 const szlabel=O.sizing==='conviction'?'機會÷風險加權（非等權重）':'等權重';
 $('#ordhint').innerHTML=`決策日 <b>${O.decided}</b> 收盤 → <b>${O.fill_at}</b> 開盤成交`+
  (O.exposure!=null?` ｜ 曝險 ${pf(O.exposure,0)} ｜ 籌碼配置：<b>${szlabel}</b>`:'')+
  (O.target_max?` ｜ 單檔目標 NT$${nf(O.target_min)}–${nf(O.target_max)}`:'')+`<br>`+
  `<span style="color:var(--warn)">參考價為決策日收盤價，實際成交價為隔日開盤價 — 股數會依開盤價微調。</span>`;
 const SLVO={active:'主動 α',core:'核心 0050'};
 const hasSlvO=O.rows.some(r=>r.sleeve);
 $('#orders').innerHTML=`<table><thead><tr><th class="l">買賣</th><th class="l">代號</th><th class="l">名稱</th>`+
  (hasSlvO?`<th>來源</th>`:``)+`<th>股數</th><th>參考價</th><th>概算金額</th><th>目標權重</th><th class="l">理由</th></tr></thead><tbody>`+
  O.rows.map(r=>`<tr><td class="l ${r.side.indexOf('BUY')>=0?'pos':'neg'}"><b>${esc(r.side)}</b></td>
   <td class="l"><b>${esc(r.code)}</b></td><td class="l">${esc(r.name)}</td>`+
   (hasSlvO?`<td><span class="tag ${r.sleeve==='core'?'t-hold':'t-add'}">${SLVO[r.sleeve]||r.sleeve||'—'}</span></td>`:``)+`
   <td>${nf(r.shares)}</td><td>${pr(r.ref_price)}</td><td>NT$${nf(r.amount)}</td>
   <td>${r.target_frac!=null&&r.target_frac>0?pf(r.target_frac,0):'—'}</td>
   <td class="l" style="font-size:12px;color:var(--ink3)">${esc(r.why)}</td></tr>`).join('')+
  `</tbody></table><p class="hint" style="margin-top:11px">合計概算 NT$`+
  nf(O.rows.reduce((a,r)=>a+(r.side.indexOf('BUY')>=0?r.amount:0),0))+
  ` ｜ 多數為<b>零股</b>委託（單檔 12.5 萬買不到高價股一整張）。</p>`;})();

/* ---------- live positions (paper mode) ---------- */
(function(){const Ps=D.positions;
 if(!Ps||!Ps.length){$('#poscard').style.display='none';return;}
 const tot=Ps.reduce((a,p)=>a+p.value,0);
 const SLV={active:'主動 α',core:'核心 0050'};
 const hasSlv=Ps.some(p=>p.sleeve);
 $('#poshint').textContent=`${Ps.length} 檔 ｜ 市值 NT$${nf(tot)}`;
 $('#positions').innerHTML=`<table><thead><tr><th class="l">代號</th><th class="l">名稱</th>`+
  (hasSlv?`<th class="l">來源</th>`:``)+`<th>股數</th>
  <th>成本</th><th>現價</th><th>市值</th><th>權重</th><th>損益</th></tr></thead><tbody>`+
  Ps.map(p=>`<tr><td class="l"><b>${esc(p.code)}</b></td><td class="l">${esc(p.name)}</td>`+
   (hasSlv?`<td class="l"><span class="tag ${p.sleeve==='core'?'t-hold':'t-add'}">${SLV[p.sleeve]||p.sleeve}</span></td>`:``)+`
   <td>${nf(p.sh)}</td><td>${pr(p.entry)}</td><td>${pr(p.last)}</td><td>NT$${nf(p.value)}</td>
   <td>${pf(p.value/tot,0)}</td><td class="${sg(p.ret)}">${pf(p.ret)}</td></tr>`).join('')+`</tbody></table>`;})();

/* ---------- 集保籌碼分佈 (TDCC) -- DISPLAY ONLY, never fed to `score` ----------
   The feed publishes one weekly snapshot with no history endpoint, so the week-on-week
   deltas only start appearing once the archive has two snapshots. Until then the card
   shows levels plus an honest note about when the deltas arrive -- a level on its own
   says little, since a 85% 千張大戶 share is normal for a large cap and alarming for a
   small one. */
(function(){const T=D.tdcc||{}, ST=D.tdcc_status||{}, Ps=D.positions||[];
 const rows=Ps.map(p=>[p,T[String(p.code).trim()]]).filter(x=>x[1]);
 if(!rows.length){$('#chipcard').style.display='none';return;}
 const asof=rows[0][1].asof, prev=rows[0][1].prev;
 const dl=v=>v==null?'<span style="color:var(--ink3)">—</span>'
   :`<span class="${sg(v)}">${v>0?'+':''}${v.toFixed(2)}</span>`;
 $('#chiphint').innerHTML=`資料日 ${esc(asof)}（集保每週結算）｜ 已存 ${ST.snapshots||1} 週快照 ｜ `+
  (prev?`週變化對比 ${esc(prev)}`
       :`<b>週變化欄下週開始才有</b> — 集保只提供最新一週，歷史必須從現在起累積`)+
  `。<b>此面板不進入選股分數</b>，僅供人工判讀。`;
 $('#chips').innerHTML=`<table><thead><tr><th class="l">代號</th><th class="l">名稱</th>
  <th>大戶 400張+<span class="u"> %</span></th><th>週變化</th>
  <th>千張大戶<span class="u"> %</span></th><th>週變化</th>
  <th>散戶 10張以下<span class="u"> %</span></th>
  <th>股東人數</th><th>週變化</th></tr></thead><tbody>`+
  rows.map(([p,t])=>`<tr><td class="l"><b>${esc(p.code)}</b></td><td class="l">${esc(p.name)}</td>
   <td>${t.big.toFixed(2)}</td><td>${dl(t.d_big)}</td>
   <td>${t.mega.toFixed(2)}</td><td>${dl(t.d_mega)}</td>
   <td>${t.retail.toFixed(2)}</td>
   <td>${t.holders==null?'—':nf(t.holders)}</td>
   <td>${t.d_holders==null?'<span style="color:var(--ink3)">—</span>'
        :`<span class="${sg(-t.d_holders)}">${t.d_holders>0?'+':''}${nf(t.d_holders)}</span>`}</td>
   </tr>`).join('')+`</tbody></table>`+
  `<p class="hint" style="margin-top:10px">讀法：大戶比例上升 + 股東人數下降 = 籌碼集中（故以人數減少為綠）；
   反之為籌碼分散。比例的<b>絕對值</b>在大型股天生就高（台積電千張大戶 ~85%，含外資保管銀行），
   所以只比同一檔的<b>變化</b>，不要跨股比大小。</p>`;})();

/* ---------- allocation donut (cash + holdings), paper mode ---------- */
(function(){const Ps=D.positions;
 const eqc=D.equity&&D.equity.length?D.equity[D.equity.length-1]:null;
 if(!Ps||!Ps.length||!eqc){$('#alloccard').style.display='none';return;}
 const cash=eqc.cash, held=Ps.reduce((a,p)=>a+p.value,0), total=cash+held;
 if(total<=0){$('#alloccard').style.display='none';return;}
 // cash = neutral (uninvested); holdings take the fixed categorical order s1..s6
 const HUE=['var(--s1)','var(--s2)','var(--s3)','var(--s4)','var(--s5)','var(--s6)'];
 const segs=[{label:'現金',value:cash,color:'var(--ink3)'}].concat(
   Ps.slice().sort((a,b)=>b.value-a.value).map((p,i)=>
     ({label:`${p.code} ${p.name}`,value:p.value,color:HUE[i%HUE.length]})));
 $('#allochint').textContent=`總資產 NT$${nf(total)} ｜ 現金 ${pf(cash/total,0)} ｜ 持股 ${pf(held/total,0)}（${Ps.length} 檔）`;
 const R=104,r=64,cx=120,cy=120,gap=0.018;   // donut; gap = 2px surface ring between slices
 const s=`<svg width="240" height="240" viewBox="0 0 240 240" style="flex:0 0 auto">`;
 const P2=( a)=>[cx+R*Math.cos(a),cy+R*Math.sin(a)], p2=(a)=>[cx+r*Math.cos(a),cy+r*Math.sin(a)];
 let ang=-Math.PI/2, arcs='';
 segs.forEach((sg,i)=>{const frac=sg.value/total; let a0=ang+ (segs.length>1?gap/2:0);
   let a1=ang+frac*2*Math.PI-(segs.length>1?gap/2:0); ang+=frac*2*Math.PI;
   if(a1<=a0)a1=a0+0.001; const big=(a1-a0)>Math.PI?1:0;
   const[o0x,o0y]=P2(a0),[o1x,o1y]=P2(a1),[i1x,i1y]=p2(a1),[i0x,i0y]=p2(a0);
   arcs+=`<path d="M${o0x.toFixed(2)} ${o0y.toFixed(2)} A${R} ${R} 0 ${big} 1 ${o1x.toFixed(2)} ${o1y.toFixed(2)} L${i1x.toFixed(2)} ${i1y.toFixed(2)} A${r} ${r} 0 ${big} 0 ${i0x.toFixed(2)} ${i0y.toFixed(2)} Z" fill="${sg.color}" data-i="${i}" style="cursor:pointer"></path>`;});
 const svg=s+arcs+`<text x="${cx}" y="${cy-6}" text-anchor="middle" fill="var(--ink3)" font-size="11">總資產</text>`+
   `<text x="${cx}" y="${cy+14}" text-anchor="middle" fill="var(--ink)" font-size="16" font-weight="600" font-variant-numeric="tabular-nums">NT$${nf(total)}</text></svg>`;
 const tbl=`<div style="flex:1 1 280px;min-width:260px"><table><thead><tr>
     <th class="l">項目</th><th>金額</th><th>佔比</th></tr></thead><tbody>`+segs.map((sg,i)=>
   `<tr class="alegend" data-i="${i}" style="cursor:pointer">
     <td class="l"><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${sg.color};margin-right:7px;vertical-align:-1px"></i>${esc(sg.label)}</td>
     <td style="font-variant-numeric:tabular-nums">NT$${nf(sg.value)}</td>
     <td style="font-variant-numeric:tabular-nums">${pf(sg.value/total,1)}</td></tr>`).join('')+
   `<tr style="font-weight:600"><td class="l">總資產</td>
     <td style="font-variant-numeric:tabular-nums">NT$${nf(total)}</td><td>100%</td></tr>`+
   `</tbody></table></div>`;
 const host=$('#alloc'); host.innerHTML=svg+tbl;
 const tipFor=i=>`<b>${esc(segs[i].label)}</b><br>NT$${nf(segs[i].value)} · ${pf(segs[i].value/total,1)}`;
 host.querySelectorAll('path[data-i]').forEach(el=>{const i=+el.getAttribute('data-i');
   el.addEventListener('mousemove',ev=>showTip(ev,tipFor(i)));
   el.addEventListener('mouseleave',hideTip);});
 host.querySelectorAll('.alegend').forEach(el=>{const i=+el.getAttribute('data-i');
   el.addEventListener('mousemove',ev=>showTip(ev,tipFor(i)));
   el.addEventListener('mouseleave',hideTip);});})();

/* ---------- verdict banner ---------- */
(function(){const C=D.context; if(!C){$('#verdict').style.display='none';return;}
 const beat=(M.total_return>C.bench);
 $('#verdict').innerHTML=`<b>結論：這一年策略跑輸 0050，不建議照這個版本投入實盤。</b><br>
  策略 ${pf(M.total_return)} vs 0050 ${pf(C.bench)}，Sharpe ${(M.sharpe||0).toFixed(2)} vs ${(B.sharpe||0).toFixed(2)}，
  最大回撤 ${pf(M.mdd)} vs ${pf(B.mdd)} — 報酬更低、風險更高，三個指標全輸。<br>
  但原因不是「訊號沒用」：同期<b>中位數個股只有 ${pf(C.median)}</b>，只有 ${pf(C.beat_share,0)} 的個股贏過 0050。
  這一年是少數權值股帶動的行情（台積電 ${pf((C.megacaps.find(x=>x.code==='2330')||{}).ret)}），
  而本策略在 ${C.weeks} 週中<b>從未選進台積電</b> — 籌碼除以成交值、動能取橫斷面 z-score，
  結構上就偏向中小型高波動股。策略績效 (${pf(M.total_return)}) 其實貼近中位數個股 (${pf(C.median)})。`;})();

/* ---------- market context chart ---------- */
(function(){const C=D.context; if(!C){return;}
 const el=$('#ctx'); const W=1200,H=210,P={l:150,r:20,t:16,b:30};
 const s=ax(el,W,H);
 const items=[['中位數個股',C.median,'var(--ink3)'],['第 25 百分位',C.p25,'var(--ink3)'],
  ['第 75 百分位',C.p75,'var(--ink3)'],['第 90 百分位',C.p90,'var(--ink3)'],
  ['本策略',C.strategy,'var(--s1)'],['0050 大盤',C.bench,'var(--s2)']]
  .concat(C.megacaps.filter(m=>m.code!=='2330').slice(0,2).map(m=>[m.name+' '+m.code,m.ret,'var(--ink3)']));
 const mc=C.megacaps.find(x=>x.code==='2330'); if(mc) items.splice(6,0,['台積電 2330',mc.ret,'var(--s3)']);
 const lo=Math.min(0,...items.map(i=>i[1])), hi=Math.max(...items.map(i=>i[1]));
 const X=v=>P.l+(v-lo)*(W-P.l-P.r)/((hi-lo)||1);
 const bh=(H-P.t-P.b)/items.length-4;
 items.forEach((it,i)=>{const y=P.t+i*((H-P.t-P.b)/items.length);
  const x0=X(0), x1=X(it[1]);
  s.appendChild(mk('rect',{x:Math.min(x0,x1),y:y,width:Math.abs(x1-x0)||1,height:bh,fill:it[2],rx:3}));
  const t=mk('text',{x:P.l-10,y:y+bh/2+4,'text-anchor':'end',fill:'var(--ink2)','font-size':12});
  t.textContent=it[0]; s.appendChild(t);
  const v=mk('text',{x:Math.max(x0,x1)+7,y:y+bh/2+4,fill:'var(--ink2)','font-size':11.5});
  v.textContent=(it[1]*100).toFixed(0)+'%'; s.appendChild(v);});
 s.appendChild(mk('line',{x1:X(0),x2:X(0),y1:P.t,y2:H-P.b,stroke:'var(--ink3)','stroke-width':1}));
})();

/* ---------- diagnostics ---------- */
(function(){const G=D.diagnostics; if(!G){return;}
 $('#diag').innerHTML=`<table><thead><tr><th class="l">變體</th><th>總報酬</th><th>Sharpe</th>
  <th>最大回撤</th><th>成交筆數</th><th>總成本</th><th>緊急次數</th></tr></thead><tbody>`+
  G.map(r=>`<tr><td class="l">${esc(r.name)}</td><td class="${sg(r.ret)}">${pf(r.ret)}</td>
   <td>${(r.sharpe||0).toFixed(2)}</td><td class="neg">${pf(r.mdd)}</td>
   <td>${r.n>1?nf(r.n):'—'}</td><td>${r.cost?'NT$'+nf(r.cost):'—'}</td>
   <td>${r.n>1?r.emg:'—'}</td></tr>`).join('')+`</tbody></table>
  <p class="hint" style="margin-top:12px">讀法：<b>停損／緊急機制是有價值的</b> —— 全關掉的話報酬掉到 +11%、
  回撤惡化到 −47%。<b>成本很貴</b> —— 零成本版本多賺約 22 個百分點。
  <b>組合層級的緊急出清是最弱的一環</b> —— 關掉它報酬多 18 個百分點，回撤幾乎沒變差（個股停損已經在做事）。
  但這只是一個多頭年的樣本，空頭年結論可能完全相反，不足以據此拿掉它。</p>`;})();

/* ---------- caveats ---------- */
$('#caveats').innerHTML = D.caveats_html;

/* ---------- utils ---------- */
function tog(){document.body.classList.toggle('dark');
 localStorage.setItem('twdash_dark',document.body.classList.contains('dark')?'1':'0');}
if(localStorage.getItem('twdash_dark')==='1')document.body.classList.add('dark');
function dl(){const rows=[['date','equity','cash','npos','drawdown','bench']];
 const bi={}; D.bench.forEach(b=>bi[b.date]=b.equity);
 D.equity.forEach(e=>rows.push([e.date,e.equity,e.cash,e.npos,e.dd,bi[e.date]??'']));
 const csv=rows.map(r=>r.join(',')).join('\n');
 const a=document.createElement('a');
 a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));
 a.download='tw_strategy_equity.csv';a.click();}
</script></body></html>"""

CAVEATS = """
<b>這是回測模擬，不是投資建議。</b>實際下單前請自行判斷。
<ul class="tight">
<li><b>期間過短</b>：僅 1 年（約 240 個交易日、約 50 次週決策）。這個樣本數不足以區分「策略有效」與「運氣好」。任何單一年度的漂亮數字都可能是市場風格剛好對盤。</li>
<li><b>參數已做 v0 最佳化驗證，刻意保留手設值</b>：以樣本內（2025-06～2026-01）搜尋、樣本外（2026-02～2026-08）驗證，隨機搜尋 250 組。結果顯示在此資料上最佳化會過度配適 — 樣本內最佳者（夏普 5.96）樣本外崩壞（夏普 −0.88），手設參數樣本外反而勝出（夏普 4.39）。故保留手設參數，非「還沒最佳化」而是「測過、最佳化在這段資料無效」（實際數值見上方「策略參數」卡，直接讀自引擎）。</li>
<li><b>無未來函數</b>：決策只用到 D 日（含）以前的資料，一律在 D+1 <u>開盤</u>成交。緊急出場亦同 — 當天發現、隔天開盤賣，不是用當天最低點回測。</li>
<li><b>無倖存者偏誤</b>：universe 每日由當天實際有交易的個股重建，下市個股在下市前都還在樣本內。</li>
<li><b>已還原除權息</b>：TWSE 收盤價未還原，台股 7–9 月除權息集中期正好落在回測區間內。若不還原，配息會被誤判為下跌並觸發假停損。已用 TWSE 除權息計算結果表建立還原因子。</li>
<li><b>成本已計入</b>：手續費 0.1425%（買賣各一次、未打折，偏保守）＋ 證交稅 0.3%（賣出，ETF 0.1%）＋ 滑價 0.1%，最低手續費 NT$20。</li>
<li><b>零股假設</b>：以 1,000,000 元分散於多檔，單檔約 12–17 萬，許多高價股一張就超過此金額，若採整股會把高價的上漲動能個股排除在外，因此模擬採<u>零股</u>成交（可精準到每股、不受單價門檻限制）。盤中零股流動性較差、價差較大，已用 0.1% 滑價涵蓋，但極端情況下可能不足。</li>
<li><b>未模擬的現實摩擦</b>：漲跌停鎖死無法成交、處置股（分盤交易）、停牌、現金股利入帳時點與稅負（含二代健保補充保費）、借券費用。</li>
<li><b>新聞未進入訊號</b>：新聞面僅作為人工複核的資訊面板。歷史新聞難以精確對齊到「當時可得」的時間點，硬做情緒分數會造成嚴重的未來函數並灌水績效。</li>
</ul>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="result.json")
    ap.add_argument("--out", default="tw_dashboard.html")
    a = ap.parse_args()
    d = json.load(open(a.data, encoding="utf-8"))
    d["caveats_html"] = CAVEATS
    open(a.out, "w", encoding="utf-8").write(
        TPL.replace("__DATA__", json.dumps(d, ensure_ascii=False)))
    import os
    print("wrote", a.out, os.path.getsize(a.out), "bytes")


main()
