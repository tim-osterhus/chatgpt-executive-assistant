const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
test('original consumer is silent/owned, capture source is original, and teardown never stops the SDK original',async()=>{
  const audio=[],sources=[];let originalStops=0,quietStops=0;
  const original={getTracks:()=>[{stop:()=>{originalStops++;}}]};
  class Context {
    constructor(){this.state='running';this.sampleRate=48000;this.audioWorklet={addModule:async()=>{}};}
    async resume(){} async close(){this.state='closed';}
    createMediaStreamDestination(){return{stream:{clone(){return this;},getTracks:()=>[{stop:()=>{quietStops++;}}]}};}
    createMediaStreamSource(stream){sources.push(stream);return{connect(){},disconnect(){}};}
  }
  class Audio {constructor(){audio.push(this);}async play(){this.played=true;}pause(){this.paused=true;}}
  class Worklet {constructor(){this.port={};}connect(){}disconnect(){}}
  const realm=vm.createContext({AudioContext:Context,Audio,AudioWorkletNode:Worklet});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../runtime/sdk/media.js'),'utf8').replace('export class PcmMedia','globalThis.PcmMedia = class PcmMedia'),realm);
  const media=new realm.PcmMedia({bootstrapOriginal:true,onPcm(){},onFailure(){},onClock(){}});await media.open();
  const quiet=await media.remoteProcessor.createProcessedStream(original);
  assert.equal(audio.length,1);assert.equal(audio[0].srcObject,original);assert.equal(audio[0].volume,0);assert.equal(audio[0].muted,false);
  assert.equal(sources[0],original);assert.notEqual(quiet,original);
  await media.close();assert.equal(audio[0].srcObject,null);assert.equal(audio[0].paused,true);
  assert.equal(originalStops,0);assert.equal(quietStops,2);
});
