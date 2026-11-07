const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const CHROME='/Applications/Example Chrome.app/Contents/MacOS/Google Chrome';
async function run(fail=false,headlessMute=true,executable=CHROME){
  const handlers={},events=[],seen={};
  const server={process:()=>({pid:321,spawnargs:['chrome','--user-data-dir=/owned/tmp/new-profile']}),
    wsEndpoint:()=> 'ws://127.0.0.1/owned-only',close:async()=>{seen.serverClosed=true;}};
  const page={on(){},goto:async url=>{seen.url=url;},evaluate:async()=>{if(fail)throw new Error('sensitive-error-not-for-log');}};
  const browser={version:()=> 'fixture',newContext:async options=>{seen.context=options;return{newPage:async()=>page};},close:async()=>{seen.browserClosed=true;}};
  const chromium={launchServer:async options=>{seen.launch=options;return server;},connect:async url=>{seen.endpoint=url;return browser;}};
  const process={stdin:{on:(event,fn)=>{handlers[event]=fn;}},stdout:{write:line=>events.push(JSON.parse(line))},once(){}};
  const realm=vm.createContext({process,require:name=>name==='playwright-core'?{chromium}:name==='node:fs'?{existsSync:value=>value!=='/missing/chrome',readdirSync:()=>[]}:null});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../runtime/sdk/driver.cjs'),'utf8'),realm);
  handlers.data(JSON.stringify({origin:'http://127.0.0.1:12345',profile:'/owned/tmp',control:'private-local-control',headless_mute:headlessMute,executable}));await handlers.end();
  return{seen,events,process};
}
test('owned renderer uses a fresh isolated sandboxed engine and closes browser/server',async()=>{
  const {seen,events}=await run();assert.equal(seen.launch.chromiumSandbox,true);assert.equal(seen.launch.host,'127.0.0.1');
  assert.equal(seen.launch.headless,true);assert.equal(seen.context.permissions.length,0);
  assert.ok(!seen.launch.args.some(arg=>/no-sandbox|fake-ui|fake-device|disable-web-security/.test(arg)));
  assert.ok(seen.browserClosed&&seen.serverClosed);assert.equal(events.at(-1).event,'renderer_closed');
});
test('page failure still closes owned browser and logs only safe error type',async()=>{
  const {seen,events,process}=await run(true);assert.ok(seen.browserClosed&&seen.serverClosed);assert.equal(process.exitCode,1);
  assert.ok(!JSON.stringify(events).includes('sensitive-error'));assert.equal(events.at(-2).event,'renderer_failed');
});
test('mute A/B drops only the owned audio-output flag and retains sandbox/no permissions',async()=>{
  const on=await run();const off=await run(false,false);
  assert.equal(on.seen.launch.ignoreDefaultArgs.length,0);
  assert.deepEqual(Array.from(off.seen.launch.ignoreDefaultArgs),['--mute-audio']);
  assert.equal(off.seen.launch.chromiumSandbox,true);assert.equal(off.seen.context.permissions.length,0);
});
test('controller-selected installed Chrome is the only engine, and an unusable path never launches',async()=>{
  const {seen}=await run();assert.equal(seen.launch.executablePath,CHROME);
  for(const executable of ['relative/chrome','/missing/chrome',null]){
    const {seen:other,events}=await run(false,true,executable);
    assert.equal(other.launch,undefined);assert.equal(events.at(-2).event,'renderer_failed');
  }
});
