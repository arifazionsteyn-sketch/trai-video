// Разовые снимки «до/после» графика (результат шифруется)
const crypto = require('crypto'); const fs = require('fs'); const { chromium } = require('playwright');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
(async () => {
  fs.mkdirSync('probe', { recursive: true }); const log = [];
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  for (const [name, look] of [['before', 'off'], ['after', 'tv']]) {
    const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
    await ctx.addInitScript(l => { try { localStorage.setItem('trai.lang', '"ru"'); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); localStorage.setItem('trai.tf2', '"15"'); localStorage.setItem('trai.mode2', '"an"'); localStorage.setItem('trai.look', JSON.stringify(l)); localStorage.removeItem('trai.draw'); } catch {} }, look);
    await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
    const p = await ctx.newPage(); p.on('pageerror', e => log.push(name + ' ERR ' + e.message)); p.on('console', m => { if (m.type() === 'error') log.push(name + ' ' + m.text()); });
    await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(16000);
    await p.screenshot({ path: `probe/${name}.png` });
    if (look === 'tv') {
      await p.evaluate(() => window.__tvlook?.demo()); await p.waitForTimeout(800);
      const box = await p.$('#lw'); const bb = await box.boundingBox();
      await p.mouse.move(bb.x + bb.width * 0.62, bb.y + bb.height * 0.45); await p.waitForTimeout(600);
      await p.screenshot({ path: 'probe/after_tools.png' });
    }
    await ctx.close();
  }
  fs.writeFileSync('probe/log.txt', log.join('\n')); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
