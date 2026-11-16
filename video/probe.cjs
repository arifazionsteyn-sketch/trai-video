// Разовая проверка (только чтение): сигналы с итогами проверки + свечи GC=F 5 мин и графика сайта → probe/*.json
const crypto = require('crypto'); const fs = require('fs');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
(async () => {
  fs.mkdirSync('probe', { recursive: true });
  const get = async (u, h = {}) => { try { const r = await fetch(u, { headers: h }); return { status: r.status, body: await r.text() }; } catch (e) { return { status: 0, body: String(e) }; } };
  const p = await get(SITE + '/api/predictions', { 'x-trai-view': key });
  fs.writeFileSync('probe/predictions.json', p.body); console.log('pred', p.status);
  for (const tf of ['15m', 'm15', '1h', 'h1']) { const k = await get(SITE + '/api/data?part=kl&tf=' + tf, { 'x-trai-view': key }); console.log('kl', tf, k.status); if (k.status === 200 && k.body.length > 200) { fs.writeFileSync('probe/kl_' + tf + '.json', k.body); } }
  const y = await get('https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=5m&range=5d', { 'user-agent': 'Mozilla/5.0' });
  fs.writeFileSync('probe/gc5m.json', y.body); console.log('src', y.status);
})();
