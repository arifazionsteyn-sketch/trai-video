// TRAI — запуск ежедневных роликов вовремя (Cloudflare Workers, бесплатный план).
// Расписание GitHub срабатывает с опозданием на несколько часов, а Cron у Cloudflare — минута в минуту.
// Каждый день в 02:20 UTC (07:20 Ташкент) воркер нажимает «Run workflow» у ролика на GitHub — к 8:00 ролики готовы.
// Секретов в коде нет. В Cloudflare (Settings → Variables and Secrets) нужен один секрет:
//   GH_TOKEN — токен GitHub только для репозитория trai-video, право «Actions: Read and write».
// Расписание (Settings → Trigger events → Cron): 20 2 * * *
const REPO = 'arifazionsteyn-sketch/trai-video', WF = 'video.yml';
const gh = (env, path, init = {}) => fetch(`https://api.github.com/repos/${REPO}${path}`, {
  ...init, headers: { Authorization: `Bearer ${String(env.GH_TOKEN || '').trim()}`, Accept: 'application/vnd.github+json', 'User-Agent': 'trai-video-start', 'X-GitHub-Api-Version': '2022-11-28', ...(init.headers || {}) },
});

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      if (!env.GH_TOKEN) { console.log('Нет секрета GH_TOKEN'); return; }
      const r = await gh(env, `/actions/workflows/${WF}/dispatches`, { method: 'POST', body: JSON.stringify({ ref: 'main', inputs: { count: '2', langs: 'ru,en,uz', mode: 'story', daily: '1' } }) });
      console.log('запуск роликов:', r.status, r.status === 204 ? 'ок' : (await r.text()).slice(0, 300));
    })());
  },
  // Открыть адрес воркера в браузере — проверка, что токен работает: показывает последние запуски (ничего не запускает)
  async fetch(req, env) {
    if (!env.GH_TOKEN) return new Response('TRAI: нет секрета GH_TOKEN', { status: 500, headers: { 'content-type': 'text/plain; charset=utf-8' } });
    const r = await gh(env, `/actions/workflows/${WF}/runs?per_page=5`);
    if (!r.ok) return new Response(`TRAI: GitHub ответил ${r.status} — проверьте токен (доступ к trai-video, Actions: Read and write)`, { status: 502, headers: { 'content-type': 'text/plain; charset=utf-8' } });
    const j = await r.json(), tz = { timeZone: 'Asia/Tashkent', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' };
    const rows = (j.workflow_runs || []).map(x => `${new Date(x.created_at).toLocaleString('ru-RU', tz)} · ${x.event === 'workflow_dispatch' ? 'кнопка/будильник' : x.event === 'schedule' ? 'расписание GitHub' : 'изменение run.json'} · ${x.conclusion || x.status}`);
    return new Response('TRAI: будильник роликов на месте, токен работает.\nЗапуск каждый день в 07:20 по Ташкенту.\n\nПоследние запуски:\n' + rows.join('\n'), { headers: { 'content-type': 'text/plain; charset=utf-8' } });
  },
};
