// End-to-end test of the India Bot phone app with a mocked Dhan feed and a fast clock (1 real second = 5 market minutes).
// Run: node tests/app_test.js  (needs playwright; serves ../ over a local http server)
const { chromium } = require('playwright'); const http = require('http'); const fs = require('fs'); const path = require('path');
const ROOT = path.resolve(__dirname, '..', '..');
const srv = http.createServer((q, r) => { let f = path.join(ROOT, decodeURIComponent(q.url.split('?')[0])); if (f.endsWith('/')) f += 'index.html';
  fs.readFile(f, (e, d) => { if (e) { r.writeHead(404); r.end(); return; } r.writeHead(200, { 'Content-Type': f.endsWith('.html') ? 'text/html' : f.endsWith('.js') ? 'text/javascript' : 'application/octet-stream' }); r.end(d); }); });
const results = []; const ok = (name, cond, info = '') => { results.push([name, !!cond, info]); console.log((cond ? 'PASS ' : 'FAIL ') + name + (info ? '  ' + info : '')); };
(async () => {
  await new Promise(r => srv.listen(8791, r));
  const b = await chromium.launch(); const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  const page = await ctx.newPage(); const errs = []; page.on('pageerror', e => errs.push(e.message));
  // scrip master mock (CORS-allowed in reality)
  const NAMES = ["RELIANCE","HDFCBANK","ICICIBANK","INFY","TCS","SBIN"];
  let csv = 'SEM_EXM_EXCH_ID,SEM_SEGMENT,SEM_SMST_SECURITY_ID,SEM_INSTRUMENT_NAME,SEM_EXPIRY_CODE,SEM_TRADING_SYMBOL,SEM_LOT_UNITS,SEM_CUSTOM_SYMBOL,SEM_EXPIRY_DATE,SEM_STRIKE_PRICE,SEM_OPTION_TYPE,SEM_TICK_SIZE,SEM_EXPIRY_FLAG,SEM_EXCH_INSTRUMENT_TYPE,SEM_SERIES,SM_SYMBOL_NAME\n';
  NAMES.forEach((s, i) => { csv += `NSE,E,${9000 + i},EQUITY,0,${s},1,${s},,,,0.05,,ES,EQ,${s}\nBSE,E,${5000 + i},EQUITY,0,${s},1,${s},,,,0.05,,ES,A,${s}\n`; });
  csv += 'NSE,I,13,INDEX,0,NIFTY,1,Nifty 50,,,,0.05,,INDEX,,NIFTY\nNSE,I,25,INDEX,0,BANKNIFTY,1,Nifty Bank,,,,0.05,,INDEX,,BANKNIFTY\nBSE,I,51,INDEX,0,SENSEX,1,Sensex,,,,0.05,,INDEX,,SENSEX\n';
  await page.route('https://images.dhan.co/**', r => r.fulfill({ status: 200, body: csv, headers: { 'access-control-allow-origin': '*' } }));
  await page.addInitScript(() => {
    // fast clock: start Mon 23 Nov 2026 09:15:00 IST (03:45 UTC), 300x speed
    const base = Date.UTC(2026, 10, 23, 3, 45, 0), t0 = performance.now(), RealDate = Date;
    const now = () => base + (performance.now() - t0) * 297; Date.now = now;
    window.__sent = []; window.__wsurl = null;
    class MockWS { constructor(u) { window.__wsurl = u; this.readyState = 0; setTimeout(() => { this.readyState = 1; this.onopen && this.onopen(); this.startFeed(); }, 50); }
      send(m) { window.__sent.push(JSON.parse(m)); } close() { clearInterval(this.iv); this.readyState = 3; }
      startFeed() { const px = {}, cum = {}; let step = 0;
        this.iv = setInterval(() => { step++; const list = window.__sent.flatMap(s => s.InstrumentList);
          const segN = { IDX_I: 0, NSE_EQ: 1, BSE_EQ: 4 };
          const parts = list.map((x, i) => { const k = x.ExchangeSegment + x.SecurityId; px[k] = px[k] || (x.ExchangeSegment === 'IDX_I' ? 26000 : 1000 + 100 * i); cum[k] = cum[k] || 0;
            // trend up for the first half of the session, with noise; volume surges every 40 steps
            const drift = (Math.sin(step / 25 + i) * 0.0009); px[k] *= Math.exp(drift + (Math.random() - 0.5) * 0.004); cum[k] += (step % 40 < 4 ? 5000 : 500) + Math.floor(Math.random() * 300);
            const buf = new ArrayBuffer(50), dv = new DataView(buf); dv.setUint8(0, 4); dv.setUint16(1, 50, true); dv.setUint8(3, segN[x.ExchangeSegment]); dv.setInt32(4, +x.SecurityId, true);
            dv.setFloat32(8, px[k], true); dv.setInt16(12, 10, true); dv.setInt32(14, 0, true); dv.setFloat32(18, px[k], true); dv.setInt32(22, cum[k], true); dv.setInt32(26, 1000, true); dv.setInt32(30, 1200, true);
            dv.setFloat32(34, 1000, true); dv.setFloat32(38, 990, true); dv.setFloat32(42, px[k], true); dv.setFloat32(46, px[k], true); return new Uint8Array(buf); });
          const all = new Uint8Array(parts.length * 50); parts.forEach((p, i) => all.set(p, i * 50)); this.onmessage && this.onmessage({ data: all.buffer }); }, 100); } }
    window.WebSocket = MockWS;
  });
  await page.goto('http://127.0.0.1:8791/india/index.html');
  ok('T1 loads without errors, shows PAPER badge', (await page.textContent('header')).includes('PAPER') && errs.length === 0, errs.join('|'));
  ok('T2 no order code in the page', !(await page.content()).match(/\/super\/orders|\/v2\/orders|placeOrder/));
  await page.click('nav button[data-t=set]'); await page.fill('#cid', '1100000001'); await page.fill('#tok', 'TEST-TOKEN-XYZ'); await page.click('#btnConn');
  await page.waitForTimeout(1500);
  const url = await page.evaluate(() => window.__wsurl);
  ok('T3 connects to Dhan v2 feed URL with authType=2', url && url.startsWith('wss://api-feed.dhan.co?version=2&token=TEST-TOKEN-XYZ&clientId=1100000001&authType=2'), url);
  const sent = await page.evaluate(() => window.__sent);
  ok('T4 subscribes in quote mode (RequestCode 17), <=100 per message', sent.length >= 1 && sent.every(s => s.RequestCode === 17 && s.InstrumentList.length <= 100 && s.InstrumentCount === s.InstrumentList.length), JSON.stringify(sent[0]).slice(0, 120));
  ok('T5 scrip master resolved IDs (uses 9000-series from mock)', sent.flatMap(s => s.InstrumentList).some(x => x.SecurityId === '9000' && x.ExchangeSegment === 'NSE_EQ'));
  ok('T6 token not stored anywhere', await page.evaluate(() => !JSON.stringify(localStorage).includes('TEST-TOKEN') && !JSON.stringify(sessionStorage).includes('TEST-TOKEN') && document.getElementById('tok').value === ''));
  await page.click('nav button[data-t=scan]'); await page.click('#btnRun');
  await page.waitForTimeout(45000); // ~225 market minutes
  const st = await page.evaluate(() => { const a = window.__inb.acct(); const k = Object.keys(window.__inb.bars()); return { closed: a.closed.length, open: Object.keys(a.open).length, bars: Math.max(...k.map(x => window.__inb.bars()[x].length)), eq: a.eq, ch: a.closed.reduce((s, c) => s + c.ch, 0), log: document.getElementById('log').textContent.slice(0, 600) }; });
  ok('T7 builds 5-minute bars from the feed', st.bars >= 30, 'max bars ' + st.bars);
  ok('T8 paper trades happen and charges are deducted', st.closed + st.open > 0 && (st.closed === 0 || st.ch > 0), JSON.stringify({ closed: st.closed, open: st.open, eq: Math.round(st.eq), ch: Math.round(st.ch) }) + ' LOG: ' + st.log.slice(0,500));
  const md = await page.evaluate(() => window.__inb.mood(window.__inb.istNow()));
  ok('T9 Nifty mood computed', md.bias != null, JSON.stringify(md).slice(0, 150));
  await page.waitForTimeout(32000); // past 15:15
  const st2 = await page.evaluate(() => ({ open: Object.keys(window.__inb.acct().open).length, t: window.__inb.istNow().toISOString() }));
  ok('T10 all positions squared off by 15:15 IST', st2.open === 0, JSON.stringify(st2));
  const c = await page.evaluate(() => window.__inb.charges(100000, 100000, 'NSE'));
  ok('T11 intraday charges: STT 25, brokerage 40 on Rs1L each side', Math.abs(c.stt - 25) < 1e-9 && Math.abs(c.brok - 40) < 1e-9, JSON.stringify(c));
  await page.click('nav button[data-t=trades]'); await page.screenshot({ path: path.join(__dirname, 'shot_trades.png') });
  await page.click('nav button[data-t=market]'); await page.screenshot({ path: path.join(__dirname, 'shot_market.png') });
  await page.click('nav button[data-t=scan]'); await page.screenshot({ path: path.join(__dirname, 'shot_scan.png') });
  ok('T12 no page errors during the run', errs.length === 0, errs.slice(0, 3).join(' | '));
  const pass = results.filter(r => r[1]).length; console.log(`\n${pass}/${results.length} passed`);
  fs.writeFileSync(path.join(__dirname, 'app_test.json'), JSON.stringify({ when: new Date().toISOString(), pass, total: results.length, results }, null, 1));
  await b.close(); srv.close(); process.exit(pass === results.length ? 0 : 1);
})();
