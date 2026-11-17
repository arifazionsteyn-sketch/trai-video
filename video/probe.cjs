// Разовая выгрузка сигналов (только чтение, результат шифруется) — 2
const crypto = require('crypto'); const fs = require('fs');
const SITE = 'https://trai-gold-git-dev-steyn1.vercel.app';
const key = crypto.createHmac('sha256', process.env.TG_BOT_TOKEN || '').update('trai-view-v1').digest('hex');
(async () => { fs.mkdirSync('probe', { recursive: true });
  for (const [n, u] of [['predictions', '/api/predictions'], ['kl5', '/api/data?part=kl&tf=5']]) { const r = await fetch(SITE + u, { headers: { 'x-trai-view': key } }); fs.writeFileSync(`probe/${n}.json`, await r.text()); console.log(n, r.status); }
})();
