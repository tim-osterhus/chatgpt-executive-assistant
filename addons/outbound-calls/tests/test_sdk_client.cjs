const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../runtime/sdk/client.js'),'utf8').replace("import {PcmMedia} from '/media.js';",'');
async function setup(){
  let sock,active,connections=0;const sent=[];
  class Media{
    constructor(options){this.options=options;this.context={sampleRate:48000};this.remoteProcessor={};this.inputRequests=0;}
    async open(){this.options.onClock({type:'clock',sampleRate:48000});}
    async generatedInput(){this.inputRequests++;return {};}
    async close(){this.closed=true;}
  }
  class Call{constructor(){this.handlers={};}on(k,f){this.handlers[k]=f;}disconnect(){this.disconnected=true;}}
  class Device{
    static Codec={Opus:'opus'};
    constructor(token,options){this.options=options;this.audio={addProcessor:async()=>{},setInputDevice:async()=>options.getUserMedia()};}
    on(){}async connect(){connections++;active=new Call();return active;}destroy(){this.destroyed=true;}
  }
  class Socket{
    static OPEN=1;
    constructor(){sock=this;this.readyState=1;queueMicrotask(()=>this.onopen());}
    send(value){if(typeof value==='string')sent.push(JSON.parse(value));}
    close(){this.readyState=3;this.onclose();}
  }
  const realm=vm.createContext({window:{},location:{hash:'#test',origin:'http://127.0.0.1:123'},navigator:{mediaDevices:{}},
    PcmMedia:Media,Twilio:{Device,Call:{Codec:{Opus:'opus'}}},WebSocket:Socket,
    fetch:async()=>({ok:true,json:async()=>({token:'fake',request_id:'exact'})}),DOMException,ArrayBuffer,DataView,Uint8Array,JSON});
  vm.runInContext(source,realm);const running=realm.window.runOwnedRenderer();
  await new Promise(setImmediate);
  const command=async value=>{await sock.onmessage({data:JSON.stringify(value)});};
  await command({type:'connect'});
  return {sent,command,get call(){return active;},get connections(){return connections;},running};
}
test('accept unknown stays pending; actual later sample Opus is reported; closing stops later samples',async()=>{
  const p=await setup();p.call.handlers.accept();await Promise.resolve();
  assert.equal(p.sent.filter(x=>x.type==='codec').length,0);
  p.call.handlers.sample({codecName:'opus'});await Promise.resolve();
  assert.equal(p.sent.filter(x=>x.type==='codec'&&x.codec==='opus').length,1);
  await p.command({type:'stop'});await p.running;
  p.call.handlers.sample({codecName:'pcmu'});await Promise.resolve();
  assert.equal(p.sent.filter(x=>x.type==='codec').length,1);assert.equal(p.connections,1);
});
test('explicit PCMU closes and never accepts fallback',async()=>{
  const p=await setup();p.call.handlers.sample({codecName:'pcmu'});await p.running;
  assert.ok(p.sent.some(x=>x.type==='failure'&&x.reason==='unsupported_codec'));assert.equal(p.connections,1);
});
test('second connect command cannot dial again',async()=>{
  const p=await setup();await p.command({type:'connect'});await p.running;
  assert.equal(p.connections,1);assert.ok(p.sent.some(x=>x.type==='failure'));
});
