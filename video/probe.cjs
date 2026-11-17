// Разовая проверка (только чтение): сигналы, свечи сайта, GC=F и снимки графика при смене таймфрейма → probe/ (наружу уходит только зашифрованным)
const crypto = require('crypto'); const fs = require('fs'); const { chromium } = require('playwright');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const get = async (u, h = {}) => { try { const r = await fetch(u, { headers: h }); return { status: r.status, body: await r.text() }; } catch (e) { return { status: 0, body: String(e) }; } };
(async () => {
  fs.mkdirSync('probe', { recursive: true });
  const H = { 'x-trai-view': key };
  for (const [n, u] of [['predictions', '/api/predictions'], ['kl1', '/api/data?part=kl&tf=1'], ['kl5', '/api/data?part=kl&tf=5'], ['kl15', '/api/data?part=kl&tf=15']]) {
    const r = await get(SITE + u, H); fs.writeFileSync(`probe/${n}.json`, r.body); console.log(n, r.status);
  }
  const y = await get('https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1m&range=5d', { 'user-agent': 'Mozilla/5.0' }); fs.writeFileSync('probe/gc1m.json', y.body); console.log('src1', y.status);
  // график: Анализ → 1ч → 5м → 15м → 1м, снимки и состояние
  const b = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await b.newContext({ viewport: { width: 1280, height: 760 }, locale: 'ru-RU', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript(() => { try { localStorage.setItem('trai.lang', '"ru"'); localStorage.setItem('trai.tourDone', '1'); localStorage.setItem('trai.ck', '1'); localStorage.setItem('trai.tf2', '"60"'); localStorage.setItem('trai.mode2', '"an"'); } catch {} });
  await ctx.route('**/*', rt => { const u = rt.request().url(); return u.startsWith(SITE) ? rt.continue({ headers: { ...rt.request().headers(), 'x-trai-view': key } }) : rt.continue(); });
  const p = await ctx.newPage(); const log = []; p.on('pageerror', e => log.push('ERR ' + e.message)); p.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') log.push(m.type() + ' ' + m.text()); });
  p.on('response', async r => { const u = r.url(); if (u.includes('part=kl')) { let n = '?'; try { const j = await r.json(); n = (j.bars || []).length + ' last ' + (j.bars?.at(-1) || []).join(',') + ' part ' + !!j.part + ' src ' + j.src; } catch {} log.push('kl ' + r.status() + ' ' + u.split('?')[1] + ' → ' + n); } });
  await p.goto(SITE + '/#overview', { waitUntil: 'domcontentloaded' }); await p.waitForTimeout(14000);
  await p.click('#modeSeg [data-mode="an"]').catch(() => {}); await p.waitForTimeout(2500);
  await p.screenshot({ path: 'probe/tf_60.png' });
  for (const tf of ['5', '15', '1', '5']) {
    await p.click('#tfBtn').catch(e => log.push('tfBtn ' + e.message)); await p.waitForTimeout(400);
    await p.click(`#tfMenu [data-tf="${tf}"]`).catch(e => log.push('tf ' + e.message));
    await p.waitForTimeout(1500); await p.screenshot({ path: `probe/tf_${tf}_a.png` });
    await p.waitForTimeout(6000); await p.screenshot({ path: `probe/tf_${tf}_b.png` });
    log.push('tf ' + tf + ' note: ' + await p.evaluate(() => document.querySelector('#chartNote')?.textContent));
  }
  fs.writeFileSync('probe/log.txt', log.join('\n')); await b.close();
})().catch(e => { console.error(e); process.exit(1); });
