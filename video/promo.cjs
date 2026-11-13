// Промо «ноутбук»: 1) записываем живые разделы сайта (вход — робот-просмотрщик, только чтение),
// 2) рисуем ролик в promo.html (Three.js), 3) mp4 (+ тихая звуковая дорожка, чтобы Telegram показывал как видео, а не GIF).
// PROMO_MODE=reel — вертикальный 4K (2160×3840, 60 к/с) с подписями; hero — горизонтальный 1920×1080 без слов для витрины (бесшовный повтор)
// node video/promo.cjs out_dir   · PROMO_LANG=ru|en|uz · SITE
const { chromium } = require('playwright'); const crypto = require('crypto'); const fs = require('fs'), path = require('path'), http = require('http');
const { spawn } = require('child_process');
const SITE = (process.env.SITE || 'https://trai-gold-git-dev-steyn1.vercel.app').replace(/\/$/, '');
const THEME = process.env.PROMO_THEME || 'dark';
// story — тот же вертикальный ролик, но без надписей (для сторис)
const LANG = process.env.PROMO_LANG || 'ru', MODE = process.env.PROMO_MODE || 'reel', HERO = MODE === 'hero', STORY = MODE === 'story';
const OUT = path.resolve(process.argv[2] || 'promo_out'), DIR = __dirname, FPS = +(process.env.PROMO_FPS || 60);
// rec — плотность записи сайта, recW — для «Наблюдателя» (в ролике наезд на каждый его блок, поэтому пишем плотнее)
const VIEW = HERO ? { w: 1920, h: 1080, scale: 1, rec: 1.5, recW: 2.5, screenW: 2400 } : { w: 1080, h: 1920, scale: 2, rec: 2, recW: 3, screenW: 3200 };
const WATCH_WAIT = +(process.env.PROMO_WATCH_WAIT || 720); // секунд ждём в «Наблюдателе» до записи — Heatmap и «Внутри свечи» успевают прорисоваться
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const TX = {
  ru: { kick: 'TRAI · ИИ-аналитик золота', intro: ['Золото глазами<br>15 ИИ-агентов', ''], overview: ['План сделки', 'вход · стоп · тейк на графике'], agents: ['15 ИИ-агентов', 'спорят и выносят один вердикт'],
    chat: ['Чат с ИИ', 'спроси — ответит с уровнями'], flow: ['Поток ордеров', 'стаканы и крупные сделки бирж'], strange: ['Доктор Стрэндж', '50 000 сценариев цены'], gamma: ['Гамма 3D', 'где дилеры держат цену'], news: ['Карта событий', 'мировые новости и золото'],
    watch: ['Наблюдатель', 'весь рынок на одном экране'], watch_heat: ['Heatmap', 'где стоят крупные заявки'], watch_fp: ['Внутри свечи', 'покупки и продажи на каждой цене'], watch_flow: ['Поток ордеров', 'стаканы и сделки вживую'],
    outro: ['TRAI', 'ИИ-аналитик золота XAU/USD'], chip: 'Первый анализ бесплатно', bottom: 'Telegram <b>@trai_agent_bot</b>' },
  en: { kick: 'TRAI · AI gold analyst', intro: ['Gold through the eyes<br>of 15 AI agents', ''], overview: ['Trade plan', 'entry · stop · take-profit on the chart'], agents: ['15 AI agents', 'debate and reach one verdict'],
    chat: ['AI chat', 'ask anything — get levels back'], flow: ['Order flow', 'order books and big trades'], strange: ['Doctor Strange', '50,000 price scenarios'], gamma: ['Gamma 3D', 'where dealers hold the price'], news: ['Event map', 'world news and gold'],
    watch: ['Watch mode', 'the whole market on one screen'], watch_heat: ['Liquidity heatmap', 'where the big orders sit'], watch_fp: ['Inside the candle', 'buyers vs sellers at every price'], watch_flow: ['Live order flow', 'order books and trades as they hit'],
    outro: ['TRAI', 'AI gold analyst · XAU/USD'], chip: 'First analysis free', bottom: 'Telegram <b>@trai_agent_bot</b> · <b>trai-agent.com</b>' },
  uz: { kick: 'TRAI · oltin bo‘yicha AI-analitik', intro: ['Oltin 15 ta<br>AI-agent nigohida', ''], overview: ['Savdo rejasi', 'kirish · stop · teyk grafikda'], agents: ['15 ta AI-agent', 'bahslashib, bitta xulosa chiqaradi'],
    chat: ['AI bilan chat', 'so‘rang — darajalar bilan javob beradi'], flow: ['Buyurtmalar oqimi', 'birjalar kitobi va yirik savdolar'], strange: ['Doktor Strendj', '50 000 ta narx ssenariysi'], gamma: ['Gamma 3D', 'dilerlar narxni qayerda ushlaydi'], news: ['Voqealar xaritasi', 'dunyo yangiliklari va oltin'],
    watch: ['Kuzatuvchi', 'butun bozor bitta ekranda'], watch_heat: ['Heatmap', 'yirik buyurtmalar qayerda turibdi'], watch_fp: ['Sham ichida', 'har bir narxda xarid va sotuv'], watch_flow: ['Buyurtmalar oqimi', 'kitob va savdolar jonli'],
    outro: ['TRAI', 'oltin bo‘yicha AI-analitik'], chip: 'Birinchi tahlil bepul', bottom: 'Telegram <b>@trai_agent_bot</b>' },
}[LANG];
// [раздел, секунд в ролике, сколько снимков записать]
// watch_* — один непрерывный «Наблюдатель» на весь экран (запись WATCH_N снимков делится между ними), в ролике камера наезжает на блок
const PLAN = [['overview', 3.0, 64], ['chat', 2.2, 46], ['agents', 2.2, 46], ['watch', 3.0], ['watch_heat', 3.2], ['watch_fp', 2.9], ['watch_flow', 2.5], ['strange', 2.4, 50], ['gamma', 2.8, 58], ['news', 2.8, 58]];
const WATCH_N = 240, ZOOM = { watch_heat: 'heat', watch_fp: 'fp', watch_flow: 'flow' };
const INTRO = 2.0, OUTRO = 1.4;
// Пример сигнала и диалога в чате для ролика (только в записи, на сайте ничего не меняется). Уровни — от текущего графика.
const DEMO = {
  ru: { head: 'Золото держится над POC — покупка на откате к VWAP, цель у сопротивления', sum: 'Цена закрепилась над контрольной точкой объёма, спрос на физическое золото остаётся сильным, положительная гамма дилеров гасит резкие падения. Лучший вход — лимит на откате к дневному VWAP, стоп под поддержкой, тейк у сопротивления. Прибыль к риску около 1 : 2.',
    why: 'Откат к дневному VWAP, стоп за поддержкой, цель — сопротивление.', sc: ['Откат к VWAP и рост к сопротивлению', 'Отбой от сопротивления', 'Боковик без направления'],
    q: 'Дай точку входа на сегодня', a: '**Покупка от VWAP.** Цена держится над POC, гамма дилеров положительная — падения гасятся. Ставь лимит на откате, стоп за поддержкой, цель — ближайшее сопротивление.', q2: 'Какие новости опасны сегодня?' },
  en: { head: 'Gold holds above the POC — buy the pullback to VWAP, target at resistance', sum: 'Price is holding above the volume point of control, physical demand stays strong and positive dealer gamma is damping sharp drops. Best entry: a limit order on the pullback to the daily VWAP, stop below support, take-profit at resistance. Reward-to-risk about 1 : 2.',
    why: 'Pullback to the daily VWAP, stop below support, target at resistance.', sc: ['Pullback to VWAP and rally to resistance', 'Rejection at resistance', 'Range with no direction'],
    q: 'Give me an entry for today', a: '**Buy from VWAP.** Price holds above the POC and dealer gamma is positive, so drops get absorbed. Set a limit on the pullback, stop below support, target the nearest resistance.', q2: 'Which news is risky today?' },
  uz: { head: 'Oltin POC ustida turibdi — VWAP ga qaytishda xarid, maqsad qarshilikda', sum: 'Narx hajmning nazorat nuqtasi ustida mustahkamlandi, jismoniy oltinga talab kuchli, dilerlarning musbat gammasi keskin tushishlarni so‘ndiradi. Eng yaxshi kirish — kunlik VWAP ga qaytishda limit, stop qo‘llab-quvvatlash ostida, teyk qarshilikda. Foyda/risk taxminan 1 : 2.',
    why: 'Kunlik VWAP ga qaytish, stop qo‘llab-quvvatlash ortida, maqsad — qarshilik.', sc: ['VWAP ga qaytish va qarshilikka o‘sish', 'Qarshilikdan qaytish', 'Yo‘nalishsiz yonbosh'],
    q: 'Bugun uchun kirish nuqtasini ber', a: '**VWAP dan xarid.** Narx POC ustida, dilerlar gammasi musbat — tushishlar so‘ndiriladi. Qaytishda limit qo‘ying, stop qo‘llab-quvvatlash ortida, maqsad — eng yaqin qarshilik.', q2: 'Bugun qaysi yangiliklar xavfli?' },
}[LANG];

