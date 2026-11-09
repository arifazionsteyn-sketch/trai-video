// Кадры разделов сайта для роликов и витрины: node video/look.cjs <папка> "watch,overview" [ширина]x[высота]
const { chromium } = require('playwright'); const crypto = require('crypto'); const fs = require('fs');
const SITE = (process.env.SITE || 'https://trai-gold-git-dev-steyn1.vercel.app').replace(/\/$/, '');
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const [out = 'look_out', views = 'watch', size = '1920x1080'] = process.argv.slice(2); const [w, h] = size.split('x').map(Number);
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: w, height: h }, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  for (const v of views.split(',')) {
    if (v === 'tfcheck') { // проверка масштаба графика при смене таймфреймов
      await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(14000);
      for (const tf of ['W', 'D', '5', '60']) {
        await p.click('#tfBtn').catch(() => {}); await p.waitForTimeout(400); await p.click(`#tfMenu [data-tf="${tf}"]`).catch(() => {}); await p.waitForTimeout(5000);
        const info = await p.evaluate(() => { const c = window.__traiChart; if (!c) return 'нет'; const ps = c.chart.priceScale('right'); const d = c.candles.data(); const lr = c.chart.timeScale().getVisibleLogicalRange();
          const vis = d.slice(Math.max(0, Math.floor(lr.from)), Math.ceil(lr.to)); const lo = Math.min(...vis.map(b => b.low)), hi = Math.max(...vis.map(b => b.high));
          const pls = (c.candles.priceLines?.() || []).map(l => l.options().price);
          return { auto: ps.options().autoScale, bars: d.length, vis: vis.length, lo, hi, extra: c.extra, top: c.candles.coordinateToPrice(0), bottom: c.candles.coordinateToPrice(600), minLow: Math.min(...d.map(b => b.low)), maxHigh: Math.max(...d.map(b => b.high)) }; });
        console.log('TF', tf, JSON.stringify(info)); await p.screenshot({ path: `${out}/tf_${tf}.png` });
      }
      continue;
    }
    if (v.startsWith('api:')) { // ответ сервера как есть (проверка источников)
      const r = await ctx.request.get(SITE + '/api/data?part=' + v.slice(4), { headers: { 'x-trai-view': key }, timeout: 90000 });
      fs.writeFileSync(`${out}/${v.slice(4)}.json`, await r.text()); console.log(v, r.status()); continue;
    }
    await p.goto(SITE + '/#' + v, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(16000);
    await p.screenshot({ path: `${out}/${v}_${w}.png` }); console.log(v, 'ok');
  }
  console.log(errs.join('\n') || 'без ошибок'); await b.close();
})();
