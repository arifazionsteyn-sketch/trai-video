# TRAI — автоматические ролики про золото: тема и факты (Gemini с поиском Google) → сценарий на RU/EN/UZ →
# озвучка Azure (время каждого слова для субтитров) → кадры (scene.html) → эффекты → сведение → Telegram.
#   python3 video/gen.py --count 3 --langs ru,en,uz
#   python3 video/gen.py --mock          — без сети: проверочный сценарий и тишина вместо голоса
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
    'ru': 'Ты диктор. Говори по-русски низким, мужественным, спокойным и ровным голосом — как опытный трейдер, который никуда не спешит и уверен в своих словах. Без восторга и без напора, не повышай голос, не тараторь: размеренный темп, чуть медленнее обычной речи. Очень чёткая дикция: каждое слово и каждую цифру произноси ясно. После важной цифры — короткая пауза. Без пауз в начале, между строками пауза. Читай ТОЛЬКО текст пользователя, ничего не добавляй.',
    'en': 'You are a narrator. Speak English in a low, masculine, calm but charismatic and confident voice — like an experienced trader. Calm, confident pace, never rushed; brief pause after key numbers. No pause at the start, pauses between lines. Read ONLY the user text, add nothing.',
    'uz': "Siz diktorsiz. O'zbek tilida past, erkakcha, xotirjam, lekin xarizmatik va ishonchli ovozda gapiring — tajribali treyder kabi. Xotirjam, shoshilmasdan; muhim raqamdan keyin qisqa pauza. Boshida pauza yo'q, satrlar orasida pauza. FAQAT foydalanuvchi matnini o'qing, hech narsa qo'shmang.",
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


def trim(a):
    # тишина в начале и в конце фразы Azure — убираем, чтобы сцены шли плотно
    idx = np.where(np.abs(a) > 0.01)[0]
    if not len(idx): return a, 0.0
    i0 = max(0, idx[0] - int(0.03 * SR)); i1 = min(len(a), idx[-1] + int(0.08 * SR))
    return a[i0:i1], i0 / SR


norm = lambda s: re.sub(r'[^\w%$]+', '', s.lower().replace('ё', 'е'))


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
            cut = max(0.0, (tm[0] if tm else 0) - 0.12)
            if cut > 0.6:
                log(f'вырезаю {cut:.1f} с лишней речи в начале'); a = a[int(cut * SR):]; tm = [max(0.0, x_ - cut) for x_ in tm]
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
    scenes, subs = [], []
    for i, s in enumerate(sc):
        ws = [[w, t_] for w, t_, k in tok_scene if k == i]
        d = scene_data(s, L, work); st = ws[0][1] if ws else (scenes[-1]['start'] + 2.5 if scenes else 0.3)
        d['start'] = 0.0 if i == 0 else round(max(st - 0.12, scenes[-1]['start'] + 0.8), 3)
        scenes.append(d); subs += chunks(ws, s[L].get('keys') or [])
    t = len(voice) / SR
    outro = round(max(t + 0.5, 28.0), 3); total = round(outro + 2.0, 3)  # ролик не короче 30 с
    for i, d in enumerate(scenes): d['end'] = scenes[i + 1]['start'] if i + 1 < len(scenes) else outro
    beats = [c['w'][c['key']][1] for c in subs if c.get('key', -1) >= 0]
    job = {'lang': L, 'handle': '@trai_agent_bot', 'tagline': TAGLINE[L], 'disclaimer': DISCLAIMER[L], 'scenes': scenes, 'subs': subs, 'beats': beats, 'outro': outro, 'total': total}
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--count', type=int, default=1); ap.add_argument('--langs', default='ru,en,uz'); ap.add_argument('--formats', default='')
    ap.add_argument('--mock', action='store_true')
    a = ap.parse_args(); langs = [l for l in a.langs.split(',') if l in LANGS_ALL]
    os.makedirs(OUTDIR, exist_ok=True)
    hist = json.load(open(HIST, encoding='utf-8')) if os.path.exists(HIST) else []
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M')
    order = [f for f in (a.formats.split(',') if a.formats else []) if f in FORMATS] or ['levels', 'hype', 'pattern', 'options', 'news', 'indicators', 'fact']
    start = len(hist) % len(order) if not a.formats else 0
    made = []
    for n in range(a.count):
        fmt = order[(start + n) % len(order)]
        try:
            if a.mock:
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
            hist.append({'date': stamp, 'format': fmt, 'topic': script['topic']})
        except Exception as e:
            log('ошибка темы:', e); tg_text(f'TRAI видео: не получилось сделать ролик ({fmt}): {e}')
    if not a.mock: json.dump(hist[-200:], open(HIST, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log('роликов:', len(made))
    if not made: sys.exit(1)


if __name__ == '__main__':
    main()
