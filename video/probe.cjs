// Разовая проверка (только чтение) → probe/ (наружу уходит только зашифрованным)
const fs = require('fs'); const { chromium } = require('playwright');
(async () => {
  fs.mkdirSync('probe', { recursive: true });
  const b = await chromium.launch({ args: ['--no-sandbox'] }); const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
  const p = await ctx.newPage(); const hosts = new Map(), ws = [], scripts = [];
  p.on('request', r => { try { const u = new URL(r.url()); hosts.set(u.host, (hosts.get(u.host) || 0) + 1); if (r.resourceType() === 'script') scripts.push(r.url()); } catch {} });
  p.on('websocket', w => ws.push(w.url()));
  for (const u of ['https://next.vestmarkets.com/', 'https://next.vestmarkets.com/trade', 'https://next.vestmarkets.com/login']) {
    try { await p.goto(u, { waitUntil: 'networkidle', timeout: 30000 }); } catch {}
    await p.waitForTimeout(5000); const n = u.split('/').pop() || 'home';
    await p.screenshot({ path: `probe/vm_${n}.png` }); fs.writeFileSync(`probe/vm_${n}.txt`, (await p.evaluate(() => document.body.innerText)).slice(0, 4000) + '\nURL ' + p.url());
  }
  // поиск следов источника цен в загруженных скриптах
  const hits = []; for (const s of [...new Set(scripts)].slice(0, 40)) { try { const t = await (await fetch(s)).text(); for (const k of ['tradingview', 'lightweight-charts', 'charting_library', 'datafeed', 'wss://', 'polygon', 'twelvedata', 'finnhub', 'oanda', 'tradelocker', 'match-trader', 'matchtrader', 'ctrader', 'dxtrade', 'metaapi', 'quote', 'lp ']) { const i = t.toLowerCase().indexOf(k); if (i >= 0) hits.push(k + ' @ ' + s.split('/').pop() + ' : ' + t.slice(Math.max(0, i - 80), i + 120).replace(/\s+/g, ' ')); } } catch {} }
  fs.writeFileSync('probe/vm_net.txt', [...hosts].map(x => x.join(' ')).join('\n') + '\n\nWS:\n' + ws.join('\n') + '\n\nHITS:\n' + hits.join('\n'));
  await b.close();
})();
