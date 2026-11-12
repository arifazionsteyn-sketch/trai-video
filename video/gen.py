# TRAI — автоматические ролики: история рынка за неделю или тема про золото (Gemini с поиском Google) → сценарий RU/EN/UZ →
# голос Gemini (время слов — Whisper) → кадры (scene2.html для историй, scene.html для золота) → эффекты → сведение → Telegram.
#   python3 video/gen.py --count 2 --langs ru,en,uz            — истории рынка (по умолчанию --mode story)
#   python3 video/gen.py --mode gold --formats levels          — старые темы про золото
#   python3 video/gen.py --mock [--mode gold]                  — без сети: проверочный сценарий и тишина вместо голоса
# Ключи берутся из переменных окружения: GEMINI_SCRIPT_KEY, AZURE_SPEECH_KEY, AZURE_SPEECH_REGION, TG_BOT_TOKEN, TG_REVIEW_CHAT.
import argparse, datetime, json, os, re, subprocess, sys, time, urllib.parse, urllib.request, wave
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
OUTDIR = os.path.join(HERE, 'out')
HIST = os.path.join(HERE, 'history.json')
SR = 48000
LANGS_ALL = ['ru', 'en', 'uz']
VOICES = {'ru': os.environ.get('VOICE_RU', 'ru-RU-DmitryNeural'), 'en': os.environ.get('VOICE_EN', 'en-US-AndrewNeural'), 'uz': os.environ.get('VOICE_UZ', 'uz-UZ-SardorNeural')}
RATE = os.environ.get('VOICE_RATE', '+6%')
DISCLAIMER = {'ru': 'Не является финансовой рекомендацией', 'en': 'Not financial advice', 'uz': 'Moliyaviy maslahat emas'}
DISCLAIMER_SHORT = {'ru': 'Не финансовый совет', 'en': 'Not financial advice', 'uz': 'Moliyaviy maslahat emas'}
TAGLINE = {'ru': 'ИИ-агенты для торговли золотом', 'en': 'AI agents for gold trading', 'uz': 'Oltin savdosi uchun AI agentlar'}
FORMATS = {
    'levels': 'карта рынка золота на сегодня по данным TRAI: где скопилась ликвидность (стопы толпы выше и ниже цены), ключевые уровни поддержки и сопротивления, VWAP, дневной диапазон ATR — куда цене логичнее сходить и почему; конкретные цены',
    'news': 'ближайшее важное событие для золота из календаря TRAI (ФРС, CPI, NFP и т.п.) и как золото реагировало на такие события в прошлые разы — средний ход, направление, ловушки; плюс что сейчас говорят новости',
    'pattern': 'фигура или импульс на реальном графике золота прямо сейчас (по свечам TRAI): что это за фигура, где подтверждение, где стоп и цель, что ломает сценарий; если явной фигуры нет — разбор последнего импульса и откуда он пришёл (сбор ликвидности, пробой уровня)',
    'options': 'опционы на золото по данным TRAI: где стоят стены коллов и путов, уровень переключения гаммы, ожидаемый ход на день — как маркетмейкеры «держат» цену и где возможен резкий разгон',
    'hype': 'главная громкая новость последних дней из заголовков ниже (выборы, ФРС, войны, тарифы, крупные события) и как она уже повлияла на золото: что было с ценой, где сработали стопы, что говорят опционы и уровни TRAI; нейтрально, без политических оценок',
    'indicators': 'технический разбор по индикаторам TRAI прямо сейчас: RSI, EMA 50/200, тренд по таймфреймам, ATR, объём и VWAP — что они вместе говорят о следующем движении и где сценарий ломается',
    'fact': 'малоизвестный, но проверяемый факт о золоте, который меняет взгляд на рынок (центробанки, потоки денег, исторические аналогии с сегодняшней ситуацией по данным TRAI)',
}
MODELS = [m for m in os.environ.get('SCRIPT_MODELS', 'gemini-3.5-flash,gemini-flash-latest,gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-2.5-flash').split(',') if m]


def log(*a): print(*a, flush=True)


# ---------- Gemini ----------
def gemini(body, timeout=120):
    key = os.environ['GEMINI_SCRIPT_KEY']; last = None; errs = []
    for m in MODELS:
        for attempt in range(3):
            try:
                b2 = json.loads(json.dumps(body))
                if m.startswith('gemini-3'): b2.setdefault('generationConfig', {})['thinkingConfig'] = {'thinkingLevel': 'low'}
                req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}',
                                             data=json.dumps(b2).encode(), headers={'content-type': 'application/json'})
                with urllib.request.urlopen(req, timeout=timeout) as r: j = json.load(r)
                c = (j.get('candidates') or [{}])[0]
                txt = ''.join(p.get('text', '') for p in (c.get('content') or {}).get('parts', []) if not p.get('thought'))
                if c.get('finishReason') == 'MAX_TOKENS':
                    errs.append(f'{m}: ответ обрезан ({len(txt)} знаков)'); gc = body.setdefault('generationConfig', {}); gc['maxOutputTokens'] = min(65536, gc.get('maxOutputTokens', 8192) * 2); continue
                if txt.strip(): return txt, c, m
                last = f'{m}: пустой ответ {c.get("finishReason")}'
            except urllib.error.HTTPError as e:
                last = f'{m}: HTTP {e.code} {e.read()[:300]!r}'; errs.append(last[:160])
                if e.code in (400, 403, 404): break   # модель недоступна этому ключу — следующая
            except Exception as e:
                last = f'{m}: {e}'
            time.sleep(4 * (attempt + 1))
    raise RuntimeError('Gemini не ответил: ' + ' | '.join(e.split('\\n')[0] for e in errs[-8:]) if errs else str(last))


def gold_price():
    try:  # вечный контракт Gate XAU_USDT (тот же источник живой цены, что на сайте)
        with urllib.request.urlopen(urllib.request.Request('https://api.gateio.ws/api/v4/futures/usdt/tickers?contract=XAU_USDT', headers={'user-agent': 'trai-video'}), timeout=15) as r:
            p = float(json.load(r)[0]['last'])
        if p > 500: return p
    except Exception as e: log('цена Gate:', e)
    for u in ('https://trai-agent.com/api/data?part=tick', 'https://trai-xau-agent.vercel.app/api/data?part=tick'):
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={'user-agent': 'trai-video'}), timeout=15) as r: p = json.load(r).get('price')
            if p: return float(p)
        except Exception as e: log('цена с сайта:', u, e)
    return None


SITE = (os.environ.get('SITE_API') or 'https://trai-gold-git-dev-steyn1.vercel.app').rstrip('/')


def site(part, q=''):
    # данные сайта TRAI: ключ — HMAC токена бота (тот же расчёт в api/data.js), сам токен по сети не уходит
    import hashlib, hmac
    tok = os.environ.get('TG_BOT_TOKEN') or ''
    h = {'user-agent': 'trai-video', 'x-trai-video': hmac.new(tok.encode(), b'trai-video-v1', hashlib.sha256).hexdigest()} if tok else {'user-agent': 'trai-video'}
    try:
        with urllib.request.urlopen(urllib.request.Request(f'{SITE}/api/data?part={part}{q}', headers=h), timeout=60) as r: return json.load(r)
    except Exception as e:
        log('данные сайта', part, e); return None


def slim(o, depth=0):
    # для подсказки модели: без длинных массивов свечей, числа покороче
    if isinstance(o, dict): return {k: slim(v, depth + 1) for k, v in o.items() if k not in ('chart', 'spark', 'bars', 'vol', 'z', 'times', 'close', 'prices', 'strikes', 'profile', 'h1', 'm5', 'm15', 'vol5')}
    if isinstance(o, list): return [slim(v, depth + 1) for v in o[:12]]
    if isinstance(o, float): return round(o, 2)
    return o


DATA = {}


def load_data():
    if DATA: return DATA
    m = site('market'); DATA['market'] = m
    for k in ('calendar', 'evreact', 'news', 'gamma', 'macro'): DATA[k] = site(k)
    DATA['gamma_hist'] = site('gamma_hist', '&tf=1h')
    DATA['bars'] = (m or {}).get('chart', {}).get('h1') if m else None
    if not DATA['bars']:  # свечи с Gate, если сайт недоступен
        try:
            with urllib.request.urlopen(urllib.request.Request('https://api.gateio.ws/api/v4/futures/usdt/candlesticks?contract=XAU_USDT&interval=1h&limit=200', headers={'user-agent': 'trai-video'}), timeout=20) as r:
                DATA['bars'] = [[int(c['t']), float(c['o']), float(c['h']), float(c['l']), float(c['c'])] for c in json.load(r)]
        except Exception as e: log('свечи Gate:', e)
    return DATA


def rss(url, n=12):
    import xml.etree.ElementTree as ET
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={'user-agent': 'Mozilla/5.0 trai-video'}), timeout=20) as r: root = ET.fromstring(r.read())
        return [f"{(i.findtext('pubDate') or '')[:16]} · {i.findtext('title')}" for i in root.iter('item')][:n]
    except Exception as e:
        log('новости RSS:', e); return []


def web_brief():
    # Свежий интернет без ключей: Google News (заголовки за последние дни) + по ключам, если добавлены: YouTube (что набирает просмотры), Tavily (поиск)
    out = []
    for q, hl in (('gold price when:2d', 'en-US&gl=US&ceid=US:en'), ('XAUUSD OR "gold futures" when:2d', 'en-US&gl=US&ceid=US:en'), ('Fed OR inflation OR election markets when:2d', 'en-US&gl=US&ceid=US:en'), ('золото цена when:3d', 'ru&gl=RU&ceid=RU:ru')):
        items = rss('https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + '&hl=' + hl, 10)
        if items: out.append(f'— Google News «{q}»:\n' + '\n'.join(items))
    yk = os.environ.get('YOUTUBE_API_KEY')
    if yk:
        try:
            after = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=7)).strftime('%Y-%m-%dT%H:%M:%SZ'); vids = []
            for q in ('gold trading', 'XAUUSD', 'золото трейдинг'):
                u = 'https://www.googleapis.com/youtube/v3/search?' + urllib.parse.urlencode({'part': 'snippet', 'q': q + ' #shorts', 'type': 'video', 'videoDuration': 'short', 'order': 'viewCount', 'publishedAfter': after, 'maxResults': 8, 'key': yk})
                with urllib.request.urlopen(u, timeout=20) as r: vids += [i['snippet']['title'] for i in json.load(r).get('items', [])]
            if vids: out.append('— Самые просматриваемые Shorts про золото и трейдинг за неделю (YouTube):\n' + '\n'.join(dict.fromkeys(vids)))
        except Exception as e: log('YouTube:', e)
    tk = os.environ.get('TAVILY_API_KEY')
    if tk:
        try:
            req = urllib.request.Request('https://api.tavily.com/search', data=json.dumps({'api_key': tk, 'query': 'gold price news today drivers', 'topic': 'news', 'days': 2, 'max_results': 6}).encode(), headers={'content-type': 'application/json'})
            with urllib.request.urlopen(req, timeout=30) as r: res = json.load(r).get('results', [])
            if res: out.append('— Поиск по интернету (Tavily):\n' + '\n'.join(f"{x.get('title')}: {(x.get('content') or '')[:300]}" for x in res))
        except Exception as e: log('Tavily:', e)
    return '\n\n'.join(out)


def groq_search(fmt):
    # Groq Compound: модель сама ищет в интернете (бесплатный ключ) — свежие новости и цифры по теме ролика
    key = os.environ.get('GROQ_API_KEY')
    if not key: return ''
    q = (f'Today is {datetime.date.today().isoformat()}. Search the web and give a factual brief (in Russian) for a short video about gold (XAU/USD). '
         f'Topic type: {FORMATS[fmt]}. Include: the 5–8 most important fresh facts with exact numbers and dates, what moved gold in the last 3 days and why, '
         'the biggest market news people discuss right now, and which gold/trading topics are trending in Shorts/Reels/TikTok. Name the source for each fact.')
    for model in ('groq/compound', 'groq/compound-mini'):
        try:
            req = urllib.request.Request('https://api.groq.com/openai/v1/chat/completions', data=json.dumps({'model': model, 'messages': [{'role': 'user', 'content': q}], 'max_tokens': 2500}).encode(),
                                         headers={'content-type': 'application/json', 'authorization': 'Bearer ' + key, 'user-agent': 'trai-video'})
            with urllib.request.urlopen(req, timeout=120) as r: j = json.load(r)
            txt = j['choices'][0]['message'].get('content') or ''
            if txt.strip(): log(f'поиск Groq ({model}):', txt[:300].replace('\n', ' ')); return txt[:7000]
        except urllib.error.HTTPError as e: log('Groq:', model, e.code, e.read()[:200])
        except Exception as e: log('Groq:', model, e)
    return ''


