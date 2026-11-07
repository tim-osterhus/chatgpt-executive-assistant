// Product-owned renderer. No attachment to an existing browser/profile/CDP endpoint.
const {chromium} = require('playwright-core');
const fs = require('node:fs');
let input = '';
process.stdin.on('data', chunk => input += chunk);
process.stdin.on('end', async () => {
  let server, browser;
  try {
    const config = JSON.parse(input);
    if (!/^http:\/\/127\.0\.0\.1:\d+$/.test(config.origin)) throw new Error('loopback_origin_required');
    if (!fs.existsSync(config.profile) || fs.readdirSync(config.profile).length)
      throw new Error('new_owned_profile_required');
    // The user's existing installed Chrome, selected by the controller; never a downloaded browser.
    if (typeof config.executable !== 'string' || !config.executable.startsWith('/') || !fs.existsSync(config.executable))
      throw new Error('installed_chrome_executable_required');
    server = await chromium.launchServer({
      executablePath: config.executable,
      headless: true, chromiumSandbox: true, host: '127.0.0.1',
      ignoreDefaultArgs: config.headless_mute === false ? ['--mute-audio'] : [],
      // Only this fresh owned application process; does not grant microphone permission.
      args: ['--autoplay-policy=no-user-gesture-required'],
    });
    const child = server.process();
    const profileArgument = child.spawnargs.find(value => value.startsWith('--user-data-dir='));
    const profile = profileArgument && profileArgument.slice('--user-data-dir='.length);
    if (!profile || !profile.startsWith(config.profile + '/')) throw new Error('owned_profile_outside_private_temp');
    process.stdout.write(JSON.stringify({event:'renderer_process', pid:child.pid, profile,
      default_mute_audio:child.spawnargs.includes('--mute-audio')})+'\n');
    const close = () => server.close().catch(() => {});
    process.once('SIGTERM', close); process.once('SIGINT', close);
    browser = await chromium.connect(server.wsEndpoint());
    const context = await browser.newContext({permissions: []});
    const page = await context.newPage();
    page.on('pageerror', () => process.stdout.write(JSON.stringify({event:'renderer_page_error'})+'\n'));
    await page.goto(config.origin + '/#' + config.control, {waitUntil: 'load'});
    process.stdout.write(JSON.stringify({event:'renderer_started', browser_version:browser.version()})+'\n');
    await page.evaluate(() => window.runOwnedRenderer());
  } catch (error) {
    process.stdout.write(JSON.stringify({event:'renderer_failed', error_type:error.name})+'\n');
    process.exitCode = 1;
  } finally {
    if (browser) await browser.close().catch(() => { process.exitCode = 1; });
    if (server) await server.close().catch(() => { process.exitCode = 1; });
    process.stdout.write(JSON.stringify({event:'renderer_closed'})+'\n');
  }
});
