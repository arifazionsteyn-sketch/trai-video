# Дорожка эффектов по таймлайну ролика: «вжух» на смене сцен, мягкий «пак» на появлении цифр,
# печать адреса клавишами, «Enter» и низкий «бум» под логотип (утверждённая концовка).
# python3 sfx.py job.json out.wav
import json, glob, os, sys, wave
import numpy as np

SR = 48000
HERE = os.path.dirname(os.path.abspath(__file__))
job = json.load(open(sys.argv[1], encoding='utf-8'))
TOTAL, OUT = job['total'], job['outro']
rng = np.random.default_rng(3)


def load(f):
    w = wave.open(f)
    a = np.frombuffer(w.readframes(w.getnframes()), '<i2').astype(float) / 32768
    return a.reshape(-1, w.getnchannels()) if w.getnchannels() == 2 else np.stack([a, a], 1)


out = np.zeros((int(SR * (TOTAL + 2)), 2))


def place(sig, t, g, pan=0.0):
    i = int(max(0, t) * SR); n = min(len(sig), len(out) - i)
    if n <= 0: return
    l, r = np.cos((pan + 1) * np.pi / 4) * 1.414, np.sin((pan + 1) * np.pi / 4) * 1.414
    out[i:i + n] += sig[:n] * g * np.array([l, r])


S = os.path.join(HERE, 'sfx')
keys = [load(f) for f in sorted(glob.glob(os.path.join(S, 'key_*.wav')))]
woosh, pac, pac2 = load(os.path.join(S, 'woosh.wav')), load(os.path.join(S, 'pac.wav')), load(os.path.join(S, 'pac2.wav'))


def boom(dur=1.4):
    n = int(SR * dur); tt = np.arange(n) / SR; f = 45 + 55 * np.exp(-tt / 0.06)
    s = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt / 0.4); s /= np.abs(s).max(); return np.stack([s, s], 1)


# переходы: пик «вжуха» — в момент смены сцены
for s in job['scenes'][1:]:
    place(woosh, s['start'] - 0.16, 0.14)
place(woosh, OUT - 0.16, 0.14)
# появление главной цифры/карточки в сцене
for k, s in enumerate(job['scenes']):
    d = s['end'] - s['start']
    if s['type'] in ('big', 'percent'): place(pac, s['start'] + min(1.9, d * 0.5) + 0.4, 0.10)
    elif s['type'] == 'compare': place(pac, s['start'] + min(2.2, d * 0.5), 0.12)
    elif s['type'] == 'ask':
        place(pac2, s['start'] + 0.6, 0.10, -0.4); place(pac2, s['start'] + 0.8, 0.10, 0.4)
    elif s['type'] in ('list', 'bars'):
        n = len(s.get('items') or [])
        for i in range(min(n, 5)):
            step = min(0.9 if s['type'] == 'list' else 0.45, (d - 1) / (n + 0.5 if s['type'] == 'list' else n + 1))
            place(pac2, s['start'] + 0.35 + i * step, 0.08, -0.3 + 0.6 * i / max(1, n - 1))
    elif s['type'] == 'hook' and s.get('art', 'ingots') == 'ingots':
        for i, t in enumerate([0.35, 0.51, 0.67]): place(pac2, s['start'] + t + 0.3, 0.09, [-0.4, 0.4, 0][i])
    elif s['type'] in ('pattern', 'line'):
        place(pac, s['start'] + 0.3 + min(2.6, d * 0.62), 0.10)

# сцены v2: мягкий «пак» на каждом ударе (слово диктора, на котором меняется картинка)
for k, s in enumerate(job['scenes']):
    bt = s.get('beats') or []
    if s['type'] == 'cta':
        w = len(str(s.get('title') or 'GOLD'))
        for i in range(w): place(keys[(i * 7) % len(keys)], s['start'] + 0.35 + i * 0.09, 0.12, -0.2 + 0.4 * i / max(1, w))
        continue
    if s['type'] not in ('hook', 'candles', 'counter', 'chain', 'versus', 'grid', 'timeline', 'headline', 'checklist', 'ring', 'bars', 'ticker'): continue
    for i, t in enumerate(bt[:5]):
        place(pac2 if i % 2 else pac, t - 0.01, 0.09 if i else 0.11, [-0.3, 0.3, 0, -0.2, 0.2][i % 5])
    if s['type'] == 'grid' and bt:
        n = int(s.get('count') or 0)
        for i in range(min(n, 12)): place(pac2, bt[0] + i * (0.9 / max(1, n)), 0.05, -0.4 + 0.8 * i / max(1, n - 1))

url = 'trai-agent.com'; typeA = OUT + 0.1; per = 0.06
order = rng.permutation(len(keys))
for i in range(len(url)):
    place(keys[order[i % len(keys)]], typeA + i * per + rng.uniform(-0.008, 0.008), 0.16, -0.2 + 0.4 * i / len(url))
press = typeA + len(url) * per + 0.08
place(keys[order[-1]], press, 0.22); place(pac, press + 0.02, 0.06)
place(boom(), press + 0.1, 0.14)

out = np.tanh(out[:int(SR * TOTAL)] * 1.1) / 1.1
with wave.open(sys.argv[2], 'wb') as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(out, -1, 1) * 32767).astype('<i2').tobytes())