# Какие данные и какие сцены подходят каждой теме: в одном ролике — одна линия, без мешанины (новости без гаммы и индикаторов)
TOPIC = {
    'levels': (('market',), 'hook, chart, big, percent, list, compare, ask'),
    'hype': (('news', 'calendar', 'evreact', 'macro'), 'hook, photo, bars, line, big, percent, list, chart (не больше одной), ask'),
    'news': (('calendar', 'evreact', 'news', 'macro'), 'hook, photo, bars, line, big, percent, list, ask'),
    'pattern': (('market',), 'hook, chart, pattern, list, percent, ask'),
    'indicators': (('market',), 'hook, chart, list, percent, big, ask'),
    'options': (('gamma', 'market'), 'hook, gamma3d, walls, chart, big, ask'),
    'fact': (('news', 'macro'), 'hook, photo, big, compare, percent, line, list, ask'),
}


def data_brief(fmt=None):
    d = load_data(); parts = []; keep = TOPIC.get(fmt, (None,))[0] if fmt else None
    for k, title in (('market', 'Рынок (цена, уровни, ликвидность, техника, профиль объёма, ATR)'), ('gamma', 'Опционы (стены, флип, ожидаемый ход)'), ('calendar', 'Календарь событий'),
                     ('evreact', 'Как золото реагировало на события раньше'), ('news', 'Новости'), ('macro', 'Межрынок')):
        if keep and k not in keep:
            if k == 'market' and d.get('market'): parts.append(f"### Текущая цена золота: {(d['market'] or {}).get('price')}")
            continue
        if d.get(k): parts.append(f'### {title}\n' + json.dumps(slim(d[k]), ensure_ascii=False)[:6000])
    b = d.get('bars') or []
    if b and (not keep or 'market' in keep): parts.append('### Последние часовые свечи (время, открытие, макс, мин, закрытие), 48 шт.\n' + json.dumps([[x[0], round(x[1], 1), round(x[2], 1), round(x[3], 1), round(x[4], 1)] for x in b[-48:]]))
    return '\n\n'.join(parts)


def research(fmt, recent):
    today = datetime.date.today().isoformat(); px = gold_price()
    prompt = (f'Сегодня {today}. Подбери ОДНУ тему для короткого вертикального ролика (30 секунд) аккаунта TRAI про золото (XAU/USD).\n'
              f'Формат: {FORMATS[fmt]}.\n'
              f'Не повторяй темы, которые уже были: {"; ".join(recent[-40:]) or "—"}.\n'
              + (f'Текущая цена золота (спот XAU/USD, данные TRAI на {today}): ${px:,.0f} за унцию — используй её для всех расчётов в долларах.\n' if px else '') +
              'Ниже — живые данные сайта TRAI (наши ИИ-агенты). Это главный источник: опирайся на них, цитируй точные цены и уровни.\n\n' + (data_brief(fmt) or '(данные сайта недоступны)') + '\n\n'
              'Свежие новости и что сейчас популярно в интернете:\n' + (web_brief() or '(нет)') + '\n\n'
              + (lambda g: ('Поиск по интернету (Groq, с источниками):\n' + g + '\n\n') if g else '')(groq_search(fmt)) +
              'Если доступен поиск Google — добавь свежие проверенные цифры и новости по теме. '
              'Тема должна цеплять с первой секунды: не банальщина, которую все знают, а глубокий разбор, как делают профессиональные трейдеры — ликвидность, поток, реакция на новости, конкретные цены. '
              'Ответь по-русски: 1) тема одной строкой; 2) 6–10 фактов с точными цифрами и датами, у каждого — источник (название сайта); '
              '3) текущая цена золота и дата. Только проверенные данные, без выдумок; если цифру не нашёл — не пиши её.')
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'tools': [{'google_search': {}}], 'generationConfig': {'temperature': 0.7, 'maxOutputTokens': 8000}}
    try: txt, cand, model = gemini(body)
    except Exception as e:  # поиск Google недоступен ключу — без поиска, но предупреждаем в подписи
        log('поиск Google не сработал:', e); body.pop('tools'); txt, cand, model = gemini(body); model += ' (без поиска — проверь цифры!)'
    src = []
    for ch in ((cand.get('groundingMetadata') or {}).get('groundingChunks') or []):
        w = ch.get('web') or {}
        if w.get('title') and w.get('title') not in src: src.append(w['title'])
    return txt, src[:8], model


TXT = lambda: {'type': 'STRING'}
LANG_TEXT = {'type': 'OBJECT', 'properties': {
    'say': TXT(), 'kicker': TXT(), 'title': TXT(), 'label': TXT(), 'prefix': TXT(), 'suffix': TXT(), 'sub': TXT(), 'source': TXT(), 'badge': TXT(),
    'a_label': TXT(), 'a_display': TXT(), 'b_label': TXT(), 'b_display': TXT(), 'mark_label': TXT(), 'start_label': TXT(), 'end_label': TXT(),
    'level_label': TXT(), 'cta': TXT(), 'calendar': TXT(), 'zone_label': TXT(), 'call_label': TXT(), 'put_label': TXT(), 'level_labels': {'type': 'ARRAY', 'items': TXT()},
    'items': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'properties': {'label': TXT(), 'display': TXT()}}},
    'list': {'type': 'ARRAY', 'items': TXT()}, 'options': {'type': 'ARRAY', 'items': TXT()}, 'keys': {'type': 'ARRAY', 'items': TXT()}},
    'required': ['say']}
SCHEMA = {'type': 'OBJECT', 'required': ['topic', 'scenes', 'post'], 'properties': {
    'topic': TXT(),
    'post': {'type': 'OBJECT', 'properties': {l: {'type': 'OBJECT', 'properties': {'caption': TXT(), 'hashtags': TXT()}} for l in LANGS_ALL}},
    'scenes': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'required': ['type', 'ru', 'en', 'uz'], 'properties': {
        'type': {'type': 'STRING', 'enum': ['hook', 'photo', 'chart', 'gamma3d', 'walls', 'big', 'compare', 'percent', 'bars', 'line', 'pattern', 'list', 'ask']},
        'levels': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}}, 'tones': {'type': 'ARRAY', 'items': {'type': 'STRING', 'enum': ['up', 'down', 'blue', 'gold', 'violet']}},
        'photo_query': {'type': 'STRING'}, 'zone': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}}, 'dir': {'type': 'STRING', 'enum': ['up', 'down', 'none']}, 'hours': {'type': 'INTEGER'},
        'art': {'type': 'STRING', 'enum': ['ingots', 'chart_up', 'chart_down', 'calendar', 'question']},
        'kind': {'type': 'STRING', 'enum': ['double_top', 'double_bottom', 'head_shoulders', 'inv_head_shoulders', 'triangle_asc', 'triangle_desc', 'bull_flag', 'bear_flag', 'breakout']},
        'value': {'type': 'NUMBER'}, 'decimals': {'type': 'INTEGER'}, 'pct': {'type': 'NUMBER'},
        'a_value': {'type': 'NUMBER'}, 'b_value': {'type': 'NUMBER'},
        'values': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}}, 'points': {'type': 'ARRAY', 'items': {'type': 'NUMBER'}}, 'mark': {'type': 'INTEGER'},
        'ru': LANG_TEXT, 'en': LANG_TEXT, 'uz': LANG_TEXT}}}}}

RULES = '''Ты сценарист вирусных коротких роликов (Reels, TikTok, Shorts) аккаунта TRAI — ИИ-агенты для торговли золотом.
Цель роликов — привлекать трейдеров: показывать то, чего нет у других (ликвидность, поток ордеров, опционы, реакция на новости, точные уровни),
как профессиональный аналитик, а не пересказ банальностей. Используй ТОЛЬКО цифры из фактов и данных TRAI, ничего не выдумывай.

Темп: 7–9 сцен, в каждой одна мысль и одно предложение диктора (6–11 слов, 3–4 секунды). Не перегружай: в ролике 4–6 цифр всего,
в одной фразе — не больше одной цифры. Лучше меньше фактов, но понятно и с выводом, чем много цифр подряд.
ОДНА ЛИНИЯ: ролик раскрывает одну тему от начала до конца. Ролик про новости — только новости, что предстоит, как рынок реагировал раньше
и что это значит для золота; не вставляй туда гамму, индикаторы и технический анализ. Ролик про опционы — про опционы, и т.д.
Разрешённые типы сцен для этой темы указаны ниже — используй только их.
Первая сцена — type "hook": цепляющий вопрос или сильное утверждение за 2–3 секунды (art по смыслу; для рынка сейчас — chart_up/chart_down).
Последняя — type "ask": НЕ вопрос, а призыв написать слово в комментариях. title — одно КОДОВОЕ слово по-английски заглавными, одинаковое во всех языках
(по умолчанию GOLD; можно слово темы ролика: FED, GAMMA, LEVELS, но короткое и из ролика); options — пустой список []; kicker — «Напиши в комментариях» на нужном языке;
cta — «и я пришлю подробный разбор» на нужном языке. say: «Напиши в комментариях GOLD — и я пришлю подробный разбор» (на нужном языке, кодовое слово — как в title).
Между ними — сцены-картинки:
- chart — НАСТОЯЩИЙ график золота (свечи подставятся сами): hours — сколько последних часов показать (24–96); levels — до 4 цен уровней из данных TRAI,
  tones — цвет каждого (up — поддержка, down — сопротивление, blue — ликвидность/стопы, gold — вход/VWAP, violet — опционы); level_labels — короткие подписи
  («Стопы покупателей», «Стена коллов», «VWAP»); zone — [низ, верх] зоны (например, куда цене логичнее сходить), zone_label; dir — куда стрелка (up/down/none).
  Используй chart 2–4 раза в роликах про рынок, уровни, опционы и фигуры — каждый раз с новым акцентом.
- photo — фотография по теме (здание ФРС, слитки, рудник, хранилище, нефтяная вышка, биржа, город, карта): photo_query — 2–4 английских слова для поиска
  на Wikimedia Commons, БЕЗ людей и лиц (не имена политиков и не «portrait»). Хорошо для новостей и фактов.
- gamma3d — 3D-поверхность гаммы опционов с сайта TRAI (данные подставятся сами), walls — стены опционов по страйкам (call_label/put_label — подписи стен,
  например «Стена коллов», «Стена путов»). Используй их, когда речь про опционы, гамму, маркетмейкеров.
- big (одно крупное число: value, decimals, prefix/suffix), compare (два столбика: a_value/b_value, a_label/a_display, b_label/b_display, badge «×18»),
  percent (кольцо: pct 0–100, label, sub), bars (2–5 полос: values + items label/display; можно отрицательные — реакция цены в % на прошлые события),
  line (points 8–20 чисел, mark — номер точки события, mark_label, start_label, end_label), pattern (схема фигуры: kind, level_label), list (2–4 пункта до 28 символов).

Тексты для каждого языка (ru, en, uz — узбекский латиницей):
- say — что говорит диктор в этой сцене: одно живое предложение, разговорно, с интригой, как блогер-трейдер. Числа цифрами («4 120», «3 раза», «1,8%»).
  Весь текст озвучки всех сцен вместе: русский 55–70 слов, английский 55–68, узбекский 45–58 — это 30–36 секунд спокойной речи. Не длиннее!
- kicker — маленькая подпись капсом над заголовком (до 32 символов), title — крупный заголовок (до 16 символов в строке, можно 2 строки через \\n).
- source — откуда цифры (например «данные TRAI, 08.11» или «World Gold Council, 2025»), пусто если цифр нет.
- keys — 1–2 главных слова из say для подсветки в субтитрах (точно как в say).
- для hook с art "calendar" — calendar: дата или короткая надпись (до 6 символов, например «12.11»).
Тему и подачу выбирай с оглядкой на то, что сейчас обсуждают и что набирает просмотры (новости и популярные ролики ниже в фактах) — цепляй хайп, но давай нашу глубину.
Все надписи (kicker, title, подписи) — на языке ролика: в русском ролике по-русски (не «SELL-STOP POOL», а «Стопы продавцов»), термины CVD/VWAP/ATR можно.
Цены в тексте — целыми числами без копеек («4 034», а не «4033.87»).
Без поучений и школьных фраз: никаких «помните», «запомните», «важно понимать», «друзья», «давайте разберём» — сразу суть, как сильный блогер-трейдер.
У каждой сцены обязательно заполни её данные: percent — pct (0–100), big — value, compare — a_value/b_value и a_display/b_display, bars — values и items, list — list, ask — options.
Политику освещай нейтрально: только влияние на рынок, без оценок партий и политиков.
Это не финансовый совет — не обещай прибыль, говори «сценарий», «вероятнее», «цель», «стоп».
Переводы — не дословные: естественно для носителя, те же цифры. Узбекский — современный, понятный молодёжи.
post — подпись к ролику для соцсетей на каждом языке (2–3 предложения + призыв зайти в бота @trai_agent_bot, без хэштегов) и hashtags (5–8 штук).'''


