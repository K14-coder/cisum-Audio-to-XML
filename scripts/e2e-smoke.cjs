// End-to-end smoke test of the web app against a running server.
//   CISUM_ADMIN_EMAILS=admin@example.com uvicorn cisum.api.main:app   (fresh database)
//   python -m tests.synth out/song   (in backend/)
//   node scripts/e2e-smoke.cjs backend/out/song/mix.wav
// Needs Playwright with Chromium (npm i -g playwright && npx playwright install chromium).
const { chromium } = require('playwright');
const path = require('path');

const BASE = process.env.CISUM_URL || 'http://localhost:8000';
const SONG = process.argv[2];
const SHOTS = path.dirname(SONG);
const RUN = Date.now();
const log = (...a) => console.log('•', ...a);

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

  // Register
  await page.goto(BASE + '/register');
  await page.fill('input[type=email]', `player${RUN}@example.com`);
  await page.fill('input[type=password]', 'piano-lover-1');
  await page.click('button[type=submit]');
  await page.waitForURL(BASE + '/');
  log('registered, at library');

  // Upload with rights checkbox
  await page.click('text=New song');
  await page.waitForSelector('text=Only upload music you have the rights to.');
  await page.setInputFiles('input[type=file]', SONG);
  const titleInput = page.locator('label:has-text("Title") input').first();
  await titleInput.fill('Synthetic Test Song');
  const submit = page.locator('button[type=submit]');
  if (!(await submit.isDisabled())) throw new Error('submit should be disabled before the rights box is ticked');
  await page.check('input[type=checkbox]');
  await submit.click();
  await page.waitForURL(/\/songs\//, { timeout: 30000 });
  log('uploaded, waiting for processing at', page.url());
  await page.screenshot({ path: path.join(SHOTS, 'e2e-progress.png') });

  // Wait for the viewer (sheet music svg from OSMD)
  await page.waitForSelector('svg g', { timeout: 300000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: path.join(SHOTS, 'e2e-sheet.png'), fullPage: false });
  log('sheet music rendered');

  // Difficulty switch
  for (const level of ['Easy', 'Hard', 'Medium']) {
    await page.getByRole('radio', { name: level, exact: true }).first().click();
    await page.waitForTimeout(2500);
  }
  log('switched levels');

  // Letter names + falling notes tabs, with playback
  await page.getByRole('tab', { name: /Letter names/ }).click();
  await page.waitForTimeout(500);
  await page.screenshot({ path: path.join(SHOTS, 'e2e-letters.png') });
  await page.getByRole('tab', { name: /Falling notes/ }).click();
  await page.getByRole('button', { name: /Play$/ }).first().click();
  await page.waitForTimeout(3000);
  await page.screenshot({ path: path.join(SHOTS, 'e2e-falling.png') });
  await page.getByRole('button', { name: /Stop$/ }).first().click();
  await page.getByRole('tab', { name: /Sheet music/ }).click();
  log('letter names + falling notes + playback ok');

  // Downloads
  for (const label of ['PDF', 'MIDI', 'MusicXML']) {
    const link = page.getByRole('link', { name: new RegExp(label) }).first();
    const href = await link.getAttribute('href');
    const res = await page.request.get(BASE + href);
    if (!res.ok()) throw new Error(`${label} download failed: ${res.status()}`);
    log(`${label} download`, res.status(), (await res.body()).length, 'bytes');
  }

  // Chord editor: change the first chord
  await page.getByRole('button', { name: /Edit chords/ }).click();
  const firstChord = page.getByLabel(/^Chord at/).first();
  await firstChord.waitFor();
  const before = await firstChord.inputValue();
  await firstChord.fill('Hzz');
  await page.getByRole('button', { name: /^Save/ }).click();
  await page.waitForSelector('text=Hzz', { timeout: 10000 });
  log('invalid chord rejected');
  await firstChord.fill(before === 'Am' ? 'C' : 'Am');
  await page.getByRole('button', { name: /^Save/ }).click();
  await page.waitForTimeout(3000);
  log(`edited first chord ${before} -> ${before === 'Am' ? 'C' : 'Am'}`);

  // Share
  await page.getByRole('button', { name: /^Share/ }).first().click();
  await page.getByRole('button', { name: /Create|Share link|Make link/ }).first().click();
  const linkInput = page.getByLabel('Share link');
  await linkInput.waitFor({ timeout: 10000 });
  const shareUrl = await linkInput.inputValue();
  log('share link', shareUrl);
  await page.keyboard.press('Escape');

  // Public view in a fresh, logged-out context
  const anon = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const pub = await anon.newPage();
  pub.on('pageerror', (e) => errors.push('public pageerror: ' + e.message));
  await pub.goto(shareUrl);
  await pub.waitForSelector('svg g', { timeout: 30000 });
  await pub.waitForTimeout(1000);
  await pub.screenshot({ path: path.join(SHOTS, 'e2e-public-phone.png') });
  log('public page renders on phone width');

  // Report it as infringing
  await pub.getByRole('button', { name: /Report/ }).first().click();
  await pub.getByLabel(/Your name/).fill('Rights Holder');
  await pub.getByLabel(/Your email/).fill('rights@example.com');
  await pub.locator('textarea').fill('This arrangement is of my song.');
  const boxes = pub.locator('dialog input[type=checkbox], [role=dialog] input[type=checkbox]');
  if (await boxes.count()) await boxes.first().check();
  await pub.getByRole('button', { name: /Send|Submit/ }).click();
  await pub.waitForSelector('text=received your report', { timeout: 10000 });
  log('report submitted');
  const hidden = await pub.request.get(BASE + '/api/public/shares/' + shareUrl.split('/s/')[1]);
  if (hidden.status() !== 404) throw new Error('share should be hidden after a copyright report');
  log('share hidden pending review');

  // Admin upholds
  const adminCtx = await browser.newContext();
  const admin = await adminCtx.newPage();
  admin.on('dialog', (d) => d.accept());
  await admin.goto(BASE + '/register');
  await admin.fill('input[type=email]', 'admin@example.com');
  await admin.fill('input[type=password]', 'admin-password-1');
  await admin.click('button[type=submit]');
  await admin.waitForURL(BASE + '/');
  await admin.goto(BASE + '/admin/reports');
  await admin.getByRole('button', { name: /Uphold/ }).first().click();
  await admin.waitForTimeout(1500);
  await admin.screenshot({ path: path.join(SHOTS, 'e2e-admin.png') });
  const me = await (await page.request.get(BASE + '/api/auth/me')).json();
  log('uploader strikes after uphold:', me.strikes);
  if (me.strikes !== 1) throw new Error('expected one strike');

  const realErrors = errors.filter((e) => !/401|Failed to load resource|tonejs|salamander|sample/i.test(e));
  console.log('\nbrowser errors:', realErrors.length ? realErrors : 'none');
  await browser.close();
  process.exit(realErrors.length ? 1 : 0);
})().catch(async (e) => { console.error('E2E FAILED:', e.message); process.exit(1); });
