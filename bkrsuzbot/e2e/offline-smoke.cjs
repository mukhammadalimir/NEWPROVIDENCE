// Проверка автономной Mini App (bkrsuzbot/webapp, без сервера) на экране телефона.
//   python3 -m http.server 8090   (из корня репозитория)
//   BASE_URL=http://localhost:8090/bkrsuzbot/webapp/ node bkrsuzbot/e2e/offline-smoke.cjs
// Голоса телефона в headless-браузере нет, поэтому speechSynthesis подменяется
// (проверяются кнопки и вызовы, а не качество звука).
const {chromium, devices} = require('playwright');
const fs = require('fs');
const BASE = process.env.BASE_URL || 'http://localhost:8090/bkrsuzbot/webapp/';
const S = (process.env.SHOTS_DIR || __dirname + '/shots') + '/offline-';
fs.mkdirSync(__dirname + '/shots', {recursive: true});

const fakeVoice = () => {
  window.__spoken = [];
  const voice = {name: 'Tingting', lang: 'zh-CN', default: true, localService: true, voiceURI: 'tt'};
  Object.defineProperty(window, 'speechSynthesis', {value: {
    getVoices: () => [voice], speak: (u) => window.__spoken.push([u.text, u.rate]), cancel() {},
    addEventListener() {},
  }});
  window.SpeechSynthesisUtterance = function (t) { this.text = t; };
};