def make_script(facts, fmt):
    msg = RULES + f'\n\nФормат ролика: {FORMATS[fmt]}\nРазрешённые типы сцен: {TOPIC[fmt][1]}\n\nФакты:\n{facts}'
    gc = {'temperature': 0.8, 'maxOutputTokens': 16384, 'responseMimeType': 'application/json'}
    try: txt, _, model = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg}]}], 'generationConfig': {**gc, 'responseSchema': SCHEMA}}, timeout=180)
    except Exception as e:  # схему не приняли — та же структура описанием в запросе
        log('схема не принята:', e)
        txt, _, model = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg + '\n\nОтветь JSON строго по этой схеме:\n' + json.dumps(SCHEMA, ensure_ascii=False)}]}], 'generationConfig': gc}, timeout=180)
    txt = txt.strip().removeprefix('```json').removeprefix('```').removesuffix('```')
    sc = json.loads(txt)
    if not sc.get('scenes') or len(sc['scenes']) < 4: raise RuntimeError('слишком короткий сценарий')
    # Модель любит длинные фразы — проверяем и при необходимости просим сократить (ролик должен быть 30–40 с)
    for _ in range(2):
        wl = [len((x.get('ru') or {}).get('say', '').split()) for x in sc['scenes']]
        if sum(wl) <= 75 and max(wl) <= 12: break
        log(f'сценарий длинный ({sum(wl)} слов, самая длинная фраза {max(wl)}) — сокращаю')
        msg2 = ('Сократи этот сценарий: каждая фраза say — 6–11 слов на русском (английский и узбекский — так же коротко), весь русский текст 55–70 слов, не больше одной цифры во фразе. '
                'Сохрани смысл, цифры, интригу, типы сцен и все остальные поля без изменений. Верни тот же JSON.\n\n' + json.dumps(sc, ensure_ascii=False))
        try:
            t2, _, _ = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg2}]}], 'generationConfig': {**gc, 'responseSchema': SCHEMA}}, timeout=180)
            sc2 = json.loads(t2.strip().removeprefix('```json').removeprefix('```').removesuffix('```'))
            if len(sc2.get('scenes') or []) >= 4: sc = sc2
        except Exception as e: log('сократить не вышло:', e); break
    return sc, model


# ---------- Озвучка ElevenLabs (если есть ключ): живые голоса, время каждой буквы → время слов ----------
ELEVEN_VOICES = {'ru': os.environ.get('ELEVEN_VOICE_RU') or 'ws3YyKFd5whKb21yaXES', 'en': os.environ.get('ELEVEN_VOICE_EN') or '', 'uz': os.environ.get('ELEVEN_VOICE_UZ') or ''}
ELEVEN_MODEL = os.environ.get('ELEVEN_MODEL') or 'eleven_v3'


def tts_eleven(text, lang, path):
    import base64
    vid = ELEVEN_VOICES.get(lang) or ELEVEN_VOICES['ru']  # один голос на все языки, если свои не заданы — модель многоязычная
    body = {'text': text, 'model_id': ELEVEN_MODEL, 'language_code': lang}
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(f'https://api.elevenlabs.io/v1/text-to-speech/{vid}/with-timestamps?output_format=mp3_44100_128',
                                         data=json.dumps(body).encode(), headers={'content-type': 'application/json', 'xi-api-key': os.environ['ELEVENLABS_API_KEY']})
            with urllib.request.urlopen(req, timeout=120) as r: j = json.load(r)
            break
        except urllib.error.HTTPError as e:
            last = f'HTTP {e.code} {e.read()[:300]!r}'
            if e.code == 400 and 'language_code' in body: body.pop('language_code'); continue  # модель без выбора языка
            if e.code in (401, 402, 403): raise RuntimeError('ElevenLabs: ' + last)
            time.sleep(5 * (attempt + 1))
    else: raise RuntimeError('ElevenLabs: ' + str(last))
    mp3 = path[:-4] + '.mp3'; open(mp3, 'wb').write(base64.b64decode(j['audio_base64']))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', mp3, '-ar', str(SR), '-ac', '1', path], check=True)
    al = j.get('alignment') or j.get('normalized_alignment') or {}
    words, cur, st = [], '', None
    for ch, t0 in zip(al.get('characters', []), al.get('character_start_times_seconds', [])):
        if ch.isspace():
            if cur: words.append([cur, st]); cur = ''
        else:
            if not cur: st = t0
            cur += ch
    if cur: words.append([cur, st])
    return words


# ---------- Озвучка Gemini TTS (бесплатный ключ): весь текст одним куском, выразительно; время слов — Whisper ----------
TTS_MODELS = [m for m in (os.environ.get('TTS_MODELS') or 'gemini-3.8-flash-lite-tts,gemini-3.1-flash-tts-preview,gemini-2.5-flash-preview-tts').split(',') if m]
STYLE = {
    'ru': 'Ты рассказчик популярного канала о рынках. Говори по-русски низким, мужественным, уверенным голосом — спокойно, но живо, как будто рассказываешь другу интересную историю: с интонацией, без монотонности и без крика. Первую фразу — с лёгким напряжением, чтобы зацепить. Перед главной цифрой и на тире — короткая пауза, саму цифру — чуть выделить. Темп ровный, не тараторь. Очень чёткая дикция: каждое слово и каждую цифру произноси полностью, с первого звука. Между строками — пауза. Читай ТОЛЬКО текст пользователя, ничего не добавляй.',
    'en': 'You are the narrator of a popular markets channel. Speak English in a low, masculine, confident voice — calm but alive, like telling a friend a gripping story: natural intonation, never monotone, never shouting. Give the first line a touch of tension to hook the listener. Brief pause before key numbers and at dashes, and lean slightly on the number itself. Steady pace, never rushed. Crisp diction: pronounce every word fully from its first sound. Pause between lines. Read ONLY the user text, add nothing.',
    'uz': "Siz bozorlar haqidagi mashhur kanal hikoyachisisiz. O'zbek tilida past, erkakcha, ishonchli ovozda gapiring — xotirjam, lekin jonli, do'stingizga qiziqarli voqeani aytib berayotgandek: intonatsiya bilan, bir xil ohangda emas. Birinchi gapni biroz taranglik bilan ayting. Muhim raqamdan oldin va tire belgisida qisqa pauza qiling. Shoshilmang. Har bir so'zni birinchi tovushidan boshlab aniq talaffuz qiling. Satrlar orasida pauza. FAQAT foydalanuvchi matnini o'qing, hech narsa qo'shmang.",
}


# Один и тот же голос на каждый язык во всех роликах (поменять — переменные GEMINI_VOICE_RU / _EN / _UZ в GitHub)
# Голоса выбраны по роликам (одно и то же имя голоса на разных моделях звучит по-разному, поэтому закреплена и модель):
# en — Algenib на gemini-3.1-flash-tts-preview (ролик «H4 up vs D1 down»), uz — Fenrir на gemini-3.8-flash-lite-tts (ролик 07.11 22:24),
# ru — Fenrir на gemini-3.8-flash-lite-tts (не запинается), манера — спокойнее, как у английского
VOICE_DEFAULT = {'ru': 'Fenrir', 'en': 'Algenib', 'uz': 'Fenrir'}
MODEL_DEFAULT = {'ru': 'gemini-3.8-flash-lite-tts', 'en': 'gemini-3.1-flash-tts-preview', 'uz': 'gemini-3.8-flash-lite-tts'}


def tts_gemini_whole(lines, lang, path):
    import base64
    key = os.environ['GEMINI_SCRIPT_KEY']; voice = os.environ.get('GEMINI_VOICE_' + lang.upper()) or os.environ.get('GEMINI_VOICE') or VOICE_DEFAULT[lang]; errs = []
    text = '\n'.join(lines)
    first = MODEL_DEFAULT.get(lang); models = ([first] if first else []) + [x for x in TTS_MODELS if x != first]
    for m in models:
        noinst = False
        # основную модель пробуем дольше (у запасных другой тембр — голос не должен «гулять» от ролика к ролику)
        for attempt in range(5 if m == models[0] else 2):
            try:
                body = {'contents': [{'role': 'user', 'parts': [{'text': text}]}],
                        'generationConfig': {'responseModalities': ['AUDIO'], 'speechConfig': {'voiceConfig': {'prebuiltVoiceConfig': {'voiceName': voice}}}}}
                if not noinst: body['systemInstruction'] = {'parts': [{'text': STYLE[lang]}]}  # манера речи — инструкцией, а не текстом для чтения
                req = urllib.request.Request(f'https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}', data=json.dumps(body).encode(), headers={'content-type': 'application/json'})
                with urllib.request.urlopen(req, timeout=240) as r: j = json.load(r)
                part = next(p for p in j['candidates'][0]['content']['parts'] if p.get('inlineData'))
                mime, raw = part['inlineData'].get('mimeType', ''), base64.b64decode(part['inlineData']['data'])
                rate = int((re.search(r'rate=(\d+)', mime) or [0, 24000])[1])
                a = np.frombuffer(raw, '<i2').astype(float) / 32768
                a = np.interp(np.arange(int(len(a) * SR / rate)) / SR, np.arange(len(a)) / rate, a)
                with wave.open(path, 'wb') as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(a, -1, 1) * 32767).astype('<i2').tobytes())
                log(f'голос Gemini {m} · {voice} · {len(a) / SR:.1f} с'); return
            except urllib.error.HTTPError as e:
                errs.append(f'{m}: HTTP {e.code} {e.read()[:160]!r}'.split('\\n')[0])
                if e.code == 400 and not noinst: noinst = True; continue  # модель без системной инструкции — повтор без неё
                if e.code in (400, 403, 404): break
                time.sleep(min(60, 10 * (attempt + 1)))
            except Exception as e:
                errs.append(f'{m}: {e}'); time.sleep(3)
    raise RuntimeError('Gemini TTS: ' + ' | '.join(errs[-4:]))


_WH = None


def whisper_words(path, lang):
    global _WH
    from faster_whisper import WhisperModel
    if _WH is None: _WH = WhisperModel(os.environ.get('WHISPER_MODEL') or 'small', device='cpu', compute_type='int8')
    a = read_wav(path); a16 = np.interp(np.arange(int(len(a) * 16000 / SR)) / 16000, np.arange(len(a)) / SR, a).astype(np.float32)  # без PyAV
    segs, _ = _WH.transcribe(a16, language=lang, word_timestamps=True, vad_filter=False, beam_size=1)
    ws = [[w.word.strip(), w.start, w.end] for sg in segs for w in (sg.words or []) if w.word.strip()]
    whisper_words.last_end = ws[-1][2] if ws else None
    return [[w, st] for w, st, _ in ws]


def align_text(tokens, heard, total):
    # слова сценария ↔ слова, которые распознал Whisper: совпавшие получают точное время, остальные — между соседями
    import difflib
    A, B = [norm(t) for t in tokens], [norm(w) for w, _ in heard]
    times = [None] * len(tokens)
    for blk in difflib.SequenceMatcher(None, A, B, autojunk=False).get_matching_blocks():
        for k in range(blk.size): times[blk.a + k] = heard[blk.b + k][1]
    known = [(i, t) for i, t in enumerate(times) if t is not None]
    if not known: return [k * total / max(1, len(tokens)) for k in range(len(tokens))]
    for i in range(len(tokens)):
        if times[i] is not None: continue
        prev = max((k for k in known if k[0] < i), default=None, key=lambda k: k[0]); nxt = min((k for k in known if k[0] > i), default=None, key=lambda k: k[0])
        if prev and nxt: times[i] = prev[1] + (nxt[1] - prev[1]) * (i - prev[0]) / (nxt[0] - prev[0])
        elif prev: times[i] = min(total - 0.2, prev[1] + 0.3 * (i - prev[0]))
        else: times[i] = max(0.0, nxt[1] - 0.3 * (nxt[0] - i))
    for i in range(1, len(times)): times[i] = max(times[i], times[i - 1] + 0.05)
    return times


