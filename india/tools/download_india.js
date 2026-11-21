// Downloads real NSE/BSE price history from Yahoo Finance's public chart API (no keys) plus Dhan's public scrip master.
// Usage (Node 18+): node download_india.js <outDir>
// Writes <outDir>/<interval>/<SYMBOL>.csv (ts_utc,open,high,low,close,volume) and MANIFEST.txt with SHA-256 of each file.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const out=process.argv[2]||'data_india';
const IDX=['^NSEI','^NSEBANK','NIFTY_FIN_SERVICE.NS','^NSEMDCP50','^BSESN','BSE-BANK.BO','^INDIAVIX'];
const STK=['RELIANCE','HDFCBANK','ICICIBANK','INFY','TCS','BHARTIARTL','ITC','LT','SBIN','AXISBANK','KOTAKBANK','HINDUNILVR','BAJFINANCE','M&M','MARUTI',
'SUNPHARMA','HCLTECH','NTPC','TATAMOTORS','TITAN','ULTRACEMCO','POWERGRID','ASIANPAINT','ONGC','TATASTEEL','ADANIENT','ADANIPORTS','COALINDIA','BAJAJFINSV',
'NESTLEIND','JSWSTEEL','GRASIM','WIPRO','TECHM','HINDALCO','CIPLA','DRREDDY','EICHERMOT','BEL','TRENT','SHRIRAMFIN','HEROMOTOCO','APOLLOHOSP','INDUSINDBK',
'TATACONSUM','BPCL','BRITANNIA','SBILIFE','HDFCLIFE','BAJAJ-AUTO','DIVISLAB','VEDL','TVSMOTOR','DLF','HAL','IOC','BANKBARODA','PNB','CANBK','TATAPOWER',
'GAIL','SIEMENS','PIDILITIND','GODREJCP','DABUR','CHOLAFIN','LUPIN','AUROPHARMA','INDIGO','ZOMATO','ETERNAL','JIOFIN','RECLTD','PFC','IRFC'].map(s=>s+'.NS');
const BSE=['RELIANCE','HDFCBANK','ICICIBANK','INFY','SBIN'].map(s=>s+'.BO');
const JOBS=[['1d','max'],['60m','730d'],['5m','60d']];
const UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36','Accept':'application/json'};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function get(sym,iv,rg){
  for(const host of ['query1','query2'])for(let a=0;a<3;a++){
    try{const u=`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=${iv}&range=${rg}&includePrePost=false&events=div%2Csplit`;
      const r=await fetch(u,{headers:UA});if(r.status===429){await sleep(3000*(a+1));continue;}
      if(!r.ok){if(r.status===404)return {err:'404'};await sleep(1000);continue;}
      const j=await r.json();const R=j.chart&&j.chart.result&&j.chart.result[0];if(!R||!R.timestamp)return {err:'empty'};
      const q=R.indicators.quote[0];const adj=R.indicators.adjclose&&R.indicators.adjclose[0]&&R.indicators.adjclose[0].adjclose;
      const rows=['ts_utc,open,high,low,close,volume'+(adj?',adjclose':'')];
      R.timestamp.forEach((t,i)=>{if(q.close[i]==null||q.open[i]==null)return;rows.push([t,q.open[i],q.high[i],q.low[i],q.close[i],q.volume[i]||0].concat(adj?[adj[i]]:[]).join(','));});
      return {csv:rows.join('\n')+'\n',n:rows.length-1,tz:R.meta.exchangeTimezoneName,splits:R.events&&R.events.splits?Object.keys(R.events.splits).length:0};
    }catch(e){await sleep(1500);}
  }
  return {err:'failed'};
}
(async()=>{
  const man=[];
  for(const [iv,rg] of JOBS){const d=path.join(out,iv);fs.mkdirSync(d,{recursive:true});
    for(const s of IDX.concat(STK,BSE)){const r=await get(s,iv,rg);
      if(r.err){man.push(`${iv}\t${s}\tERROR ${r.err}`);console.log(iv,s,r.err);continue;}
      const f=path.join(d,s.replace(/[^A-Za-z0-9.&-]/g,'_')+'.csv');fs.writeFileSync(f,r.csv);
      const h=crypto.createHash('sha256').update(r.csv).digest('hex');man.push(`${iv}\t${s}\t${r.n} rows\t${r.tz}\tsplits:${r.splits}\t${h}`);console.log(iv,s,r.n);await sleep(350);}
  }
  try{const r=await fetch('https://images.dhan.co/api-data/api-scrip-master.csv',{headers:UA});if(r.ok){const t=await r.text();fs.writeFileSync(path.join(out,'dhan_scrip_master.csv'),t);man.push('dhan_scrip_master.csv\t'+t.length+' bytes\t'+crypto.createHash('sha256').update(t).digest('hex'));}else man.push('dhan_scrip_master ERROR '+r.status);}catch(e){man.push('dhan_scrip_master ERROR '+e.message);}
  man.unshift('Downloaded '+new Date().toISOString()+' from query1/query2.finance.yahoo.com v8 chart API and images.dhan.co');
  fs.writeFileSync(path.join(out,'MANIFEST.txt'),man.join('\n')+'\n');console.log('DONE');
})();
