import {PcmMedia} from '/media.js';

// Private autonomous application; no test buttons, physical microphone or user profile.
window.runOwnedRenderer = async () => {
  const control=location.hash.slice(1); let socket,device,call,media;
  let stopping=false,connectedOnce=false,readySent=false,lastClock,observedCodec;
  let finishResolve; const finished=new Promise(resolve=>{finishResolve=resolve;});
  const send=data=>{if(socket&&socket.readyState===WebSocket.OPEN)socket.send(JSON.stringify(data));};
  const ready=()=>{
    if(!readySent&&socket&&socket.readyState===WebSocket.OPEN&&lastClock&&media.inputRequests){
      readySent=true;send({type:'ready',sample_rate:media.context.sampleRate,input_requests:media.inputRequests});
    }
  };
  async function close(reason,failed=false){
    if(stopping)return;stopping=true;
    if(failed)send({type:'failure',reason});
    const active=call;call=null;if(active)active.disconnect();
    if(device){device.destroy();device=null;}
    if(media)await media.close();
    if(socket&&socket.readyState===WebSocket.OPEN)socket.close();
    finishResolve();
  }
  async function codec(value){
    if(typeof value!=='string'||!value||value===observedCodec)return;
    observedCodec=value;send({type:'codec',codec:value});
    if(value!=='opus')await close('unsupported_codec',true);
  }
  try {
    navigator.mediaDevices.getUserMedia=async()=>{throw new DOMException('Physical microphone forbidden','NotAllowedError');};
    const response=await fetch('/config',{method:'POST',headers:{'X-Renderer-Control':control}});
    if(!response.ok)throw new Error('configuration_unavailable');
    const config=await response.json();
    media=new PcmMedia({
      onPcm:frame=>{
        if(stopping)return;
        if(!socket||socket.readyState!==WebSocket.OPEN||socket.bufferedAmount>192400){close('remote_pcm_backpressure',true);return;}
        const packet=new Uint8Array(4+frame.pcm.byteLength);new DataView(packet.buffer).setUint32(0,frame.seq,true);
        packet.set(new Uint8Array(frame.pcm),4);socket.send(packet.buffer);
      },
      onFailure:reason=>close(reason,true),
      onClock:frame=>{lastClock=frame;send(frame);ready();},
    });
    await media.open();
    device=new Twilio.Device(config.token,{
      codecPreferences:[Twilio.Call.Codec.Opus],maxAverageBitrate:40000,logLevel:'silent',
      maxCallSignalingTimeoutMs:0,closeProtection:false,
      getUserMedia:()=>media.generatedInput(),
      enumerateDevices:async()=>[{deviceId:'default',groupId:'generated',kind:'audioinput',label:'Generated PCM'}],
    });
    device.on('error',()=>close('sdk_device_failed',true));
    // Supported sound toggles; the only SDK speaker stream is processed silence.
    for(const name of ['incoming','outgoing','disconnect'])if(typeof device.audio[name]==='function')device.audio[name](false);
    await device.audio.addProcessor(media.remoteProcessor,true);
    await device.audio.setInputDevice('default');
    socket=new WebSocket(location.origin.replace('http:','ws:')+'/pcm',['sdk-pcm',control]);
    socket.binaryType='arraybuffer';socket.onopen=ready;
    socket.onmessage=async event=>{
      try {
        if(event.data instanceof ArrayBuffer){
          if(stopping)return;
          if(event.data.byteLength!==1924)throw new Error('pcm_frame_size');
          media.write(new DataView(event.data).getUint32(0,true),event.data.slice(4));return;
        }
        const data=JSON.parse(event.data);
        if(data.type==='connect'){
          if(stopping||connectedOnce)throw new Error('connect_already_consumed');
          connectedOnce=true;
          call=await device.connect({params:{Intent:config.request_id},rtcConstraints:{audio:{
            echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false}});
          const current=call;
          call.on('accept',()=>{if(call===current)codec(current.codec);});
          call.on('sample',sample=>{if(call===current)codec(sample.codecName||current.codec);});
          call.on('error',()=>close('sdk_call_failed',true));
          call.on('disconnect',()=>{send({type:'disconnected'});close('sdk_disconnected');});
          call.on('cancel',()=>{send({type:'disconnected'});close('sdk_canceled');});
        }else if(data.type==='drain'){
          const acknowledgement=await media.drain(data);
          if(!stopping)send(acknowledgement);
        }else if(data.type==='stop')await close('coordinator_stop');
        else throw new Error('unexpected_control');
      }catch(_){await close('renderer_protocol_failed',true);}
    };
    socket.onerror=()=>close('local_socket_failed',true);
    socket.onclose=()=>close('local_socket_closed');
    await finished;
  }catch(_){await close('renderer_initialization_failed',true);throw new Error('owned_renderer_failed');}
};
