/* Owned renderer media:48k mono PCM16, bounded queues, no desktop output. */
'use strict';
class PhonePcm extends AudioWorkletProcessor {
  constructor(options) {
    super();
    this.mode = options.processorOptions.mode;
    this.queue = []; this.offset = 0; this.queued = 0;
    this.accepted = 0; this.consumed = 0; this.seq = 0;
    this.primed = false; this.sealed = false; this.failed = false;
    this.padding = 0; this.paddingDone = 0; this.barriers = [];
    this.underrunSamples = 0;
    this.rendered = 0; this.lastClock = 0;
    this.outputPeak = 0; this.outputEnergy = 0; this.outputSignal = 0;
    this.inputPeakBeforeClear = 0; this.inputPeakAtRead = 0; this.inputOutputBufferShared = false;
    this.capture = new Int16Array(960); this.captureOffset = 0; this.captureSeq = 0;
    if (sampleRate !== 48000) this.fail('audio_context_requires_48k');
    this.port.onmessage = ({data}) => {
      if (this.failed) return;
      if (data.type === 'pcm') {
        const pcm = new Int16Array(data.pcm);
        if (this.sealed || data.seq !== this.seq + 1 || pcm.length !== 960)
          return this.fail('outgoing_pcm_order_or_format');
        if (this.queued + pcm.length > 48000) return this.fail('outgoing_pcm_overflow');
        this.seq = data.seq; this.accepted += pcm.length; this.queued += pcm.length;
        this.queue.push(pcm);
      } else if (data.type === 'drain') {
        if (data.seq !== this.seq || data.samples !== this.accepted || this.sealed
            || !Number.isInteger(data.padding) || data.padding < 0 || data.padding > 96000)
          return this.fail('invalid_local_drain_boundary');
        if (data.finite) { this.sealed = true; this.padding = data.padding; }
        this.barriers.push(data);
      }
    };
  }
  fail(reason) {
    if (!this.failed) this.port.postMessage({type: 'failure', reason});
    this.failed = true;
  }
  process(inputs, outputs) {
    const output = outputs[0] && outputs[0][0];
    if (this.mode === 'capture') {
      for (const channel of inputs[0] || []) {
        if (output && channel.buffer === output.buffer) this.inputOutputBufferShared = true;
        for (const value of channel) this.inputPeakBeforeClear = Math.max(this.inputPeakBeforeClear, Math.abs(value));
      }
    }
    if (output) output.fill(0);
    if (this.failed) return true;
    if (this.mode === 'capture') {
      const channels = inputs[0] || [];
      if (!channels.length) return true;
      for (let i = 0; i < channels[0].length; i++) {
        let value = 0;
        for (const channel of channels) value += channel[i] / channels.length;
        this.inputPeakAtRead = Math.max(this.inputPeakAtRead, Math.abs(value));
        if (!Number.isFinite(value)) { this.fail('invalid_remote_audio_sample'); return true; }
        this.capture[this.captureOffset++] = Math.max(-32768, Math.min(32767, Math.round(value * 32768)));
        if (this.captureOffset === 960) {
          const pcm = this.capture.buffer;
          this.port.postMessage({type: 'capture', seq: ++this.captureSeq, pcm,
            inputPeakBeforeClear:this.inputPeakBeforeClear,inputPeakAtRead:this.inputPeakAtRead,
            inputOutputBufferShared:this.inputOutputBufferShared}, [pcm]);
          this.capture = new Int16Array(960); this.captureOffset = 0;
        }
      }
      return true; // All capture output is digital silence for SDK speaker playback.
    }
    if (!output) return true;
    this.rendered += output.length;
    if (this.rendered - this.lastClock >= 48000) {
      this.lastClock = this.rendered;
      this.port.postMessage({type: 'clock', sampleRate, contextFrame: currentFrame,
                             rendered: this.rendered, contextTime: currentTime});
    }
    if (this.queued >= 3840 || this.sealed || this.barriers.length) this.primed = true;
    for (let i = 0; i < output.length; i++) {
      if (!this.primed) break;
      if (this.queue.length) {
        output[i] = this.queue[0][this.offset++] / 32768;
        this.outputPeak = Math.max(this.outputPeak, Math.abs(output[i]));
        this.outputEnergy += output[i] * output[i];
        if (output[i] !== 0) this.outputSignal++;
        this.queued--; this.consumed++;
        if (this.offset === this.queue[0].length) { this.queue.shift(); this.offset = 0; }
      } else if (this.sealed && this.paddingDone < this.padding) {
        this.paddingDone++; // Quiet follows every source sample on this SAME render clock.
      } else if (!this.sealed) {
        this.underrunSamples++;
      }
    }
    while (this.barriers.length) {
      const boundary = this.barriers[0];
      if (this.consumed < boundary.samples || (boundary.finite && this.paddingDone < boundary.padding)) break;
      this.barriers.shift();
      this.port.postMessage({type: 'drained', id: boundary.id, seq: boundary.seq,
        accepted: this.accepted, consumed: this.consumed, padding: this.paddingDone,
        underrunSamples: this.underrunSamples, contextFrame: currentFrame,
        sampleRate, finite: boundary.finite,renderedPeak:this.outputPeak,
        renderedRms:Math.sqrt(this.outputEnergy/Math.max(1,this.consumed)),renderedSignalSamples:this.outputSignal});
    }
    return true;
  }
}
registerProcessor('phone-pcm', PhonePcm);
