// Скриншоты для витрины: живые разделы dev-сайта (робот-просмотрщик, только чтение) → WebP 1440 px.
// «Наблюдатель» снимаем последним: перед этим ждём, пока Heatmap и «Внутри свечи» наберут историю.
// node video/landing_shots.cjs out_dir · SHOTS_LANG=ru · SHOTS_WAIT=720
const { chromium } = require('playwright'); const crypto = require('crypto'); const fs = require('fs'), path = require('path');
const SITE = (process.env.SITE || 'https://trai-gold-git-dev-steyn1.vercel.app').replace(/\/$/, '');
const LANG = process.env.SHOTS_LANG || 'ru', WAIT = +(process.env.SHOTS_WAIT || 720), ONLY = (process.env.SHOTS_ONLY || '').split(',').filter(Boolean), want = n => !ONLY.length || ONLY.includes(n), OUT = path.resolve(process.argv[2] || 'shots');
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const CLEAN = 'header.top,.rail,.statusbar,.ag-pill,#runFab,.ck,#tourBox,#tourRing{display:none!important}';

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const b = await chromium.launch({ executablePath: fs.existsSync('/usr/bin/google-chrome') ? '/usr/bin/google-chrome' : undefined, args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(l => { try { localStorage.setItem('trai.lang', JSON.stringify(l)); localStorage.setItem('lang', l); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); } catch {} }, LANG);
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage();
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(12000);
  if (await p.evaluate(() => { const e = document.querySelector('#lUser'); return !!(e && e.offsetParent); })) throw new Error('робот не вошёл на сайт (видна форма входа)');
  await p.addStyleTag({ content: CLEAN });
  const go = async (v, ms) => { await p.evaluate(v => { location.hash = v; }, v); await p.waitForTimeout(ms); await p.evaluate(() => scrollTo(0, 0)); await p.addStyleTag({ content: CLEAN }); await p.mouse.move(0, 899); };
  // клип вокруг элементов (с полями), координаты страницы
  const clipOf = async (sels, pad = 14) => p.evaluate(([sels, pad]) => { const rs = sels.map(s => document.querySelector(s)?.getBoundingClientRect()).filter(Boolean); if (!rs.length) return null;
    const x0 = Math.min(...rs.map(r => r.left)) - pad, y0 = Math.min(...rs.map(r => r.top)) - pad, x1 = Math.max(...rs.map(r => r.right)) + pad, y1 = Math.max(...rs.map(r => r.bottom)) + pad;
    return { x: Math.max(0, x0), y: Math.max(0, y0 + scrollY), width: Math.min(innerWidth, x1) - Math.max(0, x0), height: y1 - Math.max(0, y0) }; }, [sels, pad]);
  // без fullPage: снимок «во всю страницу» на миг меняет размер окна, и 3D-глобус успевает перерисоваться не в том размере
  const shot = async (name, sels) => { await p.evaluate(s => { const e = document.querySelector(s); if (e) { const r = e.getBoundingClientRect(); scrollTo(0, Math.max(0, scrollY + r.top - 20)); } }, sels[0]); await p.waitForTimeout(1500);
    const c = await clipOf(sels); if (c) c.y -= await p.evaluate(() => scrollY);
    await p.screenshot({ path: path.join(OUT, name + '.png'), clip: c || undefined }); console.log('снимок', name, JSON.stringify(c)); };

  if (want('strange')) { await go('strange', 9000); await shot('strange', ['#c-mc']); }
  if (want('flow')) { await go('flow', 12000); await shot('flow', ['.fl-top', '.fl-live']); }
  if (want('globe')) { await go('news', 12000); await shot('globe', ['.news-top']); }
  if (!want('watch')) { await b.close(); return; }
  // «Наблюдатель» во весь экран
  await go('watch', 3000);
  await p.addStyleTag({ content: 'body[data-view="watch"] main{padding:8px!important} body[data-view="watch"] .w-grid{height:calc(100vh - 16px)!important;min-height:0!important} body[data-view="watch"] .w-edge{display:none!important}' });
  console.log('жду в «Наблюдателе»', WAIT, 'с'); const t0 = Date.now(); while (Date.now() - t0 < WAIT * 1000) await p.waitForTimeout(30000);
  await p.screenshot({ path: path.join(OUT, 'watch.png') }); console.log('снимок watch');
  await b.close();
})().catch(e => { console.error(e); process.exit(1); });
