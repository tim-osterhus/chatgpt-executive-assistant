const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
function make(mode='outgoing', rate=48000) {
  let Type; const messages=[];
  class Base { constructor(){this.port={postMessage:message=>messages.push(message)};} }
  const realm=vm.createContext({AudioWorkletProcessor:Base,sampleRate:rate,currentFrame:0,currentTime:0,
    registerProcessor:(_,type)=>{Type=type;}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../runtime/sdk/pcm-worklet.js'),'utf8'),realm);
  const node=new Type({processorOptions:{mode}});
  return {node,messages,send:data=>node.port.onmessage({data}),step:input=>{
    const output=new Float32Array(128);node.process(input||[],[[output]]);
    realm.currentFrame+=128;realm.currentTime=realm.currentFrame/48000;return output;}};
}
test('finite ordered PCM preserves exact level/order and drains padding after every source sample',()=>{
  const f=make();const expected=[];
  for(let seq=1;seq<=4;seq++){const pcm=new Int16Array(960).fill(seq*1000);expected.push(...pcm);f.send({type:'pcm',seq,pcm:pcm.buffer});}
  f.send({type:'drain',id:'end',seq:4,samples:3840,finite:true,padding:960});
  const output=[];while(!f.messages.some(m=>m.type==='drained'))output.push(...f.step());
  assert.deepEqual(output.slice(0,3840),expected.map(value=>value/32768));
  assert.ok(output.slice(3840).every(value=>value===0));
  const ack=f.messages.find(m=>m.type==='drained');assert.equal(ack.consumed,3840);assert.equal(ack.padding,960);assert.equal(ack.seq,4);
  assert.equal(ack.renderedPeak,4000/32768);assert.ok(ack.renderedRms>0);assert.equal(ack.renderedSignalSamples,3840);
  f.send({type:'pcm',seq:5,pcm:new Int16Array(960).buffer});assert.equal(f.messages.at(-1).reason,'outgoing_pcm_order_or_format');
});
test('missing/duplicate frames and bounded queue overflow fail instead of fabricating a drain',()=>{
  const wrong=make();wrong.send({type:'pcm',seq:2,pcm:new Int16Array(960).buffer});assert.equal(wrong.messages[0].type,'failure');
  const full=make();for(let seq=1;seq<=51;seq++)full.send({type:'pcm',seq,pcm:new Int16Array(960).buffer});
  assert.equal(full.messages[0].reason,'outgoing_pcm_overflow');assert.equal(full.messages.some(m=>m.type==='drained'),false);
});
test('remote capture downmixes to48k PCM16 chunks while speaker output stays exactly silent',()=>{
  const f=make('capture');
  for(let i=0;i<8;i++){const out=f.step([[new Float32Array(128).fill(.125),new Float32Array(128).fill(.375)]]);assert.ok(out.every(value=>value===0));}
  const packet=f.messages.find(m=>m.type==='capture');assert.equal(packet.seq,1);
  const pcm=new Int16Array(packet.pcm);assert.equal(pcm.length,960);assert.ok(pcm.every(value=>value===8192));
  assert.equal(packet.inputPeakBeforeClear,.375);assert.equal(packet.inputPeakAtRead,.25);assert.equal(packet.inputOutputBufferShared,false);
  const bad=make('capture');bad.step([[new Float32Array(128).fill(NaN)]]);assert.equal(bad.messages[0].reason,'invalid_remote_audio_sample');
});
test('render clock is measured from real render quanta and wrong sample rate fails',()=>{
  const f=make();for(let i=0;i<750;i++)f.step();
  const clocks=f.messages.filter(m=>m.type==='clock');assert.equal(clocks.length,2);assert.ok(clocks[1].contextFrame>clocks[0].contextFrame);
  assert.equal(make('outgoing',44100).messages[0].reason,'audio_context_requires_48k');
});