# ---------- Озвучка Azure: каждая сцена отдельно, время каждого слова ----------
def tts(text, lang, path):
    if os.environ.get('ELEVENLABS_API_KEY'): return tts_eleven(text, lang, path)
    import azure.cognitiveservices.speech as speechsdk
    cfg = speechsdk.SpeechConfig(subscription=os.environ['AZURE_SPEECH_KEY'], region=os.environ['AZURE_SPEECH_REGION'])
    cfg.set_speech_synthesis_output_format(speechsdk.SpeechSynthesisOutputFormat.Riff48Khz16BitMonoPcm)
    cfg.set_property(speechsdk.PropertyId.SpeechServiceResponse_RequestWordBoundary, 'true')
    synth = speechsdk.SpeechSynthesizer(speech_config=cfg, audio_config=None)  # звук забираем из ответа и пишем сами
    words = []

    def wb(e):
        if str(e.boundary_type).endswith('Word'): words.append([e.text, e.audio_offset / 1e7])
    synth.synthesis_word_boundary.connect(wb)
    loc = {'ru': 'ru-RU', 'en': 'en-US', 'uz': 'uz-UZ'}[lang]
    esc = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    ssml = f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="{loc}"><voice name="{VOICES[lang]}"><prosody rate="{RATE}">{esc}</prosody></voice></speak>'
    r = synth.speak_ssml_async(ssml).get()
    if r.reason != speechsdk.ResultReason.SynthesizingAudioCompleted:
        det = speechsdk.SpeechSynthesisCancellationDetails(r) if r.reason == speechsdk.ResultReason.Canceled else None
        raise RuntimeError(f'Azure: {r.reason} {det.error_details if det else ""}')
    open(path, 'wb').write(r.audio_data)
    return words


def read_wav(path):
    w = wave.open(path); a = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(float) / 32768
    if w.getnchannels() == 2: a = a.reshape(-1, 2).mean(1)
    if w.getframerate() != SR: a = np.interp(np.arange(int(len(a) * SR / w.getframerate())) / SR, np.arange(len(a)) / w.getframerate(), a)
    return a


def trim(a, pre=0.18, post=0.12):
    # тишина в начале и в конце — убираем, но с запасом: тихие первые звуки («с», «ф», «х», «п») не должны срезаться
    if not len(a): return a, 0.0
    pk = float(np.abs(a).max())
    if pk <= 0: return a, 0.0
    env = np.convolve(np.abs(a), np.ones(240) / 240, 'same')  # огибающая 5 мс
    idx = np.where(env > max(0.003, pk * 0.02))[0]
    if not len(idx): return a, 0.0
    i0 = max(0, idx[0] - int(pre * SR)); i1 = min(len(a), idx[-1] + int(post * SR))
    b = a[i0:i1].copy(); n = min(len(b), int(0.01 * SR)); b[:n] *= np.linspace(0, 1, n)  # мягкое начало только по тишине перед речью
    return b, i0 / SR


norm = lambda s: re.sub(r'[^\w%$]+', '', s.lower().replace('ё', 'е'))


def safe_cut(a, first, heard):
    # Модель иногда читает лишнее перед текстом. Режем, только если Whisper услышал слова раньше первого слова сценария
    # и между ними есть тишина; режем в самой тихой точке, а не «за 0,12 с до слова» (так раньше срезался первый слог).
    if first < 0.6 or not any(st < first - 0.4 for _, st in heard): return 0.0
    lo, hi = int(max(0.0, first - 0.9) * SR), int(max(0.0, first - 0.08) * SR)
    seg_ = a[lo:hi]
    if len(seg_) < 1200: return 0.0
    e = np.sqrt(np.convolve(seg_ ** 2, np.ones(960) / 960, 'valid')); k = int(np.argmin(e))
    speech = a[int(first * SR):int((first + 1.5) * SR)]
    if not len(speech) or e[k] > 0.25 * float(np.sqrt(np.mean(speech ** 2)) + 1e-9): return 0.0  # тишины нет — не трогаем
    return (lo + k + 480) / SR


def words_of(say):
    # слова фразы; «4 128», «220 000» — одно слово (группы цифр по три)
    out = []
    for w in say.split():
        if out and not re.search(r'\w', w): out[-1] += ' ' + w  # «—» к предыдущему слову
        elif out and re.fullmatch(r'\d{3}([.,]\d+)?[%$.,!?:;]*', w) and re.fullmatch(r'[$€]?\d{1,3}', out[-1]): out[-1] += ' ' + w
        else: out.append(w)
    return out


def align(say, words):
    # время слов от Azure + слова из текста с пунктуацией («золото,» «тонн.»). Число «220 000» Azure может прислать
    # словами («двести двадцать тысяч») — тогда в субтитрах остаются цифры с временем первого слова, лишние слова пропускаем.
    toks = say.split(); out = []; ti = 0; in_num = False
    for wd, t in words:
        nw = norm(wd)
        if not nw: continue
        while ti < len(toks) and not norm(toks[ti]):  # «—» и подобное — к предыдущему слову
            if out: out[-1][0] += ' ' + toks[ti]
            ti += 1
        if ti < len(toks):
            acc, j = '', ti
            while j < len(toks) and len(norm(acc)) < len(nw): acc = (acc + ' ' + toks[j]).strip(); j += 1
            if norm(acc) == nw: out.append([acc, t]); ti = j; in_num = False; continue
            if re.search(r'\d', toks[ti]):  # число цифрами в тексте, словами в озвучке
                j = ti + 1
                while j < len(toks) and re.fullmatch(r'[\d.,]+[%.,!?]*', toks[j]) and not re.search(r'[.!?]$', toks[j - 1]): j += 1
                out.append([' '.join(toks[ti:j]), t]); ti = j; in_num = True; continue
        if in_num: continue
        out.append([wd, t])
    return out


def chunks(words, keys):
    # субтитры кусками по 2–4 слова: разрыв после знака препинания, паузы или на 3-м слове
    keyset = {norm(k) for ks in keys for k in ks.split()} if keys else set()
    res, cur = [], []
    for i, (wd, t) in enumerate(words):
        cur.append([wd, round(t, 3)])
        nxt = words[i + 1][1] if i + 1 < len(words) else None
        brk = bool(re.search(r'[.,!?:;—…]$', wd)) or len(cur) >= 3 or (nxt is not None and nxt - t > 0.7)
        if len(cur) >= 4 or (brk and (len(cur) >= 2 or nxt is None or nxt - t > 0.5 or re.search(r'[.!?]$', wd))) or nxt is None:
            k = next((j for j, (w, _) in enumerate(cur) if norm(w) in keyset), None)
            if k is None: k = next((j for j, (w, _) in enumerate(cur) if re.search(r'\d', w)), -1)
            res.append({'w': cur, 'key': k}); cur = []
    return res


def _num_in(t):
    for k in ('title', 'say', 'kicker', 'label', 'sub'):
        m_ = re.search(r'(-?\d[\d  ]*(?:[.,]\d+)?)\s*%', str(t.get(k) or ''))
        if m_: return float(m_.group(1).replace(' ', '').replace(' ', '').replace(',', '.')), True
    for k in ('title', 'say'):
        m_ = re.search(r'\$?(\d[\d  ]*(?:[.,]\d+)?)', str(t.get(k) or ''))
        if m_: return float(m_.group(1).replace(' ', '').replace(' ', '').replace(',', '.')), False
    return None, False


def fix_scene(s, L):
    # модель иногда забывает данные сцены — достаём число из текста или превращаем в сцену-картинку, чтобы кадр не был пустым
    t = s[L]; ty = s['type']; v, pc = _num_in(t)
    if ty == 'percent':
        p_ = s.get('pct')
        if p_ is not None and 0 < p_ <= 1: s['pct'] = p_ * 100
        if not s.get('pct'):
            if v is not None and pc: s['pct'] = v
            else: s['type'] = 'hook'; s.setdefault('art', 'chart_up')
    elif ty == 'big' and s.get('value') is None:
        if v is not None: s['value'] = v; s.setdefault('decimals', 0 if float(v).is_integer() else 1); t.setdefault('suffix', '%' if pc else '')
        else: s['type'] = 'hook'; s.setdefault('art', 'chart_up')
    elif ty == 'compare' and (s.get('a_value') is None or s.get('b_value') is None): s['type'] = 'hook'; s.setdefault('art', 'chart_up')
    elif ty == 'bars' and not (s.get('values') and t.get('items')): s['type'] = 'hook'; s.setdefault('art', 'chart_up')
    elif ty == 'list' and not t.get('list'): s['type'] = 'hook'; s.setdefault('art', 'question')
    elif ty == 'line' and len(s.get('points') or []) < 3: s['type'] = 'chart' if load_data().get('bars') else 'hook'; s.setdefault('hours', 48)
    elif ty == 'ask':  # концовка — кодовое слово в комментарии, без вариантов ответа
        t['options'] = []; t['title'] = re.sub(r'[^A-Z0-9]', '', str(t.get('title') or '').upper()) or 'GOLD'
        t.setdefault('kicker', {'ru': 'Напиши в комментариях', 'en': 'Comment the word', 'uz': 'Izohga yozing'}[L]); t.setdefault('cta', {'ru': 'и я пришлю подробный разбор', 'en': 'and I’ll send you the full breakdown', 'uz': 'va men batafsil tahlilni yuboraman'}[L])
    if s['type'] == 'hook' and s.get('art') == 'chart_up' and load_data().get('bars'): s['type'] = 'chart'; s.setdefault('hours', 48)


PHOTOS = {}


def commons_photo(q, work):
    if q in PHOTOS: return PHOTOS[q]
    try:
        u = 'https://commons.wikimedia.org/w/api.php?' + urllib.parse.urlencode({'action': 'query', 'format': 'json', 'generator': 'search', 'gsrsearch': f'filetype:bitmap {q}', 'gsrnamespace': 6, 'gsrlimit': 15,
                                                                               'prop': 'imageinfo', 'iiprop': 'url|extmetadata|size', 'iiurlwidth': 1400})
        with urllib.request.urlopen(urllib.request.Request(u, headers={'user-agent': 'TRAI-video/1.0 (trai-agent.com)'}), timeout=30) as r: pages = (json.load(r).get('query') or {}).get('pages') or {}
        for pg in sorted(pages.values(), key=lambda p_: p_.get('index', 99)):
            ii = (pg.get('imageinfo') or [{}])[0]; md = ii.get('extmetadata') or {}
            lic = (md.get('LicenseShortName') or {}).get('value', ''); desc = re.sub('<[^>]+>', '', (md.get('ImageDescription') or {}).get('value', '')).lower()
            if not re.search(r'cc0|public domain|cc by', lic, re.I) or re.search(r'portrait|headshot|selfie', desc) or ii.get('width', 0) < 900: continue
            path = os.path.join(work, 'ph_' + re.sub(r'\W+', '_', q)[:30] + '.jpg')
            with urllib.request.urlopen(urllib.request.Request(ii['thumburl'], headers={'user-agent': 'TRAI-video/1.0 (trai-agent.com)'}), timeout=60) as r: open(path, 'wb').write(r.read())
            artist = re.sub('<[^>]+>', '', (md.get('Artist') or {}).get('value', '')).strip()[:40]
            PHOTOS[q] = {'src': 'file://' + path, 'credit': f'Фото: {artist + " / " if artist else ""}Wikimedia Commons, {lic}'}
            return PHOTOS[q]
    except Exception as e: log('фото:', q, e)
    PHOTOS[q] = None; return None


