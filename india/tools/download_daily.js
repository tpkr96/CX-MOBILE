// Daily-bar re-download (Yahoo returns monthly bars for range=max, so daily is fetched in 4-year period1/period2 chunks).
// Usage: node download_daily.js <data_india dir>   (symbol list = files in <dir>/60m)
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const out=process.argv[2]||'data_india',dir=path.join(out,'1d');
const UA={'User-Agent':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36','Accept':'application/json'};
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const syms=fs.readdirSync(path.join(out,'60m')).filter(f=>f.endsWith('.csv')).map(f=>f.slice(0,-4).replace(/^_/,'^'));
async function chunk(sym,p1,p2){for(const host of['query1','query2'])for(let a=0;a<3;a++){try{const u=`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?interval=1d&period1=${p1}&period2=${p2}&includePrePost=false&events=div%2Csplit`;const r=await fetch(u,{headers:UA});if(r.status===429){await sleep(3000*(a+1));continue;}if(r.status===404)return null;if(r.status===400)return [];if(!r.ok){await sleep(1000);continue;}const j=await r.json();const R=j.chart&&j.chart.result&&j.chart.result[0];if(!R||!R.timestamp)return [];const q=R.indicators.quote[0];return R.timestamp.map((t,i)=>[t,q.open[i],q.high[i],q.low[i],q.close[i],q.volume[i]||0]).filter(x=>x[4]!=null&&x[1]!=null);}catch(e){await sleep(1500);}}return null;}
(async()=>{const man=[];const now=Math.floor(Date.now()/1000);
for(const s of syms){let rows=[],bad=false;for(let y=2000;y<=2026;y+=4){const p1=Math.floor(Date.UTC(y,0,1)/1000),p2=Math.min(now,Math.floor(Date.UTC(y+4,0,1)/1000));const r=await chunk(s,p1,p2);if(r===null){bad=true;break;}rows=rows.concat(r);await sleep(250);}
if(bad||rows.length<50){man.push(`FAIL ${s} rows=${rows.length}`);console.log('FAIL',s);continue;}
const m=new Map();rows.forEach(r=>m.set(r[0],r));rows=[...m.values()].sort((a,b)=>a[0]-b[0]);
const gaps=rows.slice(1).map((r,i)=>r[0]-rows[i][0]).sort((a,b)=>a-b);const med=gaps[Math.floor(gaps.length/2)]/86400;
if(med>4){man.push(`FAIL ${s} median gap ${med} days`);console.log('FAIL gap',s,med);continue;}
const csv='ts_utc,open,high,low,close,volume\n'+rows.map(r=>r.join(',')).join('\n')+'\n';const f=path.join(dir,s.replace(/[^A-Za-z0-9.&-]/g,'_')+'.csv');fs.writeFileSync(f,csv);
man.push(`1d ${s} ${rows.length} rows ${new Date(rows[0][0]*1000).toISOString().slice(0,10)}..${new Date(rows[rows.length-1][0]*1000).toISOString().slice(0,10)} ${crypto.createHash('sha256').update(csv).digest('hex')}`);console.log(s,rows.length);}
fs.writeFileSync(path.join(out,'MANIFEST_DAILY.txt'),'Daily re-download '+new Date().toISOString()+'\n'+man.join('\n')+'\n');console.log('DONE');})();
