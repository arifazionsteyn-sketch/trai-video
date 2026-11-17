// Разовая проверка (только чтение) → probe/ (наружу уходит только зашифрованным)
const crypto = require('crypto'); const fs = require('fs');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
const get = async (u, h = {}) => { try { const r = await fetch(u, { headers: h }); return { status: r.status, body: await r.text() }; } catch (e) { return { status: 0, body: String(e) }; } };
(async () => {
  fs.mkdirSync('probe', { recursive: true });
  for (const [n, u] of [['market', '/api/data?part=market'], ['kl1', '/api/data?part=kl&tf=1'], ['tick', '/api/data?part=tick'], ['predictions', '/api/predictions']]) { const r = await get(SITE + u, { 'x-trai-view': key }); fs.writeFileSync(`probe/${n}.json`, r.body); console.log(n, r.status); }
  await new Promise(r => setTimeout(r, 20000));
  const r = await get(SITE + '/api/predictions', { 'x-trai-view': key }); fs.writeFileSync('probe/predictions2.json', r.body);
})();