def scene_data(s, L, work=None):
    fix_scene(s, L)
    if s['type'] == 'photo':
        ph = commons_photo(s.get('photo_query') or 'gold bars', work or OUTDIR) if s.get('photo_query') or True else None
        if ph: s['_photo'] = ph
        else: s['type'] = 'chart' if load_data().get('bars') else 'hook'; s.setdefault('art', 'ingots'); s.setdefault('hours', 48)
    t = s[L]; d = {k: v for k, v in t.items() if k not in ('say', 'keys', 'items', 'list', 'a_label', 'a_display', 'b_label', 'b_display', 'calendar')}
    d['type'] = s['type']
    for k in ('art', 'kind', 'value', 'decimals', 'pct', 'points', 'mark'):
        if s.get(k) is not None: d[k] = s[k]
    if s['type'] == 'compare':
        d['a'] = {'label': t.get('a_label', ''), 'display': t.get('a_display', ''), 'value': s.get('a_value', 1)}
        d['b'] = {'label': t.get('b_label', ''), 'display': t.get('b_display', ''), 'value': s.get('b_value', 1)}
    if s['type'] == 'bars':
        vals = s.get('values') or []
        d['items'] = [{'label': it.get('label', ''), 'display': it.get('display', ''), 'value': vals[i] if i < len(vals) else 0} for i, it in enumerate(t.get('items') or [])]
    if s['type'] == 'list': d['items'] = t.get('list') or []
    if s['type'] == 'hook': d['label'] = t.get('calendar', '')
    if s['type'] == 'ask': d['options'] = t.get('options') or []
    if s['type'] == 'photo': d['img'] = s['_photo']['src']; d['credit'] = s['_photo']['credit'].replace('Фото:', {'ru': 'Фото:', 'en': 'Photo:', 'uz': 'Foto:'}[L])
    if s['type'] == 'chart':
        bars = (load_data().get('bars') or [])[-max(12, min(160, int(s.get('hours') or 48))):]
        d['bars'] = [[round(b[1], 2), round(b[2], 2), round(b[3], 2), round(b[4], 2)] for b in bars]
        lv, tn, lb = s.get('levels') or [], s.get('tones') or [], t.get('level_labels') or []
        d['levels'] = [{'price': v, 'tone': tn[i] if i < len(tn) else 'gold', 'label': lb[i] if i < len(lb) else ''} for i, v in enumerate(lv[:4])]
        if s.get('zone') and len(s['zone']) == 2: d['zone'] = {'lo': min(s['zone']), 'hi': max(s['zone']), 'label': t.get('zone_label', '')}
        d['dir'] = s.get('dir') or 'none'
        if not d['bars']: d['type'] = 'big'  # свечей нет — хотя бы крупное число
    if s['type'] in ('gamma3d', 'walls'):
        D = load_data(); g, gh = D.get('gamma') or {}, D.get('gamma_hist') or {}
        if s['type'] == 'gamma3d' and gh.get('z'): d['g'] = {'z': gh['z'][-72:], 'prices': gh['prices'], 'price': gh.get('price') or g.get('xau')}
        elif s['type'] == 'walls' and g.get('strikes'): d['g'] = {'strikes': g['strikes'], 'price': g.get('xau'), 'call_wall': g.get('call_wall'), 'put_wall': g.get('put_wall')}; d['labels'] = {'call': t.get('call_label') or '', 'put': t.get('put_label') or ''}
        else: d['type'] = 'big' if s.get('value') is not None else 'list'
    return d


# ================= Истории рынка (v2): любой рынок за неделю, история с началом и концом, сцены scene2.html =================
CATS = {'crypto': 'криптовалюты (биткоин, эфир, крипто-компании, биржевые фонды на крипту)',
        'stocks': 'акции компаний (резкие движения из-за отчётов, скандалов, сделок, смены CEO, ИИ, судов)',
        'commodities': 'сырьё (нефть, газ, серебро, медь, золото, зерно)',
        'macro': 'макро и индексы (ФРС, инфляция, рынок труда, облигации, S&P 500, Nasdaq)',
        'fx': 'валюты (доллар, евро, иена, юань)'}
CAT_ORDER = ['stocks', 'crypto', 'commodities', 'stocks', 'macro', 'crypto', 'fx', 'commodities']


def story_brief():
    # заголовки за неделю — подсказка, о чём сейчас говорит рынок (сами факты модель берёт из поиска Google)
    out = []
    for q, hl in (('stock plunges OR soars OR tumbles when:7d', 'en-US&gl=US&ceid=US:en'), ('shares CEO OR earnings OR lawsuit when:7d', 'en-US&gl=US&ceid=US:en'),
                  ('bitcoin OR crypto OR ether when:7d', 'en-US&gl=US&ceid=US:en'), ('oil OR silver OR copper OR gold prices when:7d', 'en-US&gl=US&ceid=US:en'),
                  ('Fed OR inflation OR "jobs report" OR treasury yields when:7d', 'en-US&gl=US&ceid=US:en'), ('акции рухнули OR взлетели when:7d', 'ru&gl=RU&ceid=RU:ru')):
        items = rss('https://news.google.com/rss/search?q=' + urllib.parse.quote(q) + '&hl=' + hl, 12)
        if items: out.append(f'— Google News «{q}»:\n' + '\n'.join(items))
    return '\n\n'.join(out)


def research_story(hist, avoid_cats):
    today = datetime.date.today().isoformat()
    recent = [f"{h.get('topic')} [{h.get('asset', '')}]" for h in hist[-30:]]
    cats = [c for c in CATS if c not in avoid_cats] or list(CATS)
    prompt = (f'Сегодня {today}. Найди поиском Google самые обсуждаемые истории на финансовых рынках за последние 7 дней и выбери ОДНУ — '
              'для короткого вертикального ролика (45 секунд). Нужна история с сильным крючком, точными цифрами и понятной цепочкой «что случилось → почему → что дальше»: '
              'резкий обвал или взлёт акции (отчёт, скандал, смена CEO, сделка, суд), движение биткоина или крипто-компаний, нефть, серебро, решения ФРС, инфляция, валюты.\n'
              f'Категория — одна из: {"; ".join(f"{c} — {CATS[c]}" for c in cats)}.\n'
              f'Не повторяй истории и активы прошлых роликов: {"; ".join(recent) or "—"}.\n\n'
              'Заголовки последней недели (для ориентира, факты проверь поиском):\n' + (story_brief() or '(нет)') + '\n\n'
              'Ответь по-русски строго по пунктам:\n'
              '1) КАТЕГОРИЯ: одно слово из списка (crypto, stocks, commodities, macro, fx)\n'
              '2) АКТИВ: название и тикер Yahoo Finance (например NVDA, TSLA, BTC-USD, ETH-USD, CL=F, BZ=F, GC=F, SI=F, HG=F, EURUSD=X, JPY=X, ^GSPC, ^IXIC, DX-Y.NYB); '
              'до 3 связанных тикеров, если они помогают истории\n'
              '3) ИСТОРИЯ: заголовок одной строкой\n'
              '4) ДАТЫ: дата главного события (ГГГГ-ММ-ДД) и других важных моментов\n'
              '5) ФАКТЫ: 8–12 фактов с точными цифрами (цены, проценты, суммы) и датами; у каждого — издание-источник\n'
              '6) ЦЕПОЧКА: почему это случилось — 2–4 звена «причина → следствие», только из фактов\n'
              '7) ПОВОРОТ: неочевидная деталь, которую большинство упускает (подтверждённая фактами)\n'
              '8) ЧТО ДАЛЬШЕ: ближайшие даты, события и уровни цены, за которыми следит рынок\n'
              'Правила: только проверенные факты из найденных источников; о людях и компаниях — только то, что сообщили издания, с указанием издания; '
              'никого не называй виновным; если цифру не нашёл — не пиши её.')
    body = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}], 'tools': [{'google_search': {}}], 'generationConfig': {'temperature': 0.8, 'maxOutputTokens': 8000}}
    try: txt, cand, model = gemini(body)
    except Exception as e:
        log('поиск Google не сработал:', e); body.pop('tools'); txt, cand, model = gemini(body); model += ' (без поиска — проверь цифры!)'
    src = []
    for ch in ((cand.get('groundingMetadata') or {}).get('groundingChunks') or []):
        w = ch.get('web') or {}
        if w.get('title') and w.get('title') not in src: src.append(w['title'])
    m = re.search(r'КАТЕГОРИЯ:\s*\**\s*([a-z]+)', txt)
    return txt, src[:8], model, (m.group(1) if m and m.group(1) in CATS else '')


TONE = {'type': 'STRING', 'enum': ['up', 'down', 'gold', 'blue']}
NUM = {'type': 'NUMBER'}
LT2 = {'type': 'OBJECT', 'properties': {
    'say': TXT(), 'kicker': TXT(), 'title': TXT(), 'accent': TXT(), 'label': TXT(), 'prefix': TXT(), 'suffix': TXT(), 'source': TXT(), 'mark_label': TXT(),
    'badge': TXT(), 'a_label': TXT(), 'a_display': TXT(), 'b_label': TXT(), 'b_display': TXT(), 'date': TXT(), 'text': TXT(), 'highlight': TXT(), 'cta': TXT(),
    'level_labels': {'type': 'ARRAY', 'items': TXT()}, 'names': {'type': 'ARRAY', 'items': TXT()}, 'list': {'type': 'ARRAY', 'items': TXT()},
    'items': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'properties': {'label': TXT(), 'sub': TXT(), 'display': TXT(), 'date': TXT()}}},
    'beats': {'type': 'ARRAY', 'items': TXT()}, 'keys': {'type': 'ARRAY', 'items': TXT()}},
    'required': ['say', 'beats']}
SCHEMA2 = {'type': 'OBJECT', 'required': ['topic', 'category', 'asset', 'scenes', 'post'], 'properties': {
    'topic': TXT(), 'category': {'type': 'STRING', 'enum': list(CATS)}, 'asset': TXT(),
    'post': {'type': 'OBJECT', 'properties': {l: {'type': 'OBJECT', 'properties': {'caption': TXT(), 'hashtags': TXT()}} for l in LANGS_ALL}},
    'scenes': {'type': 'ARRAY', 'items': {'type': 'OBJECT', 'required': ['type', 'ru', 'en', 'uz'], 'properties': {
        'type': {'type': 'STRING', 'enum': ['hook', 'candles', 'headline', 'chain', 'counter', 'versus', 'grid', 'ring', 'bars', 'timeline', 'ticker', 'checklist', 'cta']},
        'symbol': TXT(), 'range': {'type': 'STRING', 'enum': ['5d', '1mo', '3mo', '6mo', '1y']}, 'interval': {'type': 'STRING', 'enum': ['1h', '1d', '1wk']},
        'mark_date': TXT(), 'levels': {'type': 'ARRAY', 'items': NUM}, 'level_tones': {'type': 'ARRAY', 'items': TONE},
        'value': NUM, 'from': NUM, 'decimals': {'type': 'INTEGER'}, 'tone': TONE, 'dir': {'type': 'STRING', 'enum': ['up', 'down', 'none']},
        'a_value': NUM, 'b_value': NUM, 'a_tone': TONE, 'b_tone': TONE, 'total': {'type': 'INTEGER'}, 'count': {'type': 'INTEGER'}, 'pct': NUM,
        'values': {'type': 'ARRAY', 'items': NUM}, 'symbols': {'type': 'ARRAY', 'items': TXT()}, 'source_name': TXT(), 'ref_value': NUM,
        'ru': LT2, 'en': LT2, 'uz': LT2}}}}}

