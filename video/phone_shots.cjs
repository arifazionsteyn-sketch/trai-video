// Проверка телефонной версии: все разделы dev-сайта в размере iPhone (390×844, ×3) → PNG.
// Робот-просмотрщик, только чтение. node video/phone_shots.cjs out_dir · PHONE_LANG=ru
const { chromium, devices } = require('playwright'); const crypto = require('crypto'); const fs = require('fs'), path = require('path');
const SITE = (process.env.SITE || 'https://trai-gold-git-dev-steyn1.vercel.app').replace(/\/$/, '');
const LANG = process.env.PHONE_LANG || 'ru', OUT = path.resolve(process.argv[2] || 'phone');
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const VIEWS = (process.env.PHONE_VIEWS || 'overview,market,news,tech,flow,strange,gamma,agents,watch,journal,accuracy,settings').split(',');
(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ executablePath: fs.existsSync('/usr/bin/google-chrome') ? '/usr/bin/google-chrome' : undefined, args: ['--no-sandbox'] });
  const ctx = await b.newContext({ ...devices['iPhone 13'], deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(l => { try { localStorage.setItem('trai.lang', JSON.stringify(l)); localStorage.setItem('lang', l); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); } catch {} }, LANG);
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(14000);
  if (await p.evaluate(() => { const e = document.querySelector('#lUser'); return !!(e && e.offsetParent); })) throw new Error('робот не вошёл на сайт');
  const snap = async name => { await p.screenshot({ path: path.join(OUT, name + '.png') }); const h = await p.evaluate(() => document.documentElement.scrollHeight);
    if (h > 900) await p.screenshot({ path: path.join(OUT, name + '_full.png'), fullPage: true }); console.log('снимок', name, h); };
  for (const v of VIEWS) {
    await p.evaluate(v => { location.hash = v; }, v); await p.waitForTimeout(v === 'flow' || v === 'watch' || v === 'gamma' ? 11000 : 7000); await p.evaluate(() => scrollTo(0, 0)); await p.waitForTimeout(600);
    await snap(v);
    if (v === 'overview') { // меню «Слои» и чат
      await p.click('#ovBtn').catch(() => {}); await p.waitForTimeout(800); await snap('overview_layers'); await p.keyboard.press('Escape').catch(() => {}); await p.mouse.click(5, 300).catch(() => {});
      await p.click('#chatBtn').catch(() => {}); await p.waitForTimeout(1500); await snap('overview_chat'); await p.evaluate(() => document.body.classList.remove('chat-on')); await p.keyboard.press('Escape').catch(() => {});
    }
  }
  fs.writeFileSync(path.join(OUT, 'errors.txt'), errs.join('\n') || 'нет ошибок');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
