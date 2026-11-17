// Разовый замер плавности графика на тестовой версии (результат шифруется): кадры при сдвиге, масштабе, растяжке шкалы и открытии панели вердикта
const crypto = require('crypto'); const fs = require('fs'); const { chromium } = require('playwright');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const sleep = ms => new Promise(r => setTimeout(r, ms));
(async () => {
  fs.mkdirSync('probe', { recursive: true }); const log = []; const out = {};
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(() => { try { localStorage.setItem('lang', 'ru'); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); localStorage.setItem('trai.tf2', '"15"'); localStorage.setItem('trai.mode2', '"an"'); localStorage.setItem('trai.vsOpen', 'true'); } catch {} });
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); p.on('pageerror', e => log.push('ERR ' + e.message));
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(16000);
  out.env = await p.evaluate(() => ({ cores: navigator.hardwareConcurrency, dpr: devicePixelRatio, bars: window.__traiChart?.candles?.data?.()?.length, closed: document.querySelector('#ovWrap')?.classList.contains('vs-closed') }));
  const cdp = await ctx.newCDPSession(p); await cdp.send('Profiler.enable'); await cdp.send('Profiler.setSamplingInterval', { interval: 250 });
  const startRec = () => p.evaluate(() => {
    window.__fr = []; window.__lt = []; window.__tr = []; let last = performance.now(); window.__frOn = true;
    const c = window.__traiChart; const d = c?.candles?.data?.() || []; const px = d.length ? d[d.length - 1].close : null; window.__px = px;
    const tick = t => { window.__fr.push(t - last); last = t; try { const lw = document.querySelector('#lw'), bx = lw.parentElement; window.__tr.push([Math.round(t), px != null ? Math.round(c.candles.priceToCoordinate(px) * 10) / 10 : null, lw.clientWidth, bx.clientWidth, bx.clientHeight, Math.round(c.chart.timeScale().width())]); } catch {} if (window.__frOn) requestAnimationFrame(tick); };
    requestAnimationFrame(tick);
    try { new PerformanceObserver(l => l.getEntries().forEach(e => window.__lt.push(Math.round(e.duration)))).observe({ type: 'longtask' }); } catch {}
  });
  const stopRec = () => p.evaluate(() => { window.__frOn = false; const f = window.__fr.slice(1).sort((a, b) => a - b); const n = f.length; return { n, p50: +f[n >> 1]?.toFixed(1), p90: +f[Math.floor(n * .9)]?.toFixed(1), max: +f[n - 1]?.toFixed(1), over33: f.filter(x => x > 33).length, longtasks: window.__lt, trace: window.__tr }; });
  async function rec(name, fn, prof) {
    await startRec(); if (prof) await cdp.send('Profiler.start');
    await fn();
    if (prof) { const { profile } = await cdp.send('Profiler.stop'); fs.writeFileSync(`probe/${name}.cpuprofile`, JSON.stringify(profile)); }
    out[name] = await stopRec(); await sleep(600);
  }
  const box = await p.locator('#lw').boundingBox(); const cx = box.x + box.width * 0.55, cy = box.y + box.height * 0.45;
  await p.screenshot({ path: 'probe/start.png' });
  await rec('pan', async () => { await p.mouse.move(cx, cy); await p.mouse.down(); for (let i = 0; i < 70; i++) { await p.mouse.move(cx - i * 6, cy + Math.sin(i / 8) * 20); await sleep(16); } await p.mouse.up(); }, true);
  await rec('zoom', async () => { await p.mouse.move(cx, cy); for (let i = 0; i < 30; i++) { await p.mouse.wheel(0, i < 15 ? -120 : 120); await sleep(33); } }, true);
  const ax = box.x + box.width - 25;
  await rec('stretch', async () => { await p.mouse.move(ax, cy); await p.mouse.down(); for (let i = 0; i < 50; i++) { await p.mouse.move(ax, cy + i * 4); await sleep(16); } for (let i = 50; i > 0; i--) { await p.mouse.move(ax, cy + i * 4); await sleep(16); } await p.mouse.up(); }, true);
  await rec('hover', async () => { for (let i = 0; i < 80; i++) { await p.mouse.move(box.x + 100 + i * 10, box.y + 200 + (i % 10) * 15); await sleep(16); } }, true);
  await p.mouse.move(box.x + 5, box.y - 40);
  await rec('vs_close', async () => { await p.click('#vsToggle'); await sleep(1150); }, true);
  await p.screenshot({ path: 'probe/closed.png' });
  await rec('vs_open', async () => { await p.click('#vsTab'); await sleep(1150); }, true);
  await p.screenshot({ path: 'probe/open.png' });
  fs.writeFileSync('probe/out.json', JSON.stringify(out)); fs.writeFileSync('probe/log.txt', log.join('\n')); await b.close();
})().catch(e => { console.error(e); fs.writeFileSync('probe/fail.txt', String(e.stack || e)); process.exit(1); });
