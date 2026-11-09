// Кадры разделов сайта для роликов и витрины: node video/look.cjs <папка> "watch,overview" [ширина]x[высота]
const { chromium } = require('playwright'); const crypto = require('crypto'); const fs = require('fs');
const SITE = (process.env.SITE || 'https://trai-gold-git-dev-steyn1.vercel.app').replace(/\/$/, '');
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const [out = 'look_out', views = 'watch', size = '1920x1080'] = process.argv.slice(2); const [w, h] = size.split('x').map(Number);
(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const ctx = await b.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: +(process.env.DPR || 1), locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  for (const v of views.split(',')) {
    if (v === 'promo') { // кадры для витрины: пример сигнала BUY (только в снимке), «Наблюдатель», уведомления, глобус
      const AI = { confidence: 72, headline: 'Золото держится над POC — покупка на откате к VWAP, цель у сопротивления', summary: 'Цена закрепилась над контрольной точкой объёма, спрос на физическое золото остаётся сильным, а положительная гамма дилеров гасит резкие падения. Лучший вход — лимит на откате к дневному VWAP, стоп под поддержкой, тейк у сопротивления. Прибыль к риску около 1 : 2.', why: 'Откат к дневному VWAP, стоп за поддержкой, цель — сопротивление.' };
      await ctx.addInitScript(() => { try { localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.lang', JSON.stringify('ru')); localStorage.setItem('lang', 'ru'); } catch {} });
      await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(12000);
      const ok = await p.evaluate(o => { const a = JSON.parse(localStorage.getItem('trai.lastAI') || 'null'); if (!a?.chief) return false; const px = a.price || 4100, e = Math.round(px - 8), st = +(e - 20).toFixed(1), tp = Math.round(e + 42);
        const set = { direction: 'BUY', type: 'limit', entry: e, stop: st, tp, why: o.why };
        Object.assign(a.chief, { decision: 'BUY', confidence: o.confidence, headline: o.headline, summary: o.summary, best_setup: set, forced_setup: null });
        a.entry = { action: 'limit', direction: 'BUY', entry: e, stop: st, tp, comment: o.why }; a.at = Date.now() - 20 * 60e3; localStorage.setItem('trai.lastAI', JSON.stringify(a)); return true; }, AI);
      console.log('promo_ai', ok); await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForTimeout(12000);
      await p.screenshot({ path: `${out}/promo-overview.png` });
      await p.click('#chAlert').catch(() => {}); await p.waitForTimeout(2500); await p.locator('.chart-panel').screenshot({ path: `${out}/promo-alerts.png` }).catch(e => console.log('alerts', e.message));
      await p.keyboard.press('Escape'); await p.evaluate(() => { location.hash = 'watch'; }); await p.waitForTimeout(16000); await p.screenshot({ path: `${out}/promo-watch.png` });
      await p.evaluate(() => { location.hash = 'news'; }); await p.waitForTimeout(8000); await p.evaluate(() => document.querySelector('#nwGlobe')?.scrollIntoView({ block: 'center' })); await p.waitForTimeout(6000);
      const g = await p.$('#c-globe'); if (g) await g.screenshot({ path: `${out}/promo-globe.png` });
      console.log('globe markers', await p.evaluate(() => document.querySelectorAll('#c-globe canvas').length));
      continue;
    }
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
