// Разовая проверка (только чтение) → probe/ (наружу уходит только зашифрованным)
const crypto = require('crypto'); const fs = require('fs');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const get = async (u, h = {}) => { try { const r = await fetch(u, { headers: h }); return { status: r.status, body: await r.text() }; } catch (e) { return { status: 0, body: String(e) }; } };
(async () => {
  fs.mkdirSync('probe', { recursive: true });
  for (const [n, u] of [['predictions', '/api/predictions'], ['kl1', '/api/data?part=kl&tf=1'], ['kl5', '/api/data?part=kl&tf=5']]) { const r = await get(SITE + u, { 'x-trai-view': key }); fs.writeFileSync(`probe/${n}.json`, r.body); console.log(n, r.status); }
  for (const [n, q] of [['gc1m', 'interval=1m&range=5d'], ['gc5m', 'interval=5m&range=1mo']]) { const y = await get('https://query1.finance.yahoo.com/v8/finance/chart/GC=F?' + q, { 'user-agent': 'Mozilla/5.0' }); fs.writeFileSync(`probe/${n}.json`, y.body); console.log(n, y.status); }
})();