async function record(b) {
  const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: VIEW.rec, locale: LANG === 'en' ? 'en-US' : 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(l => { try { localStorage.setItem('trai.lang', JSON.stringify(l)); localStorage.setItem('lang', l); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); } catch {} }, LANG); // без обучающего тура и плашки cookie
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); const cdp = await ctx.newCDPSession(p);
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(10000);
  // сигнал «покупка» с аккуратными уровнями от текущей цены и пример диалога в чате — на языке ролика
  const ok = await p.evaluate(D => { const a = JSON.parse(localStorage.getItem('trai.lastAI') || 'null'); if (!a?.chief) return false;
    const px = a.price || 4070, e = Math.round(px - 12), st = +(e - 21.5).toFixed(1), tp = Math.round(e + 45);
    const set = { direction: 'BUY', type: 'limit', entry: e, stop: st, tp, why: D.why };
    Object.assign(a.chief, { decision: 'BUY', confidence: 72, headline: D.head, summary: D.sum, best_setup: set, forced_setup: null,
      scenarios: [{ name: D.sc[0], direction: 'BUY', probability: 55, entry: e, stop: st, targets: [tp] }, { name: D.sc[1], direction: 'SELL', probability: 30 }, { name: D.sc[2], direction: 'WAIT', probability: 15 }] });
    a.entry = { action: 'limit', direction: 'BUY', entry: e, stop: st, tp, comment: D.why }; a.at = Date.now() - 18 * 60e3;
    localStorage.setItem('trai.lastAI', JSON.stringify(a));
    localStorage.setItem('trai.chat', JSON.stringify([{ role: 'user', text: D.q, at: Date.now() - 120e3 }, { role: 'assistant', text: D.a, at: Date.now() - 110e3, setup: { dir: 'BUY', entry: e, stop: st, tp, lot: 0.05 } }]));
    return true; }, DEMO);
  console.log('пример сигнала', ok); await p.reload({ waitUntil: 'domcontentloaded' }); await p.waitForTimeout(10000);
  // вместо сайта — страница входа? Останавливаемся сразу, чтобы не отправить в Telegram ролик с формой входа
  const loginShown = () => p.evaluate(() => { const e = document.querySelector('#lUser'); return !!(e && e.offsetParent); }).catch(() => false);
  if (!ok || await loginShown()) throw new Error('робот-просмотрщик не вошёл на сайт (видна форма входа) — запись остановлена');
  const peek = () => p.evaluate(() => document.querySelector('.rail')?.classList.add('peek')).catch(() => {});
  const shots = {};
  // «Наблюдатель» во весь экран: без нижней панели и строки состояния; ждём, пока Heatmap и «Внутри свечи» наберут историю
  await p.evaluate(() => { location.hash = 'watch'; });
  await p.addStyleTag({ content: 'body[data-view="watch"] .rail,body[data-view="watch"] .statusbar,body[data-view="watch"] .w-edge,body[data-view="watch"] .ag-pill{display:none!important} body[data-view="watch"] main{padding:8px!important} body[data-view="watch"] .w-grid{height:calc(100vh - 16px)!important;min-height:0!important}' });
  console.log('жду в «Наблюдателе»', WATCH_WAIT, 'с'); const tw0 = Date.now();
  await p.mouse.move(0, 899).catch(() => {}); // курсор в угол — без всплывающих подсказок
  while (Date.now() - tw0 < WATCH_WAIT * 1000) await p.waitForTimeout(30000);
  if (await loginShown()) throw new Error('во время ожидания сайт выкинул на вход — запись остановлена');
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 900, deviceScaleFactor: VIEW.recW, mobile: false }); await p.waitForTimeout(4000);
  const rects = await p.evaluate(() => Object.fromEntries(['chart', 'flow', 'heat', 'fp'].map(k => { const r = document.querySelector('.w-' + k)?.getBoundingClientRect(); return [k, r ? { x: r.x / innerWidth, y: r.y / innerHeight, w: r.width / innerWidth, h: r.height / innerHeight } : null]; })));
  { const fr = []; for (let i = 0; i < WATCH_N; i++) { const d = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 88 }).catch(() => null); if (d) fr.push(d.data); if (i % 40 === 0) console.log('наблюдатель', i); }
    shots.watch = fr; shots.watchRects = rects; console.log('запись watch', fr.length, 'снимков', JSON.stringify(rects)); }
  await cdp.send('Emulation.clearDeviceMetricsOverride').catch(() => {});
  await p.evaluate(() => { location.hash = 'overview'; }); await p.waitForTimeout(7000); // обратно на главную: дальше — план сделки
  for (const [v, , N] of PLAN) {
    if (v.startsWith('watch')) continue;
    if (v === 'chat') { await p.evaluate(() => { location.hash = 'overview'; }); await p.waitForTimeout(1500); await p.click('#chatBtn').catch(() => {}); await p.waitForTimeout(1500); }
    else { if (v !== 'overview') await p.evaluate(() => document.body.classList.remove('chat-on'));
      if (v !== 'overview') { await p.evaluate(v => { location.hash = v; }, v); await p.waitForTimeout(v === 'flow' ? 9000 : v === 'gamma' || v === 'news' ? 8000 : 6500); } }
    if (v !== 'chat') await p.keyboard.press('Escape').catch(() => {});
    await p.evaluate(() => scrollTo(0, 0)); await peek();
    const sel = { overview: '#chart, .chart-wrap, canvas', strange: '#stCv' }[v];
    const target = sel ? await p.$(sel) : null; const bx = target ? await target.boundingBox().catch(() => null) : null;
    const maxY = await p.evaluate(() => Math.max(0, document.documentElement.scrollHeight - innerHeight));
    const frames = [];
    for (let i = 0; i < N; i++) {
      const k = i / (N - 1);
      if (v === 'overview') { // мышь по графику; открываем «Слои» и переключаем пару слоёв
        if (bx && (k < 0.22 || k > 0.82)) await p.mouse.move(bx.x + bx.width * (0.3 + 0.5 * k), bx.y + bx.height * (0.45 + 0.05 * Math.sin(k * 7)));
        if (i === Math.round(N * 0.25)) await p.click('#ovBtn').catch(() => {});
        for (const [f, ix] of [[0.36, 3], [0.46, 1], [0.56, 3], [0.66, 1]]) if (i === Math.round(N * f)) await p.evaluate(ix => document.querySelectorAll('#ovMenu [data-ov]')[ix]?.click(), ix).catch(() => {});
        if (i === Math.round(N * 0.78)) await p.keyboard.press('Escape').catch(() => {}), await p.mouse.click(5, 450).catch(() => {});
      }
      if (v === 'chat') { const txt = DEMO.q2, n = Math.round(txt.length * Math.min(1, k * 1.4)); await p.evaluate(t => { const el = document.querySelector('#chatInput'); if (el) el.value = t; }, txt.slice(0, n)); }
      if (v === 'strange' && bx) await p.mouse.move(bx.x + bx.width * (0.28 + 0.55 * k), bx.y + bx.height * (0.45 + 0.06 * Math.sin(k * 6)));
      if ((v === 'gamma' || v === 'news') && maxY > 0) { const q = Math.min(1, Math.max(0, (k - 0.08) / 0.84)); const e = q < 0.5 ? 2 * q * q : 1 - (-2 * q + 2) ** 2 / 2; await p.evaluate(y => scrollTo(0, y), Math.round(maxY * e)); await p.waitForTimeout(60); }
      if (i % 10 === 0) await peek();
      const d = await cdp.send('Page.captureScreenshot', { format: 'jpeg', quality: 90 }).catch(() => null);
      if (d) frames.push(d.data);
    }
    shots[v] = frames; console.log('запись', v, frames.length, 'снимков');
  }
  await ctx.close(); return shots;
}

