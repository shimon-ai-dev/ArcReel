// Run: node scripts/book/check_player.mjs /absolute/path/to/extracted/index.html
// Uses the project's Playwright package. Set CHROMIUM_EXECUTABLE for a system browser.
import { chromium } from '../../frontend/node_modules/@playwright/test/index.mjs';
import { pathToFileURL } from 'node:url';
const browser = await chromium.launch({
  headless: true,
  ...(process.env.CHROMIUM_EXECUTABLE ? { executablePath: process.env.CHROMIUM_EXECUTABLE } : {}),
});
try {
  const page = await browser.newPage();
  await page.goto(pathToFileURL(process.argv[2]).href);
  await page.waitForFunction(() => document.querySelector('#audio').readyState >= 1);
  const first = await page.locator('#frame').getAttribute('src');
  const secondTime = await page.evaluate(() => JSON.parse(document.querySelector('#manifest').textContent).chapters[0].keyframes[1].time);
  await page.locator('#audio').evaluate((audio, time) => { audio.currentTime = time + 0.05; }, secondTime);
  await page.waitForFunction((first) => document.querySelector('#frame').getAttribute('src') !== first, first);
  await page.selectOption('#rate', '1.5');
  await page.selectOption('#chapters', '1');
  await page.waitForFunction(() => document.querySelector('#audio').readyState >= 1);
  const result = await page.evaluate(() => ({
    chapter: document.querySelector('#chapters').value,
    rate: document.querySelector('#audio').playbackRate,
    duration: document.querySelector('#audio').duration,
    image: document.querySelector('#frame').getAttribute('src'),
    error: document.querySelector('#error').textContent,
  }));
  if (result.chapter !== '1' || result.rate !== 1.5 || !(result.duration > 0) || result.error) throw Error(JSON.stringify(result));
  console.log(JSON.stringify({ seekSwitchedImage: true, ...result }));
} finally { await browser.close(); }