RULES2 = '''Ты сценарист и режиссёр коротких вертикальных роликов (Shorts, Reels, TikTok) аккаунта TRAI о рынках.
Стиль — строгий, «данные на экране»: тёмный фон, настоящие графики, крупные числа, без персонажей. Каждый ролик — законченная ИСТОРИЯ с началом и концом.

СТРУКТУРА (7–9 сцен, 40–50 секунд):
1. hook — крючок за 2–3 секунды: самое сильное число или факт. Утверждение, от которого хочется досмотреть (не «знаете ли вы»).
2. Что случилось — candles (настоящий график актива с отметкой события) и/или headline (новость: издание, дата, суть своими словами).
3–5. Почему — chain (2–4 звена «причина → следствие»), counter / versus / bars / grid / ring / timeline с ключевыми цифрами.
6. Поворот — то, что большинство упускает (неочевидная деталь, уровень, сравнение с прошлым), начинай с «Но…» / «А вот…».
7. Что дальше — checklist (2–3 конкретных сигнала: даты, уровни, события) или timeline.
8. cta — призыв написать кодовое слово в комментариях.
Каждая сцена отвечает на вопрос, который оставила предыдущая: «что → почему → но → что дальше». Без повторов одной мысли.
Подряд не ставь два одинаковых типа сцен. candles — 1–2 раза, chain — 1 раз.

СЦЕНЫ И ИХ ДАННЫЕ (поля сцены — общие для всех языков, тексты — в ru/en/uz):
- hook: value (главное число, необязательно), from (было, если число «было → стало»), decimals, dir (up/down/none), symbol (тикер для фоновой линии);
  тексты: kicker, title, accent, label (подпись под числом), prefix/suffix числа («$», «%», « млрд $»).
- candles: symbol (тикер Yahoo Finance), range (5d/1mo/3mo/6mo/1y), interval (1h для 5d, 1d для 1mo–6mo, 1wk для 1y), mark_date (ГГГГ-ММ-ДД события),
  levels (до 3 цен), level_tones (up — поддержка, down — сопротивление, gold — важный уровень, blue — средняя/ориентир);
  тексты: kicker, mark_label (2–3 слова: «отчёт», «отставка CEO»), level_labels, source. Свечи и процент изменения подставятся сами из реальных данных.
- headline: source_name (издание), tone; тексты: date («9 ноя»), text (суть новости своими словами, до 14 слов, не копируй заголовок), highlight (2–4 слова из text для маркера).
- chain: тексты items — 2–4 звена {label (до 22 символов), sub (цифра/уточнение до 34 символов)}.
- counter: value, from (необязательно — «было → стало» с перечёркиванием), decimals, tone, ref_value (необязательно — текущая цена, если value — уровень: покажем шкалу «сейчас → уровень»);
  тексты: kicker, title, accent, label, prefix, suffix, source.
- versus: a_value, b_value, a_tone, b_tone; тексты: kicker, title, accent, a_label, a_display, b_label, b_display, badge («×3», «−40%»).
- grid: total (4–20), count (сколько из них выделить), tone; тексты: kicker, title, accent, label. Для «7 из 10», «5 недель подряд».
- ring: pct (0–100), tone; тексты: kicker, title, accent, label.
- bars: values (2–5 чисел, можно отрицательные — изменение в %); тексты: kicker, title, items [{label, display}].
- timeline: тексты: kicker, title, items 3–5 [{date, label (до 30 символов)}].
- ticker: symbols (2–3 тикера Yahoo), range; тексты: kicker, title, names (короткие названия). Цены и изменения подставятся сами.
- checklist: тексты: kicker, title, list (2–3 пункта до 32 символов).
- cta: тексты: title — одно кодовое слово латиницей заглавными, одинаковое во всех языках (тикер или тема: BTC, NVDA, OIL, FED);
  kicker «Напиши в комментариях»; cta «пришлю разбор и уровни»; say «Напиши в комментариях NVDA — пришлю разбор.» (на нужном языке).

ТЕКСТЫ (ru, en, uz — узбекский латиницей, современный):
- say — что говорит диктор: 1–2 коротких предложения, 8–20 слов. Весь текст: русский 85–110 слов, английский 80–105, узбекский 70–90.
  Живо, разговорно, как рассказчик популярного канала о рынках: интрига в начале, перед главной цифрой и поворотом — тире «—» (пауза).
  Числа цифрами, проценты можно «12%». НЕ используй значок $ и сокращения (млн, млрд, тыс.) — пиши «75 тысяч долларов», «1,3 миллиарда долларов».
- beats — 1–3 слова ИЗ say этой сцены (точно как в тексте, по одному слову), на которых меняется картинка: chain — по слову на каждое звено,
  checklist и timeline — на каждый пункт, candles — 2 (событие, уровни), counter/versus/grid/ring — 1–2 (на главной цифре).
- keys — 1–2 слова из say для золотой подсветки в субтитрах.
- kicker — до 30 символов; title — до 16 символов в строке, до 2 строк через \\n; accent — 1–2 слова из title для выделения золотом.
- source — откуда цифры сцены, коротко («Reuters, 9 ноя», «данные Yahoo Finance»).
- Все надписи — на языке ролика. Переводы не дословные, естественно для носителя, те же цифры.

ФАКТЫ И ТОН:
- Только цифры и факты из исследования ниже, ничего не выдумывай. Даты и цены — точно как в фактах.
- О компаниях и людях — только то, что сообщили издания, со ссылкой («по данным Reuters», «сообщает Bloomberg»). Никого не называй виновным, без оценок и слухов.
- Политика — нейтрально, только влияние на рынок.
- Не финансовый совет: без «покупайте/продавайте», говори «сценарий», «уровень», «за чем следить».
- Без поучений и шаблонов: никаких «друзья», «давайте разберём», «важно понимать», «запомните», «подписывайтесь».
topic — заголовок ролика по-русски; category и asset (главный тикер) — из исследования.
post — подпись для соцсетей на каждом языке (2–3 предложения + призыв зайти в бота @trai_agent_bot, без хэштегов) и hashtags (5–8 штук).'''


def make_script_story(facts):
    msg = RULES2 + '\n\nИССЛЕДОВАНИЕ:\n' + facts
    gc = {'temperature': 0.8, 'maxOutputTokens': 20000, 'responseMimeType': 'application/json'}
    parse = lambda t: json.loads(t.strip().removeprefix('```json').removeprefix('```').removesuffix('```'))
    try: txt, _, model = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg}]}], 'generationConfig': {**gc, 'responseSchema': SCHEMA2}}, timeout=240)
    except Exception as e:
        log('схема не принята:', e)
        txt, _, model = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg + '\n\nОтветь JSON строго по этой схеме:\n' + json.dumps(SCHEMA2, ensure_ascii=False)}]}], 'generationConfig': gc}, timeout=240)
    sc = parse(txt)
    if len(sc.get('scenes') or []) < 5: raise RuntimeError('слишком короткий сценарий')
    for _ in range(2):  # длина: 40–50 секунд речи
        wl = [len((x.get('ru') or {}).get('say', '').split()) for x in sc['scenes']]
        if sum(wl) <= 118 and max(wl) <= 24: break
        log(f'сценарий длинный ({sum(wl)} слов, самая длинная фраза {max(wl)}) — сокращаю')
        msg2 = ('Сократи этот сценарий: каждая фраза say — 8–20 слов, весь русский текст 85–110 слов (английский и узбекский — так же коротко). '
                'Сохрани историю, цифры, интригу, типы сцен и все остальные поля; beats и keys должны остаться словами из нового say. Верни тот же JSON.\n\n' + json.dumps(sc, ensure_ascii=False))
        try:
            t2, _, _ = gemini({'contents': [{'role': 'user', 'parts': [{'text': msg2}]}], 'generationConfig': {**gc, 'responseSchema': SCHEMA2}}, timeout=240)
            sc2 = parse(t2)
            if len(sc2.get('scenes') or []) >= 5: sc = sc2
        except Exception as e: log('сократить не вышло:', e); break
    sc['v'] = 2
    return sc, model


# ---------- Котировки: Yahoo Finance (без ключа) → Gate (крипта) → Stooq ----------
QUOTES = {}
UA = {'user-agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36'}
RANGE_DAYS = {'5d': 5, '1mo': 31, '3mo': 92, '6mo': 183, '1y': 366}
STOOQ = {'GC=F': 'gc.f', 'SI=F': 'si.f', 'CL=F': 'cl.f', 'BZ=F': 'cb.f', 'HG=F': 'hg.f', 'NG=F': 'ng.f', '^GSPC': '^spx', '^IXIC': '^ndq', '^DJI': '^dji', 'DX-Y.NYB': 'dx.f'}


