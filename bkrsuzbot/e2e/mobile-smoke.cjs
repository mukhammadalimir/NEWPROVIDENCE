// Проверка Mini App на экране телефона (Playwright). API должен быть запущен с APP_ENV=dev:
//   APP_ENV=dev DEV_AUTH_USER_ID=1000 ADMIN_IDS=1000 uvicorn app.api.main:app --port 8000
//   node e2e/mobile-smoke.cjs   (переменные BASE_URL, SHOTS_DIR — необязательно)
// В блоке «озвучка» ответ /api/tts подменяется в браузере: проверяются кнопки и запросы, а не Google.
const {chromium, devices} = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:8000';
const S = (process.env.SHOTS_DIR || __dirname + '/shots') + '/';
fs.mkdirSync(S, {recursive: true});
(async () => {
  const b = await chromium.launch();
  const log = [];
  const ok = (name, cond) => { log.push((cond ? 'PASS ' : 'FAIL ') + name); };
  const ctx = await b.newContext({...devices['iPhone 13'], colorScheme: 'light'});
  const p = await ctx.newPage();
  await p.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  p.on('pageerror', e => log.push('PAGEERROR ' + e.message));
  await p.goto(BASE + '/');
  await p.waitForSelector('.search-box input');
  await p.screenshot({path: S + '01-home.png'});

  const search = async (q) => {
    await p.fill('.search-box input', q);
    await p.click('button.btn.wide');
    await p.waitForSelector('.card:not(.skeleton), .state, .notice', {timeout: 10000});
    await p.waitForTimeout(150);
  };
  // 1. baliq
  await search('baliq');
  ok('baliq -> 鱼', (await p.textContent('.hanzi')) === '鱼');
  ok('baliq: trad 魚', (await p.textContent('.trad')).includes('魚'));
  ok('baliq: pinyin yú', (await p.textContent('.pinyin')) === 'yú');
  ok('baliq: collocation 海鱼', (await p.textContent('.word')).includes('海鱼'));
  ok('baliq: example', (await p.textContent('.word')).includes('Men baliq yeyishni yaxshi ko‘raman.'));
  ok('baliq: source badge', (await p.textContent('.word')).includes('Tahririyat'));
  ok('no audio buttons when TTS off', (await p.$$('.audio')).length === 0);
  await p.screenshot({path: S + '02-baliq.png', fullPage: true});

  // 2. 行 — несколько чтений
  await search('行');
  const readings = await p.$$eval('.reading .pinyin', els => els.map(e => e.textContent));
  ok('行 readings xíng/háng ' + readings.join(','), readings.includes('xíng') && readings.includes('háng'));
  await p.screenshot({path: S + '03-xing.png', fullPage: true});

  // 3. yu → выбор → пиньинь
  await search('yu');
  ok('yu asks direction', (await p.textContent('.card')).includes('Qaysi til'));
  await p.click('.choose button:first-child');
  await p.waitForSelector('.list-row.cand');
  const cands = await p.$$eval('.list-row.cand .zh', els => els.map(e => e.textContent));
  ok('yu candidates first 鱼: ' + cands.slice(0,5).join(''), cands[0] === '鱼');
  await p.screenshot({path: S + '04-yu.png', fullPage: true});
  await p.click('.list-row.cand >> nth=0');
  await p.waitForSelector('.hanzi');
  ok('candidate opens card', (await p.textContent('.hanzi')) === '鱼');

  // 4. предложение без ключа перевода
  await search('我喜欢吃鱼。');
  const txt = await p.textContent('main');
  ok('sentence: notice translate unavailable', txt.includes('ulanmagan'));
  ok('sentence: pinyin shown', txt.includes('wǒ'));
  await p.screenshot({path: S + '05-sentence-nokey.png', fullPage: true});

  // 5. избранное: добавить и удалить
  await search('鱼');
  await p.click('.reading .icon-btn.star >> nth=0');
  await p.waitForTimeout(300);
  ok('star toggled', (await p.$$('.reading .icon-btn.star.on')).length === 1);
  await p.click('.tabbar button >> nth=1');
  await p.waitForSelector('.fav');
  ok('favorite listed', (await p.textContent('.fav-list')).includes('鱼'));
  await p.screenshot({path: S + '06-favorites.png'});
  await p.click('.tabbar button >> nth=2');
  await p.waitForSelector('.flash');
  await p.click('.flash');
  await p.waitForSelector('.review-actions');
  await p.screenshot({path: S + '07-review.png'});
  await p.click('.tabbar button >> nth=1');
  await p.waitForSelector('.fav');
  await p.click('.fav .icon-btn[aria-label=delete]');
  await p.waitForSelector('.state');
  ok('favorite removed', (await p.textContent('main')).includes('Saqlangan so‘zlar yo‘q'));

  // 6. ошибка соединения
  await p.click('.tabbar button >> nth=0');
  await p.route('**/api/search', r => r.abort());
  await search('水');
  ok('network error state', (await p.textContent('main')).includes('Server bilan aloqa yo‘q'));
  await p.screenshot({path: S + '08-neterror.png'});
  await p.unroute('**/api/search');

  // 7. админка
  await p.click('.tabbar button >> nth=4');
  await p.waitForSelector('.stat-grid');
  await p.screenshot({path: S + '09-admin.png', fullPage: true});

  // 8. настройки
  await p.click('.tabbar button >> nth=3');
  await p.waitForSelector('.segmented');
  await p.screenshot({path: S + '10-settings.png', fullPage: true});

  // 9. озвучка в интерфейсе (сервис TTS подменён в браузере — проверка кнопок и запроса)
  const ctx2 = await b.newContext({...devices['iPhone 13'], colorScheme: 'dark'});
  const p2 = await ctx2.newPage();
  await p2.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  await p2.route('**/api/me', async r => { const res = await r.fetch(); const j = await res.json(); j.services.tts = true; r.fulfill({json: j}); });
  let ttsReq = null;
  await p2.route('**/api/tts?*', r => { ttsReq = r.request().url(); r.fulfill({body: fs.readFileSync(__dirname + '/beep.wav'), contentType: 'audio/wav'}); });
  await p2.goto(BASE + '/?q=' + encodeURIComponent('baliq'));
  await p2.waitForSelector('.hanzi');
  ok('deep link ?q= works', (await p2.textContent('.hanzi')) === '鱼');
  await p2.click('.word-head .audio .icon-btn >> nth=0');
  await p2.waitForTimeout(500);
  ok('tts request sent for 鱼: ' + ttsReq, ttsReq && decodeURIComponent(ttsReq).includes('text=鱼'));
  await p2.click('.word-head .audio .icon-btn >> nth=1');
  await p2.waitForTimeout(300);
  ok('slow tts request', ttsReq && ttsReq.includes('slow=true'));
  ok('no error toast', (await p2.$$('.toast')).length === 0);
  await p2.screenshot({path: S + '11-dark-audio.png', fullPage: true});
  // ошибка TTS → понятное сообщение
  await p2.unroute('**/api/tts?*');
  await p2.route('**/api/tts?*', r => r.fulfill({status: 503, json: {detail: {code: 'tts_failed'}}}));
  await p2.click('.example .audio .icon-btn >> nth=0');
  await p2.waitForSelector('.toast');
  ok('tts failure toast: ' + await p2.textContent('.toast'), (await p2.textContent('.toast')).includes('Ovozni'));

  // 10. Без Telegram в prod-режиме — экран «откройте в Telegram» (имитация 401)
  const p3 = await ctx.newPage();
  await p3.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  await p3.route('**/api/me', r => r.fulfill({status: 401, json: {detail: {code: 'unauthorized'}}}));
  await p3.goto(BASE + '/');
  await p3.waitForSelector('.state');
  ok('401 -> open in Telegram', (await p3.textContent('.state')).includes('Telegram'));
  await b.close();
  console.log(log.join('\n'));
})();
