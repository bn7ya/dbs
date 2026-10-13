const path = require('node:path');
const { spawn } = require('node:child_process');
const { once } = require('node:events');
const { chromium } = require('playwright');

const FPS = 30;
const DURATION = 30;
const SIZE = { width: 1080, height: 1920 };

async function openReel() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: SIZE, deviceScaleFactor: 1 });
  await page.goto('file://' + path.join(__dirname, 'reel.html'));
  await page.evaluate(() => document.fonts.ready);
  await page.waitForTimeout(300);
  return { browser, page };
}

async function frameAt(page, seconds, type = 'png') {
  await page.evaluate(t => window.render(t), seconds);
  return page.screenshot({ type, clip: { x: 0, y: 0, ...SIZE } });
}

async function stills(times, outDir) {
  const { browser, page } = await openReel();
  for (const t of times) {
    const file = path.join(outDir, `still-${t.toFixed(2).padStart(5, '0')}.png`);
    require('node:fs').writeFileSync(file, await frameAt(page, t));
    console.log(file);
  }
  await browser.close();
}

async function video(output) {
  const { browser, page } = await openReel();
  const ffmpeg = spawn('ffmpeg', [
    '-y', '-loglevel', 'error',
    '-f', 'image2pipe', '-framerate', String(FPS), '-c:v', 'png', '-i', '-',
    '-c:v', 'libx264', '-preset', 'slow', '-crf', '16', '-tune', 'animation',
    '-pix_fmt', 'yuv420p', '-profile:v', 'high', '-level', '4.1', '-g', String(FPS * 2),
    '-r', String(FPS), output,
  ], { stdio: ['pipe', 'inherit', 'inherit'] });
  const total = FPS * DURATION;
  for (let i = 0; i < total; i++) {
    const png = await frameAt(page, i / FPS);
    if (!ffmpeg.stdin.write(png)) await once(ffmpeg.stdin, 'drain');
    if (i % FPS === 0) process.stdout.write(`\r${i / FPS}s / ${DURATION}s`);
  }
  ffmpeg.stdin.end();
  const [code] = await once(ffmpeg, 'close');
  await browser.close();
  process.stdout.write('\n');
  if (code !== 0) process.exit(code);
}

async function cues() {
  const { browser, page } = await openReel();
  console.log(JSON.stringify(await page.evaluate(() => ({ beats: window.BEATS, ...window.CUES }))));
  await browser.close();
}

const [mode, ...rest] = process.argv.slice(2);
const run = {
  stills: () => stills(rest[0].split(',').map(Number), rest[1] || '.'),
  video: () => video(rest[0] || 'reel-silent.mp4'),
  cues,
}[mode];
if (!run) {
  console.error('usage: node render.cjs stills T1,T2,... [DIR] | video [OUT.mp4] | cues');
  process.exit(2);
}
run().catch(error => { console.error(error); process.exit(1); });
