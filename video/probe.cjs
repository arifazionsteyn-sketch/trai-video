// Разовые снимки разделов сайта (результат шифруется): все разделы на компьютере
const crypto = require('crypto'); const fs = require('fs'); const { chromium } = require('playwright');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const VIEWS = ['overview', 'agents', 'news', 'tech', 'flow', 'strange', 'gamma', 'market', 'watch', 'journal', 'accuracy', 'settings'];
const TAG = 'before';
(async () => {
  fs.mkdirSync('probe', { recursive: true }); const log = [];
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(() => { try { localStorage.setItem('lang', 'ru'); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); localStorage.setItem('trai.tf2', '"15"'); localStorage.setItem('trai.mode2', '"an"'); } catch {} });
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); p.on('pageerror', e => log.push('ERR ' + e.message));
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(15000);
  for (const v of VIEWS) {
    await p.evaluate(v => { location.hash = v; }, v); await p.waitForTimeout(v === 'watch' || v === 'gamma' || v === 'flow' ? 12000 : 6000);
    await p.screenshot({ path: `probe/${TAG}_${v}.png`, fullPage: false });
    await p.evaluate(() => scrollTo(0, 900)); await p.waitForTimeout(800);
    await p.screenshot({ path: `probe/${TAG}_${v}_2.png`, fullPage: false }); await p.evaluate(() => scrollTo(0, 0));
  }
  fs.writeFileSync('probe/log.txt', log.join('\n')); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