const STEP = process.env.PROMO_STEP || 'all'; // record — только запись разделов (кадры + job.json); render — кадры FROM..TO в отдельный кусок; all — всё сразу
const encArgs = () => HERO ? ['-c:v', 'libx264', '-preset', 'slow', '-crf', '21', '-maxrate', '8M', '-bufsize', '16M'] : ['-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-maxrate', '40M', '-bufsize', '80M', '-tune', 'film'];

async function doRecord(exe) {
  fs.mkdirSync(path.join(OUT, 'f'), { recursive: true });
  const rb = await chromium.launch({ executablePath: exe, args: ['--no-sandbox'] }); const shots = await record(rb); await rb.close();
  const sections = [{ key: 'intro', start: 0, end: INTRO, kick: TX.kick, title: TX.intro[0], sub: TX.intro[1], frames: [] }];
  let t = INTRO;
  const wTot = PLAN.filter(([v]) => v.startsWith('watch')).reduce((a, [, s]) => a + s, 0); let wPos = 0;
  for (const [v, secs] of PLAN) {
    let fr = shots[v] || [], tag = v;
    if (v.startsWith('watch')) { const all = shots.watch || [], a = Math.floor(all.length * wPos / wTot), b = Math.floor(all.length * (wPos + secs) / wTot); fr = all.slice(a, Math.max(a + 2, b)); tag = 'watch' + Math.round(wPos * 10); wPos += secs; }
    const list = fr.map((d, i) => { const name = `f/${tag}_${String(i).padStart(3, '0')}.jpg`; fs.writeFileSync(path.join(OUT, name), Buffer.from(d, 'base64')); return { src: '/out/' + name, t: fr.length > 1 ? i / (fr.length - 1) * secs : 0 }; });
    const r = ZOOM[v] && shots.watchRects?.[ZOOM[v]], pad = 0.006;
    const zoom = r ? { x: Math.max(0, r.x - pad), y: Math.max(0, r.y - pad), w: Math.min(1, r.w + 2 * pad), h: Math.min(1, r.h + 2 * pad) } : null;
    sections.push({ key: v, start: t, end: t + secs, kick: TX.kick, title: TX[v][0], sub: TX[v][1], frames: list, zoom }); t += secs;
  }
  const last = sections.at(-1);
  sections.push({ key: 'outro', start: t, end: t + OUTRO, kick: '', title: TX.outro[0], sub: TX.outro[1], chip: TX.chip, frames: last.frames.length ? [{ ...last.frames.at(-1), t: 0 }] : [] }); t += OUTRO;
  const job = { theme: THEME, mode: MODE, w: VIEW.w, h: VIEW.h, scale: VIEW.scale, screenW: VIEW.screenW, total: t, sections, bottom: TX.bottom };
  fs.writeFileSync(path.join(OUT, 'job.json'), JSON.stringify(job)); return job;
}