(async () => {
  const b = await chromium.launch();
  const log = [];
  const ok = (name, cond) => log.push((cond ? 'PASS ' : 'FAIL ') + name);
  const ctx = await b.newContext({...devices['iPhone 13']});
  await ctx.addInitScript(fakeVoice);
  const p = await ctx.newPage();
  await p.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  p.on('pageerror', e => log.push('PAGEERROR ' + e.message));
  await p.goto(BASE);
  await p.waitForSelector('.search-box input');
  const search = async (q) => {
    await p.fill('.search-box input', q);
    await p.click('button.btn.wide');
    await p.waitForSelector('.card:not(.skeleton), .state, .notice', {timeout: 30000});
    await p.waitForTimeout(100);
  };
  const t0 = Date.now();
  await search('baliq');
  log.push('INFO first search incl. dictionary load: ' + (Date.now() - t0) + ' ms');
  ok('baliq -> 鱼 / 魚', (await p.textContent('.hanzi')) === '鱼' && (await p.textContent('.trad')).includes('魚'));
  ok('baliq: yú + 条', (await p.textContent('.pinyin')) === 'yú' && (await p.textContent('.word')).includes('条 (tiáo)'));
  ok('baliq: 海鱼 + example', (await p.textContent('.word')).includes('海鱼') && (await p.textContent('.word')).includes('Men baliq yeyishni'));
  ok('no report button offline', !(await p.textContent('.word')).includes('Xato haqida'));
  await p.screenshot({path: S + 'baliq.png', fullPage: true});

  await p.click('.word-head .audio .icon-btn >> nth=0');
  await p.click('.word-head .audio .icon-btn >> nth=1');
  const spoken = await p.evaluate(() => window.__spoken);
  ok('device voice speaks 鱼 normal+slow ' + JSON.stringify(spoken), spoken.length === 2 && spoken[0][0] === '鱼' && spoken[1][1] < spoken[0][1]);

  await search('鱼');
  ok('鱼 card', (await p.textContent('.hanzi')) === '鱼');
  await search('yu2');
  const c2 = await p.$$eval('.list-row.cand .zh', els => els.map(e => e.textContent));
  ok('yu2 candidates ' + c2.slice(0, 5).join(''), c2[0] === '鱼' && !c2.includes('语'));
  await search('yú');
  ok('yú candidates', (await p.$$eval('.list-row.cand .zh', els => els[0].textContent)) === '鱼');
  await search('yu');
  ok('yu asks', (await p.textContent('.card')).includes('Qaysi til'));
  await p.click('.choose button:first-child');
  await p.waitForSelector('.list-row.cand');
  ok('yu -> pinyin list incl 语', (await p.$$eval('.list-row.cand .zh', els => els.map(e => e.textContent))).includes('语'));
  await search('行');
  const rd = await p.$$eval('.reading .pinyin', els => els.map(e => e.textContent));
  ok('行 readings ' + rd.join(','), rd.includes('xíng') && rd.includes('háng'));
  const blocks = await p.$$eval('.reading', els => els.map(e => e.textContent));
  ok('银行 under háng only', blocks.find(t => t.startsWith('háng')).includes('银行') && !blocks.find(t => t.startsWith('xíng')).includes('银行'));
  await search("o'qimoq");
  ok("o'qimoq -> 学习", (await p.textContent('.hanzi')) === '学习');
  await search('ўқимоқ');
  ok('ўқимоқ -> 学习', (await p.textContent('.hanzi')) === '学习');
  await search('рыба');
  ok('рыба -> 鱼', (await p.textContent('.hanzi')) === '鱼');
  // Wiktionary: русские/узбекские слова, которых нет в карточках редакции
  await search('осень');
  const os = await p.$$eval('.list-row.cand', els => els.map(e => e.textContent));
  ok('осень -> 秋天 first (Wiktionary) ' + os.slice(0, 2).join(' | '), os[0]?.includes('秋天') && os[0]?.includes('осень'));
  await search('небо');
  const nb = await p.$$eval('.list-row.cand .zh', els => els.map(e => e.textContent));
  ok('небо -> 天 / 天空 ' + nb.slice(0, 3).join(','), nb[0] === '天' && nb.includes('天空'));
  await p.click('.list-row.cand >> nth=1');
  await p.waitForSelector('.hanzi');
  ok('天空 card has Russian meaning + Wiktionary label', (await p.textContent('.word')).includes('небо') && (await p.textContent('.word')).includes('Wiktionary'));
  await p.screenshot({path: S + 'wikt-card.png', fullPage: true});
  await search('kuz');
  ok('kuz -> 秋天', (await p.$$eval('.list-row.cand .zh', els => els[0].textContent)) === '秋天');
  ok('target selector follows the query language (ru)', (await p.inputValue('select[aria-label=to]')) === 'ru');
  await p.selectOption('select[aria-label=to]', 'uz');
  await search('秋天');
  ok('秋天 card (uz) shows kuz', (await p.textContent('.word')).includes('kuz'));
  await search('我喜欢吃鱼。');
  const txt = await p.textContent('main');
  ok('sentence: pinyin + words + honest notice', txt.includes('wǒ xǐhuan chī yú') && txt.includes('ulanmagan') && txt.includes('喜欢'));
  await p.screenshot({path: S + 'sentence.png', fullPage: true});
  await search('Bugun havo yaxshi');
  ok('uz phrase w/o MT -> not found + notice', (await p.textContent('main')).includes('Hech narsa topilmadi'));

  await search('鱼');
  await p.click('.reading .icon-btn.star >> nth=0');
  await p.click('.tabbar button >> nth=1');
  await p.waitForSelector('.fav');
  ok('favorite saved', (await p.textContent('.fav-list')).includes('鱼'));
  await p.reload();
  await p.waitForSelector('.tabbar');
  await p.click('.tabbar button >> nth=1');
  await p.waitForSelector('.fav');
  ok('favorite persists after reload', (await p.textContent('.fav-list')).includes('鱼'));
  await p.click('.tabbar button >> nth=2');
  await p.waitForSelector('.flash');
  await p.click('.flash');
  await p.click('.review-actions .btn:not(.secondary)');
  await p.click('.tabbar button >> nth=1');
  await p.waitForSelector('.fav');
  await p.click('.fav .icon-btn[aria-label=delete]');
  await p.waitForSelector('.state');
  ok('favorite removed', (await p.textContent('main')).includes('yo‘q'));
  await p.click('.tabbar button >> nth=3');
  await p.waitForSelector('.segmented');
  ok('settings offline note', (await p.textContent('main')).includes('Oflayn rejim'));
  ok('no admin tab', (await p.$$('.tabbar button')).length === 4);
  await p.screenshot({path: S + 'settings.png', fullPage: true});

  // Без голоса на устройстве кнопки озвучки скрыты
  const p2 = await (await b.newContext({...devices['Pixel 7'], colorScheme: 'dark'})).newPage();
  await p2.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  await p2.goto(BASE + '?q=' + encodeURIComponent('学习'));
  await p2.waitForSelector('.hanzi', {timeout: 30000});
  ok('deep link ?q= (Android, dark)', (await p2.textContent('.hanzi')) === '学习');
  ok('no voice -> no audio buttons', (await p2.$$('.audio')).length === 0);
  await p2.screenshot({path: S + 'android-dark.png', fullPage: true});

  // Нет сети при загрузке словаря → понятная ошибка
  const p3 = await (await b.newContext({...devices['iPhone 13']})).newPage();
  await p3.route('https://telegram.org/**', r => r.fulfill({body: ''}));
  await p3.route('**/data/cedict.json', r => r.abort());
  await p3.goto(BASE);
  await p3.waitForSelector('.search-box input');
  await p3.fill('.search-box input', '鱼');
  await p3.click('button.btn.wide');
  await p3.waitForSelector('.state');
  ok('dictionary download error shown', (await p3.textContent('.state')).includes('Server bilan aloqa'));
  await b.close();
  console.log(log.join('\n'));
})();
