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
    await p.goto(SITE + '/#' + v, { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(16000);
    await p.screenshot({ path: `${out}/${v}_${w}.png` }); console.log(v, 'ok');
  }
  console.log(errs.join('\n') || 'без ошибок'); await b.close();
})();
