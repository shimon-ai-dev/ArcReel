// Run: node scripts/book/check_player.mjs /absolute/path/to/extracted/index.html
// Uses the project's Playwright package. Set CHROMIUM_EXECUTABLE for a system browser.
import { chromium } from '../../frontend/node_modules/@playwright/test/index.mjs';
import assert from 'node:assert/strict';
import { pathToFileURL } from 'node:url';

const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
});
try {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto(pathToFileURL(process.argv[2]).href);
  const chapters = await page.evaluate(() => JSON.parse(document.querySelector('#manifest').textContent).chapters);
  assert.ok(chapters.length >= 2, 'The smoke fixture must contain two chapters');
  assert.ok(chapters[0].keyframes.length >= 2, 'The first chapter must contain two keyframes');
  const first = chapters[0].keyframes[0].path;
  const second = chapters[0].keyframes[1];
  assert.notEqual(first, second.path, 'The seek fixture must change the image');
  const audio = page.locator('#audio');

  async function waitForMedia(chapter, imagePath) {
    await page.waitForFunction(({ chapter, imagePath }) => {
      const audio = document.querySelector('#audio');
      const frame = document.querySelector('#frame');
      return audio.readyState >= 1 && audio.getAttribute('src') === chapter.audio
        && frame.getAttribute('src') === imagePath && frame.complete && frame.naturalWidth > 0;
    }, { chapter, imagePath });
  }

  await waitForMedia(chapters[0], first);
  await page.locator('#title').click();
  const playbackStart = await audio.evaluate(async audio => {
    await audio.play();
    return audio.currentTime;
  });
  await page.waitForFunction(start => {
    const audio = document.querySelector('#audio');
    return !audio.paused && audio.currentTime > start + 0.05;
  }, playbackStart);
  await audio.evaluate(async audio => {
    audio.pause();
    const pausedAt = audio.currentTime;
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (!audio.paused || audio.currentTime !== pausedAt) throw Error('Playback continued after pause');
  });

  await audio.evaluate((audio, time) => { audio.currentTime = time + 0.05; }, second.time);
  await waitForMedia(chapters[0], second.path);
  await page.waitForFunction(() => !document.querySelector('#audio').seeking);
  assert.equal(await audio.evaluate(audio => audio.paused), true);

  await audio.evaluate(audio => { audio.currentTime = 0; });
  await waitForMedia(chapters[0], first);
  await page.waitForFunction(() => !document.querySelector('#audio').seeking);
  assert.equal(await audio.evaluate(audio => audio.paused), true);

  await page.selectOption('#rate', '1.5');
  await page.selectOption('#chapters', '1');
  await waitForMedia(chapters[1], chapters[1].keyframes[0].path);
  const result = await page.evaluate(() => ({
    chapter: document.querySelector('#chapters').value,
    rate: document.querySelector('#audio').playbackRate,
    duration: document.querySelector('#audio').duration,
    paused: document.querySelector('#audio').paused,
    image: document.querySelector('#frame').getAttribute('src'),
    error: document.querySelector('#error').textContent,
  }));
  assert.equal(result.chapter, '1');
  assert.equal(result.rate, 1.5);
  assert.equal(result.paused, true);
  assert.ok(Number.isFinite(result.duration) && result.duration > 0);
  assert.equal(result.image, chapters[1].keyframes[0].path);
  assert.equal(result.error, '');
  assert.deepEqual(pageErrors, []);
  console.log(JSON.stringify({ playbackAdvanced: true, pauseStable: true, forwardSeek: true, backwardSeek: true, ...result }));
} finally { await browser.close(); }
