// Кадры ролика → mp4 без звука. node render.cjs job.json out.mp4           — весь ролик
//                                   node render.cjs job.json - 2.5 7.5 …   — кадры для проверки (pv_*.png)
// Chrome рисует canvas из scene.html (данные — job.json), кадры JPEG идут в ffmpeg без промежуточных файлов.
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs'), path = require('path');
const DIR = __dirname, FPS = 30;

(async () => {
  const [jobPath, out, ...times] = process.argv.slice(2);
  const job = JSON.parse(fs.readFileSync(jobPath, 'utf8'));
  const exe = process.env.CHROME_PATH || (fs.existsSync('/usr/bin/google-chrome') ? '/usr/bin/google-chrome' : undefined);
  const b = await chromium.launch({ executablePath: exe, args: ['--no-sandbox', '--allow-file-access-from-files'] });
  const p = await b.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  const errs = []; p.on('pageerror', e => errs.push(e.message));
  await p.addInitScript(j => { window.JOB = j; }, job);
  await p.goto('file://' + path.join(DIR, 'scene.html')); await p.evaluate(() => window.ready);
  const cv = await p.$('#c');
  if (out === '-') {
    for (const t of times.map(Number)) { await p.evaluate(t => window.render(t), t); await cv.screenshot({ path: path.join(path.dirname(jobPath), `pv_${String(t).replace('.', '_')}.png`) }); }
  } else {
    const n = Math.round(job.total * FPS);
    const ff = spawn('ffmpeg', ['-v', 'error', '-y', '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'mjpeg', '-i', '-', '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '18', '-pix_fmt', 'yuv420p', '-r', String(FPS), out]);
    const done = new Promise((res, rej) => ff.on('close', c => (c === 0 ? res() : rej(new Error('ffmpeg ' + c)))));
    for (let j = 0; j < n; j++) {
      await p.evaluate(t => window.render(t), j / FPS);
      const buf = await cv.screenshot({ type: 'jpeg', quality: 92 });
      if (!ff.stdin.write(buf)) await new Promise(r => ff.stdin.once('drain', r));
    }
    ff.stdin.end(); await done; console.log('кадров', n, '→', out);
  }
  if (errs.length) { console.error(errs.join('\n')); process.exitCode = 1; }
  await b.close();
})();