async function doRender(exe, job, from, to, file) {
  const srv = http.createServer((q, r) => { const u = decodeURIComponent(q.url.split('?')[0]); const f = u.startsWith('/out/') ? path.join(OUT, u.slice(5)) : path.join(DIR, u);
    fs.readFile(f, (e, d) => { if (e) { r.statusCode = 404; return r.end(); } r.setHeader('content-type', f.endsWith('.html') ? 'text/html' : f.endsWith('.jpg') ? 'image/jpeg' : 'application/octet-stream'); r.end(d); }); }).listen(0);
  const port = srv.address().port;
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox', '--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
  const p = await b.newPage({ viewport: { width: job.w, height: job.h }, deviceScaleFactor: job.scale }); const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.addInitScript(j => { window.JOB = j; }, job);
  await p.goto(`http://127.0.0.1:${port}/promo.html`); await p.waitForFunction(() => window.ready, null, { timeout: 180000 });
  const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-', ...encArgs(), '-pix_fmt', 'yuv420p', '-r', String(FPS), file]);
  const done = new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg ' + c)))));
  const pv = new Set([1.0, 2.2, 3.5, 5.5, 7.4, 9.4, 11.2, 13.0, 14.6].map(x => Math.round(x * FPS))); const t0 = Date.now();
  for (let i = from; i < to; i++) {
    await p.evaluate(tt => window.render(tt), i / FPS);
    const buf = await p.screenshot({ type: 'jpeg', quality: 97 });
    if (pv.has(i)) fs.writeFileSync(path.join(path.dirname(file), `pv_${String(i).padStart(4, '0')}.jpg`), buf);
    if (HERO && i === Math.round(5.5 * FPS)) fs.writeFileSync(path.join(path.dirname(file), 'trai_hero.jpg'), buf);
    if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    if ((i - from) % 60 === 0) console.log('кадр', i, '·', ((Date.now() - t0) / Math.max(1, i - from + 1) / 1000).toFixed(2), 'с/кадр');
  }
  ff.stdin.end(); await done; srv.close(); await b.close();
  if (errs.length) console.log('ошибки:', errs.slice(0, 4).join(' | '));
}

(async () => {
  const exe = fs.existsSync('/usr/bin/google-chrome') ? '/usr/bin/google-chrome' : undefined;
  const name = (HERO ? 'trai_hero' : STORY ? 'trai_story' : `trai_promo_${LANG}`) + (THEME === 'light' ? '_white' : '');
  if (STEP === 'record') { await doRecord(exe); console.log('запись готова'); return; }
  const job = STEP === 'render' ? JSON.parse(fs.readFileSync(path.join(OUT, 'job.json'), 'utf8')) : await doRecord(exe);
  const n = Math.round(job.total * FPS);
  if (STEP === 'render') { const from = +process.env.FROM, to = Math.min(n, +process.env.TO); fs.mkdirSync(path.join(OUT, 'seg'), { recursive: true }); await doRender(exe, job, from, to, path.join(OUT, 'seg', `${String(from).padStart(5, '0')}.mp4`)); return; }
  const mp4 = path.join(OUT, name + '.mp4'); await doRender(exe, job, 0, n, mp4);
  console.log('готово', mp4, (fs.statSync(mp4).size / 1e6).toFixed(1), 'МБ');
})();