def quotes(sym, rng='1mo', interval='1d'):
    k = (sym, rng, interval)
    if k in QUOTES: return QUOTES[k]
    out = None
    for host in ('query1', 'query2'):
        try:
            u = f'https://{host}.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym)}?range={rng}&interval={interval}&includePrePost=false'
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20) as r: res = json.load(r)['chart']['result'][0]
            q = res['indicators']['quote'][0]
            bars = [[t, o, h, l, c] for t, o, h, l, c in zip(res['timestamp'], q['open'], q['high'], q['low'], q['close']) if None not in (o, h, l, c)]
            if len(bars) >= 3: out = {'bars': bars, 'currency': (res.get('meta') or {}).get('currency') or 'USD', 'src': 'Yahoo Finance'}; break
        except Exception as e: log('Yahoo', sym, host, e)
    if not out and re.fullmatch(r'[A-Z0-9]+-USD', sym):  # крипта — Gate
        try:
            gi = {'1h': '1h', '1d': '1d', '1wk': '7d'}[interval]; lim = min(900, RANGE_DAYS[rng] * (24 if gi == '1h' else 1) // (7 if gi == '7d' else 1) + 1)
            u = f'https://api.gateio.ws/api/v4/spot/candlesticks?currency_pair={sym[:-4]}_USDT&interval={gi}&limit={lim}'
            with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=20) as r: rows = json.load(r)
            out = {'bars': [[int(x[0]), float(x[5]), float(x[3]), float(x[4]), float(x[2])] for x in rows], 'currency': 'USD', 'src': 'Gate'}
        except Exception as e: log('Gate', sym, e)
    if not out and interval != '1h':  # дневные — Stooq
        try:
            st = STOOQ.get(sym) or (sym[:6].lower() if sym.endswith('=X') else sym.lower() + '.us')
            with urllib.request.urlopen(urllib.request.Request(f'https://stooq.com/q/d/l/?s={urllib.parse.quote(st)}&i=d', headers=UA), timeout=20) as r: lines = r.read().decode().strip().splitlines()[1:]
            rows = [l.split(',') for l in lines][-RANGE_DAYS[rng]:]
            bars = [[int(datetime.datetime.strptime(x[0], '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc).timestamp()), *map(float, x[1:5])] for x in rows if len(x) >= 5]
            if len(bars) >= 3: out = {'bars': bars, 'currency': 'USD', 'src': 'Stooq'}
        except Exception as e: log('Stooq', sym, e)
    QUOTES[k] = out
    return out


def agg(bars, n=60):
    # не больше n свечей: соседние объединяем (время — первой свечи группы)
    if len(bars) <= n: return bars
    g = -(-len(bars) // n); out = []
    for i in range(len(bars) % g, len(bars), g):  # с конца: последняя свеча — самая свежая
        ch = bars[i:i + g]; out.append([ch[0][0], ch[0][1], max(b[2] for b in ch), min(b[3] for b in ch), ch[-1][4]])
    return out


PERIOD = {'ru': {'5d': 'за 5 дней', '1mo': 'за месяц', '3mo': 'за 3 месяца', '6mo': 'за полгода', '1y': 'за год'},
          'en': {'5d': 'in 5 days', '1mo': 'in a month', '3mo': 'in 3 months', '6mo': 'in 6 months', '1y': 'in a year'},
          'uz': {'5d': '5 kunda', '1mo': 'bir oyda', '3mo': '3 oyda', '6mo': 'yarim yilda', '1y': 'bir yilda'}}
CTA_TXT = {'ru': ('Напиши в комментариях', 'пришлю разбор и уровни'), 'en': ('Comment the word', 'and I’ll send the breakdown'), 'uz': ('Izohga yozing', 'tahlil va darajalarni yuboraman')}


def money_prefix(sym, cur):
    return '' if (sym.endswith('=X') or sym.startswith('^') or sym == 'DX-Y.NYB') else ('$' if (cur or 'USD') == 'USD' else '')


def beat_times(ws, beats):
    out, j = [], 0
    for b in beats or []:
        nb = norm(b)
        if not nb: continue
        for i in range(j, len(ws)):
            nw = norm(ws[i][0])
            if nw and (nw.startswith(nb) or (len(nw) > 3 and nb.startswith(nw))): out.append(round(ws[i][1], 3)); j = i + 1; break
    return out


def scene_data2(s, L, script):
    t = s.get(L) or {}; ty = s.get('type') or 'counter'
    g = lambda k, dflt='': t.get(k) if t.get(k) not in (None, '') else dflt
    d = {'type': ty, 'kicker': g('kicker'), 'title': g('title'), 'accent': g('accent'), 'source': g('source')}
    sym = (s.get('symbol') or script.get('asset') or '').strip()
    if ty == 'hook':
        d.update(label=g('label'), prefix=g('prefix'), suffix=g('suffix'), dir=s.get('dir') or 'none')
        if s.get('value') is not None: d['value'] = s['value']; d['decimals'] = s.get('decimals') or (0 if float(s['value']).is_integer() else 1)
        if s.get('from') is not None: d['from'] = s['from']
        qq = quotes(sym, '1mo', '1d') if sym else None
        if qq: d['series'] = [b[4] for b in qq['bars']][-40:]
    elif ty == 'candles':
        rng = s.get('range') or '1mo'; iv = s.get('interval') or ('1h' if rng == '5d' else '1wk' if rng == '1y' else '1d')
        qq = quotes(sym, rng, iv) if sym else None
        if qq and len(qq['bars']) >= 5:
            bars = agg(qq['bars'], 60)
            d.update(bars=[[round(b[1], 4), round(b[2], 4), round(b[3], 4), round(b[4], 4)] for b in bars], period=PERIOD[L][rng], prefix=money_prefix(sym, qq['currency']),
                     mark_label=g('mark_label'), source=g('source') or f'{sym} · {qq["src"]}')
            if s.get('mark_date'):
                try:
                    md = datetime.datetime.strptime(s['mark_date'][:10], '%Y-%m-%d').replace(tzinfo=datetime.timezone.utc).timestamp()
                    idx = max([i for i, b in enumerate(bars) if b[0] <= md + 86399] or [0])
                    if bars[0][0] <= md + 86399 and md <= bars[-1][0] + 2 * 86400: d['mark'] = idx  # дата вне графика — без отметки
                except Exception: pass
            lb, tn = t.get('level_labels') or [], s.get('level_tones') or []
            lo, hi = min(b[3] for b in bars), max(b[2] for b in bars); span = hi - lo
            d['levels'] = [{'price': v, 'tone': tn[i] if i < len(tn) else 'gold', 'label': lb[i] if i < len(lb) else ''} for i, v in enumerate((s.get('levels') or [])[:3])
                           if isinstance(v, (int, float)) and lo - span * 0.6 <= v <= hi + span * 0.6]  # уровень далеко от графика сплющит свечи — не рисуем
        elif s.get('value') is not None:
            d.update(type='counter', value=s['value'], decimals=s.get('decimals') or 0, label=g('mark_label'), prefix=g('prefix'), suffix=g('suffix'))
        else:
            d.update(type='hook', label=g('mark_label'), dir=s.get('dir') or 'none')
    elif ty == 'counter':
        d.update(value=s.get('value') or 0, decimals=s.get('decimals') or 0, label=g('label'), prefix=g('prefix'), suffix=g('suffix'), tone=s.get('tone') or '')
        if s.get('from') is not None: d['from'] = s['from']
        if s.get('ref_value'):
            gap = (d['value'] / s['ref_value'] - 1) * 100
            d['ref'] = {'value': s['ref_value'], 'label': {'ru': 'сейчас', 'en': 'now', 'uz': 'hozir'}[L], 'target': g('label'), 'gap': ('+' if gap >= 0 else '−') + f'{abs(gap):.1f}%'.replace('.', ',' if L != 'en' else '.')}
            d['label'] = ''
    elif ty == 'versus':
        d.update(a={'label': g('a_label'), 'display': g('a_display'), 'value': s.get('a_value') or 1, 'tone': s.get('a_tone') or 'gold'},
                 b={'label': g('b_label'), 'display': g('b_display'), 'value': s.get('b_value') or 1, 'tone': s.get('b_tone') or 'txt'}, badge=g('badge'))
    elif ty == 'grid': d.update(total=s.get('total') or 10, count=s.get('count') or 0, tone=s.get('tone') or 'down', label=g('label'))
    elif ty == 'ring': d.update(pct=s.get('pct') or 0, tone=s.get('tone') or 'gold', label=g('label'))
    elif ty == 'bars':
        vals = s.get('values') or []
        d['items'] = [{'label': it.get('label', ''), 'display': it.get('display', ''), 'value': vals[i] if i < len(vals) else 0} for i, it in enumerate(t.get('items') or [])]
    elif ty == 'chain': d['items'] = [{'label': it.get('label', ''), 'sub': it.get('sub', '')} for it in (t.get('items') or [])][:4]
    elif ty == 'timeline': d['items'] = [{'date': it.get('date', ''), 'label': it.get('label', '')} for it in (t.get('items') or [])][:5]
    elif ty == 'checklist': d['items'] = (t.get('list') or [it.get('label', '') for it in (t.get('items') or [])])[:4]
    elif ty == 'headline': d.update(source_name=s.get('source_name') or '', date=g('date'), text=g('text') or g('title'), highlight=g('highlight'), tone=s.get('tone') or '', source='')
    elif ty == 'ticker':
        names = t.get('names') or []; rng = s.get('range') or '5d'; its = []
        for i, sy in enumerate((s.get('symbols') or [])[:3]):
            qq = quotes(sy, rng, '1h' if rng == '5d' else '1d')
            if not qq: continue
            b = qq['bars']; its.append({'symbol': sy.replace('-USD', '').replace('=F', '').replace('^', ''), 'name': names[i] if i < len(names) else '',
                                        'price': b[-1][4], 'change': (b[-1][4] / b[0][1] - 1) * 100, 'series': [x[4] for x in b][-60:]})
        d['items'] = its
        if not its: d.update(type='hook')
    elif ty == 'cta':
        k, c = CTA_TXT[L]; d.update(title=re.sub(r'[^A-Z0-9]', '', str(g('title')).upper()) or 'TRAI', kicker=g('kicker', k), cta=g('cta', c))
    # пустые сцены не показываем пустыми
    if d['type'] in ('chain', 'timeline', 'checklist', 'bars') and not d.get('items'): d['type'] = 'hook'
    return d


def make_video(script, L, idx, stamp, mock=False):
    work = os.path.join(OUTDIR, f'{stamp}_{idx}_{L}')
    os.makedirs(work, exist_ok=True)
    sc = script['scenes']; says = [(x[L].get('say') or '').strip() for x in sc]
    engine = 'mock' if mock else 'eleven' if os.environ.get('ELEVENLABS_API_KEY') else (os.environ.get('VOICE_ENGINE') or 'gemini')
    tok_scene = []  # (слово с пунктуацией, время, номер сцены)
    voice = None
    if engine == 'gemini':
        try:
            p = os.path.join(work, 'vo_all.wav'); tts_gemini_whole(says, L, p); a, off = trim(read_wav(p))
            wr = lambda path, arr: (lambda w: (w.setnchannels(1), w.setsampwidth(2), w.setframerate(SR), w.writeframes((np.clip(arr, -1, 1) * 32767).astype('<i2').tobytes()), w.close()))(wave.open(path, 'wb'))
            wr(p, a)
            toks = [(w, i) for i, sy in enumerate(says) for w in words_of(sy)]
            heard = whisper_words(p, L); tm = align_text([w for w, _ in toks], heard, len(a) / SR)
            # лишняя речь перед первым словом сценария (модель прочитала инструкцию) — вырезаем
            cut = safe_cut(a, tm[0] if tm else 0.0, heard)
            if cut > 0:
                log(f'вырезаю {cut:.2f} с лишней речи в начале'); a = a[int(cut * SR):].copy(); n_ = int(0.01 * SR); a[:n_] *= np.linspace(0, 1, n_); tm = [max(0.0, x_ - cut) for x_ in tm]
            # после последнего слова у Gemini бывает шум/«жужжание» — обрезаем через 0,3 с после конца речи и плавно гасим
            le = getattr(whisper_words, 'last_end', None)
            if le and le - cut + 0.3 < len(a) / SR:
                a = a[:int((le - cut + 0.3) * SR)].copy(); n = int(0.08 * SR); a[-n:] *= np.linspace(1, 0, n); log(f'хвост после речи обрезан на {le - cut + 0.3:.1f} с')
            if len(a) / SR > 52:  # только если совсем длинно (> 52 с) — чуть ускоряем без изменения высоты голоса (не больше чем на 18%), время слов — так же
                k = min(1.12, len(a) / SR / 48); tmp = os.path.join(work, 'vo_raw.wav'); wr(tmp, a)
                subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', tmp, '-filter:a', f'atempo={k:.3f}', '-ar', str(SR), '-ac', '1', p], check=True)
                a = read_wav(p); tm = [x_ / k for x_ in tm]; log(f'голос ускорен ×{k:.2f}')
            voice = np.concatenate([np.zeros(int(0.3 * SR)), a])
            tok_scene = [(w, 0.3 + t_, i) for (w, i), t_ in zip(toks, tm)]
            speech = len(a) / SR
        except Exception as e:
            log('голос Gemini не получился, беру Azure:', e); engine = 'azure'
    if voice is None:
        # по сценам: ElevenLabs или Azure дают время слов сами; между сценами паузы
        parts, wsl = [], []
        for i, say in enumerate(says):
            if engine == 'mock':
                ww = words_of(say); n = max(1, len(ww)); dur = max(2.2, n * 0.4); a = np.zeros(int(dur * SR)); ws = [[w, k * dur / n] for k, w in enumerate(ww)]
            else:
                p = os.path.join(work, f'vo_{i}.wav'); raw = tts(say, L, p); a, off = trim(read_wav(p))
                ws = align(say, [[w, max(0.0, tt - off)] for w, tt in raw])
                if not ws:
                    toks = say.split(); tot = sum(len(w) for w in toks) or 1; acc = 0
                    for w in toks: ws.append([w, acc / tot * len(a) / SR]); acc += len(w)
            parts.append(a); wsl.append(ws)
        speech = sum(len(a) for a in parts) / SR
        gap = min(0.9, max(0.25, (30 - 2.0 - 0.3 - 0.5 - speech) / max(1, len(parts) - 1)))
        vv, t = [np.zeros(int(0.3 * SR))], 0.3
        for i, (a, ws) in enumerate(zip(parts, wsl)):
            tok_scene += [(w, t + tt, i) for w, tt in ws]
            vv.append(a); t += len(a) / SR
            if i < len(parts) - 1: vv.append(np.zeros(int(gap * SR))); t += gap
        voice = np.concatenate(vv)
    # 2) таймлайн: сцена начинается с её первого слова, субтитры — по словам внутри сцены
    scenes, subs, v2 = [], [], script.get('v') == 2
    for i, s in enumerate(sc):
        ws = [[w, t_] for w, t_, k in tok_scene if k == i]
        d = scene_data2(s, L, script) if v2 else scene_data(s, L, work); st = ws[0][1] if ws else (scenes[-1]['start'] + 2.5 if scenes else 0.3)
        d['start'] = 0.0 if i == 0 else round(max(st - (0.18 if v2 else 0.12), scenes[-1]['start'] + 0.8), 3)
        if v2: d['beats'] = beat_times(ws, (s.get(L) or {}).get('beats') or [])
        scenes.append(d); subs += chunks(ws, s[L].get('keys') or [])
    t = len(voice) / SR
    outro = round(max(t + 0.5, 28.0), 3); total = round(outro + (2.3 if v2 else 2.0), 3)  # ролик не короче 30 с
    for i, d in enumerate(scenes): d['end'] = scenes[i + 1]['start'] if i + 1 < len(scenes) else outro
    beats = [] if v2 else [c['w'][c['key']][1] for c in subs if c.get('key', -1) >= 0]
    job = {'template': 'scene2.html' if v2 else 'scene.html', 'lang': L, 'handle': '@trai_agent_bot', 'tagline': TAGLINE[L], 'disclaimer': (DISCLAIMER_SHORT if v2 else DISCLAIMER)[L], 'scenes': scenes, 'subs': subs, 'beats': beats, 'outro': outro, 'total': total}
    jp = os.path.join(work, 'job.json'); json.dump(job, open(jp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    v = np.concatenate([voice, np.zeros(max(0, int(total * SR) - len(voice)))])[:int(total * SR)]
    with wave.open(os.path.join(work, 'voice.wav'), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(v, -1, 1) * 32767).astype('<i2').tobytes())
    # 3) кадры, эффекты, сведение
    subprocess.run(['node', os.path.join(HERE, 'render.cjs'), jp, os.path.join(work, 'v.mp4')], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'sfx.py'), jp, os.path.join(work, 'sfx.wav')], check=True)
    final = os.path.join(OUTDIR, f'trai_{stamp}_{idx}_{L}.mp4')
    fc = (f'[1:a]aresample={SR},highpass=f=70,acompressor=threshold=-22dB:ratio=3.5:attack=5:release=80,volume=1.6[vo];'
          f'[2:a]volume=0.55[fx];[vo][fx]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-13:TP=-1.2:LRA=8,apad,atrim=0:{total}[a]')  # голос громче эффектов
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', os.path.join(work, 'v.mp4'), '-i', os.path.join(work, 'voice.wav'), '-i', os.path.join(work, 'sfx.wav'),
                    '-filter_complex', fc, '-map', '0:v', '-map', '[a]', '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-ar', str(SR), '-movflags', '+faststart', final], check=True)
    log(f'готово {final} · {total:.1f} с · речь {speech:.1f} с · голос {engine}')
    return final, total


# ---------- Telegram: файлом (без сжатия) ----------
def tg_send(path, caption):
    tok, chat = os.environ.get('TG_BOT_TOKEN'), os.environ.get('TG_REVIEW_CHAT')
    if not tok or not chat: return False
    if os.path.getsize(path) > 49e6: caption += '\n\nФайл больше 50 МБ — скачай его на странице запуска в GitHub (Artifacts).'
    if os.path.getsize(path) > 49e6:
        r = subprocess.run(['curl', '-sS', '-X', 'POST', f'https://api.telegram.org/bot{tok}/sendMessage', '-d', f'chat_id={chat}', '--data-urlencode', f'text={caption[:4000]}'], capture_output=True, text=True)
    else:
        r = subprocess.run(['curl', '-sS', '-X', 'POST', f'https://api.telegram.org/bot{tok}/sendDocument', '-F', f'chat_id={chat}', '-F', f'caption={caption[:1020]}',
                            '-F', f'document=@{path};type=video/mp4'], capture_output=True, text=True)
    ok = '"ok":true' in r.stdout
    if not ok: log('Telegram не принял:', r.stdout[:300], r.stderr[:300])
    return ok


def tg_text(text):
    tok, chat = os.environ.get('TG_BOT_TOKEN'), os.environ.get('TG_REVIEW_CHAT')
    if tok and chat: subprocess.run(['curl', '-sS', '-X', 'POST', f'https://api.telegram.org/bot{tok}/sendMessage', '-d', f'chat_id={chat}', '--data-urlencode', f'text={text[:4000]}'], capture_output=True)


MOCK = {'topic': 'Всё золото мира против биткоина (проверка шаблона)', 'post': {l: {'caption': 'Проверочный ролик', 'hashtags': '#золото #gold'} for l in LANGS_ALL},
        'scenes': [
            {'type': 'hook', 'art': 'ingots', 'ru': {'say': 'Всё золото, которое люди добыли за всю историю — 220 000 тонн.', 'kicker': 'Факт дня · золото', 'title': 'Всё золото\nмира', 'keys': ['золото']}},
            {'type': 'chart', 'hours': 60, 'levels': [4128, 4061, 4092], 'tones': ['blue', 'up', 'gold'], 'zone': [4110, 4128], 'dir': 'up', 'ru': {'say': 'Над 4 128 скопились стопы продавцов — цена уже трижды к ним тянулась.', 'kicker': 'данные TRAI · 1 час', 'title': 'Где стопы', 'level_labels': ['Стопы продавцов', 'Поддержка', 'VWAP'], 'zone_label': 'цель', 'source': 'данные TRAI', 'keys': ['стопы']}},
            {'type': 'photo', 'photo_query': 'gold bars vault', 'ru': {'say': 'Центробанки скупают золото быстрее, чем когда-либо.', 'kicker': 'факт', 'title': 'Хранилища\nполнеют'}},
            {'type': 'gamma3d', 'ru': {'say': 'Гамма опционов: синее держит цену, красное разгоняет.', 'kicker': 'опционы · данные TRAI', 'title': 'Гамма 3D', 'source': 'CBOE, данные TRAI'}},
            {'type': 'walls', 'ru': {'say': 'Стена коллов на 4 150 — потолок недели.', 'kicker': 'стены опционов', 'title': 'Где потолок', 'call_label': 'Стена коллов', 'put_label': 'Стена путов', 'source': 'CBOE, данные TRAI', 'keys': ['потолок']}},
            {'type': 'big', 'value': 28.9, 'decimals': 1, 'ru': {'say': 'И стоит оно почти 29 триллионов долларов.', 'kicker': 'по цене $4 072 за унцию', 'title': 'Сколько\nоно стоит', 'label': 'Всё золото мира', 'prefix': '$', 'suffix': 'трлн', 'source': 'World Gold Council, 2025', 'keys': ['29']}},
            {'type': 'percent', 'pct': 1.6, 'ru': {'say': 'За год добывают всего около 3 500 тонн — меньше 2 процентов.', 'kicker': 'добыча за год', 'title': 'Всего 1,6%', 'label': 'от всего золота', 'sub': '≈3 500 т в год', 'source': 'World Gold Council'}},
            {'type': 'compare', 'a_value': 28.9, 'b_value': 1.57, 'ru': {'say': 'А все биткоины мира стоят в 18 раз меньше золота.', 'kicker': 'биткоин против золота', 'title': 'В 18 раз\nменьше', 'a_label': 'Золото', 'a_display': '$28,9 трлн', 'b_label': 'Биткоин', 'b_display': '$1,57 трлн', 'badge': '×18', 'source': 'ноябрь 2026'}},
            {'type': 'bars', 'values': [2.1, -1.4, 0.8, 3.2], 'ru': {'say': 'Вот как золото реагировало на решения ФРС в последние разы.', 'kicker': 'реакция на ФРС', 'title': 'За 4 раза', 'items': [{'label': 'Июнь', 'display': '+2,1%'}, {'label': 'Июль', 'display': '−1,4%'}, {'label': 'Сентябрь', 'display': '+0,8%'}, {'label': 'Октябрь', 'display': '+3,2%'}]}},
            {'type': 'pattern', 'kind': 'double_bottom', 'ru': {'say': 'Двойное дно: цена дважды отбилась от уровня и пошла вверх.', 'kicker': 'фигура графика', 'title': 'Двойное дно', 'level_label': 'линия шеи'}},
            {'type': 'ask', 'ru': {'say': 'Напиши в комментариях GOLD — и я пришлю подробный разбор.', 'kicker': 'Напиши в комментариях', 'title': 'GOLD', 'options': [], 'cta': 'и я пришлю подробный разбор'}},
        ]}


MOCK2 = {'v': 2, 'topic': 'Биткоин падает пятую неделю подряд (проверка шаблона)', 'category': 'crypto', 'asset': 'BTC-USD',
         'post': {l: {'caption': 'Проверочный ролик', 'hashtags': '#bitcoin #btc'} for l in LANGS_ALL},
         'scenes': [
             {'type': 'hook', 'value': -12.4, 'decimals': 1, 'dir': 'down', 'symbol': 'BTC-USD', 'ru': {'say': 'Биткоин падает пятую неделю подряд. Минус 12% — это 216 миллиардов долларов.', 'kicker': 'BTC · Биткоин', 'title': 'Пять недель\nподряд вниз', 'accent': 'пять вниз', 'label': 'с 4 октября · −216 млрд $', 'suffix': '%', 'beats': ['Минус', '216'], 'keys': ['пятую']}},
             {'type': 'grid', 'total': 5, 'count': 5, 'tone': 'down', 'ru': {'say': 'С начала октября каждая неделя закрылась ниже прошлой. Пять из пяти.', 'kicker': 'Недельные закрытия', 'title': '5 из 5 недель\nв минусе', 'accent': '5', 'label': '−3,3% · −2,0% · −2,4% · −2,3% · −3,2%', 'beats': ['каждая', 'Пять'], 'keys': ['Пять']}},
             {'type': 'candles', 'symbol': 'BTC-USD', 'range': '1mo', 'interval': '1d', 'mark_date': '2026-11-04', 'levels': [81765, 73176], 'level_tones': ['gold', 'blue'], 'ru': {'say': 'После выборов в США цена отскочила до 81 тысячи — и за пару дней отдала весь рост.', 'kicker': 'BTC/USD · дневные свечи', 'mark_label': 'отскок после выборов', 'level_labels': ['50-дневная средняя', '200-дневная средняя'], 'source': 'Данные: Kraken', 'beats': ['отскочила', 'отдала'], 'keys': ['отдала']}},
             {'type': 'chain', 'ru': {'say': 'Почему? Из биржевых фондов за пять дней ушло больше миллиарда. Один IBIT — минус 403 миллиона за день. И цена провалилась под среднюю.', 'kicker': 'Почему падает', 'title': 'Кто продаёт', 'accent': 'продаёт', 'source': 'Потоки ETF: Farside', 'items': [{'label': 'Отток из ETF', 'sub': '−1,28 млрд $ за 5 сессий'}, {'label': 'IBIT от BlackRock', 'sub': '−403 млн $ за день, 6 ноября'}, {'label': 'Цена под 50-дневной', 'sub': '−7,3% от средней'}], 'beats': ['фондов', 'IBIT', 'провалилась'], 'keys': ['миллиарда']}},
             {'type': 'counter', 'value': 73176, 'ref_value': 75774, 'tone': 'blue', 'ru': {'say': 'Но главное — не серия. Чуть больше трёх процентов ниже лежит двухсотдневная средняя. 73 тысячи.', 'kicker': 'Главный уровень', 'title': 'До него\nвсего 3,4%', 'accent': '3,4%', 'label': '200-дневная', 'prefix': '$', 'beats': ['73'], 'keys': ['главное']}},
             {'type': 'checklist', 'ru': {'say': 'Смотрим три вещи. Неделя выше 78 тысяч прервёт серию. День под двухсотдневной сломает структуру. И потоки в фонды.', 'kicker': 'Что смотреть дальше', 'title': 'Три сигнала', 'accent': 'три', 'list': ['Недельное закрытие выше $78 239', 'Дневное закрытие у $73 176', 'Потоки ETF после выходных'], 'beats': ['Неделя', 'День', 'потоки'], 'keys': ['три']}},
             {'type': 'cta', 'ru': {'say': 'Напиши в комментариях BTC — пришлю разбор.', 'title': 'BTC', 'beats': [], 'keys': ['BTC']}},
         ]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=1); ap.add_argument('--langs', default='ru,en,uz'); ap.add_argument('--formats', default='')
    ap.add_argument('--mode', default='story', choices=['story', 'gold'])  # story — истории любого рынка за неделю; gold — старые темы про золото
    ap.add_argument('--mock', action='store_true')
    a = ap.parse_args(); langs = [l for l in a.langs.split(',') if l in LANGS_ALL]
    os.makedirs(OUTDIR, exist_ok=True)
    hist = json.load(open(HIST, encoding='utf-8')) if os.path.exists(HIST) else []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M')
    order = [f for f in (a.formats.split(',') if a.formats else []) if f in FORMATS] or ['levels', 'hype', 'pattern', 'options', 'news', 'indicators', 'fact']
    start = len(hist) % len(order) if not a.formats else 0
    made = []; cats_run = []
    for n in range(a.count):
        fmt = 'story' if a.mode == 'story' else order[(start + n) % len(order)]
        try:
            if a.mode == 'story':
                if a.mock:
                    script, src, models = json.loads(json.dumps(MOCK2)), ['проверка'], 'mock'; langs = ['ru']; p0 = 86500.0; bb = []
                    for k in range(32): o = p0; p0 *= 1 + float(np.sin(k / 3) * 0.012 - 0.004); bb.append([1791417600 + k * 86400, o, max(o, p0) * 1.006, min(o, p0) * 0.994, p0])
                    QUOTES[('BTC-USD', '1mo', '1d')] = {'bars': bb, 'currency': 'USD', 'src': 'mock'}
                else:
                    # разнообразие: категория не как у двух последних роликов и не как у уже сделанных в этом запуске
                    avoid = set(cats_run) | {h.get('category') for h in hist[-2:] if h.get('category')}
                    facts, src, m1, cat = research_story(hist, avoid); log('история/факты:', m1, facts[:500].replace('\n', ' '))
                    script, m2 = make_script_story(facts); models = f'{m1}, {m2}'
                    script['category'] = script.get('category') or cat
                    json.dump({'facts': facts, 'sources': src, 'script': script}, open(os.path.join(OUTDIR, f'script_{stamp}_{n}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
                cats_run.append(script.get('category') or '')
            elif a.mock:
                script, src, models = MOCK, ['проверка'], 'mock'; langs = ['ru']; p0 = 4080.0; bb = []
                for k in range(200): o = p0; p0 += float(np.sin(k / 9) * 4 + np.cos(k / 3.1) * 3); bb.append([k * 3600, o, max(o, p0) + 3, min(o, p0) - 3, p0])
                gz = [[round(float(np.exp(-((4000 + j * 10 - 4080 - 30) / 45) ** 2) * 90 * (1 + .3 * np.sin(i / 5)) - np.exp(-((4000 + j * 10 - 4080 + 50) / 40) ** 2) * 80), 2) for j in range(41)] for i in range(60)]
                ks = [{'price': 3900 + k * 10, 'call': round(float(np.exp(-((3900 + k * 10 - 4150) / 60) ** 2) * 180), 1), 'put': -round(float(np.exp(-((3900 + k * 10 - 4000) / 60) ** 2) * 150), 1)} for k in range(41)]
                DATA.update({'bars': bb, 'market': {}, 'gamma_hist': {'z': gz, 'prices': [4000 + j * 10 for j in range(41)], 'price': 4080}, 'gamma': {'strikes': ks, 'xau': 4080, 'call_wall': 4150, 'put_wall': 4000}})
            else:
                facts, src, m1 = research(fmt, [h['topic'] for h in hist]); log('тема/факты:', m1, facts[:400].replace('\n', ' '))
                script, m2 = make_script(facts, fmt); models = f'{m1}, {m2}'
                json.dump({'facts': facts, 'sources': src, 'script': script}, open(os.path.join(OUTDIR, f'script_{stamp}_{n}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
            log('сценарий:', script['topic'])
            for k, sc_ in enumerate(script['scenes']): log(f'  {k + 1}. {sc_["type"]}: {(sc_.get("ru") or {}).get("say", "")}')
            for L in langs:
                try:
                    path, dur = make_video(script, L, n, stamp, mock=a.mock)
                    p = (script.get('post') or {}).get(L) or {}
                    cap = f'{script["topic"]} · {L.upper()} · {dur:.0f} с\n\n{p.get("caption", "")}\n{p.get("hashtags", "")}\n\nИсточники: {", ".join(src) or "—"}'
                    tg_send(path, cap); made.append(path)
                except Exception as e:
                    log(f'ошибка ({L}):', e); tg_text(f'TRAI видео: не получилось собрать {L.upper()} «{script["topic"]}»: {e}')
            hist.append({'date': stamp, 'format': fmt, 'topic': script['topic'], 'category': script.get('category', ''), 'asset': script.get('asset', '')})
        except Exception as e:
            log('ошибка темы:', e); tg_text(f'TRAI видео: не получилось сделать ролик ({fmt}): {e}')
    if not a.mock: json.dump(hist[-200:], open(HIST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log('роликов:', len(made))
    if not made: sys.exit(1)


if __name__ == '__main__':
    main()
