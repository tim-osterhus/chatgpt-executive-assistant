/* The same microphone-free48k media graph is used by calls and local qualification. */
export class PcmMedia {
  constructor({onPcm, onFailure, onClock, bootstrapOriginal=true}) {
    this.onPcm = onPcm; this.onFailure = onFailure; this.onClock = onClock;
    this.bootstrapOriginal = bootstrapOriginal;
    this.pending = new Map(); this.remoteNodes = new Set(); this.inputRequests = 0;
  }
  async open() {
    this.context = new AudioContext({sampleRate: 48000, latencyHint: 'interactive'});
    await this.context.resume();
    if (this.context.state !== 'running' || this.context.sampleRate !== 48000)
      throw new Error('owned_audio_context_not_running_48k');
    await this.context.audioWorklet.addModule('/pcm-worklet.js');
    this.destination = this.context.createMediaStreamDestination();
    this.destination.channelCount = 1;
    this.output = new AudioWorkletNode(this.context, 'phone-pcm', {
      numberOfInputs: 0, numberOfOutputs: 1, outputChannelCount: [1],
      processorOptions: {mode: 'outgoing'}});
    this.output.connect(this.destination);
    this.output.port.onmessage = ({data}) => {
      if (data.type === 'failure') this.fail(data.reason);
      else if (data.type === 'clock') this.onClock(data);
      else if (data.type === 'drained') {
        const waiter = this.pending.get(data.id);
        if (waiter) { this.pending.delete(data.id); waiter.resolve(data); }
      }
    };
    // One supported remote AudioProcessor, installed before SDK media starts.
    this.remoteProcessor = {
      createProcessedStream: async original => {
        let consumer = null;
        if (this.bootstrapOriginal) {
          consumer = new Audio(); consumer.srcObject = original;
          consumer.muted = false; consumer.volume = 0;
          await consumer.play();
        }
        const source = this.context.createMediaStreamSource(original);
        const capture = new AudioWorkletNode(this.context, 'phone-pcm', {
          numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
          processorOptions: {mode: 'capture'}});
        const quiet = this.context.createMediaStreamDestination(); quiet.channelCount = 1;
        capture.port.onmessage = ({data}) => {
          if (data.type === 'capture') this.onPcm(data);
          else if (data.type === 'failure') this.fail(data.reason);
        };
        source.connect(capture); capture.connect(quiet);
        const owned = {source, capture, quiet, consumer}; this.remoteNodes.add(owned);
        return quiet.stream; // SDK speaker receives SILENCE, never original phone audio.
      },
      destroyProcessedStream: async stream => {
        for (const item of this.remoteNodes) {
          if (item.quiet.stream === stream) {
            item.source.disconnect(); item.capture.disconnect();
            if (item.consumer) { item.consumer.pause(); item.consumer.srcObject = null; }
            item.quiet.stream.getTracks().forEach(track => track.stop());
            this.remoteNodes.delete(item);
          }
        }
      },
    };
  }
  async generatedInput() {
    this.inputRequests++;
    this.lastInputStream = this.destination.stream.clone();
    return this.lastInputStream; // Never native getUserMedia.
  }
  write(seq, pcm) {
    if (!(pcm instanceof ArrayBuffer)) throw new Error('pcm_requires_array_buffer');
    this.output.port.postMessage({type: 'pcm', seq, pcm}, [pcm]);
  }
  drain(boundary) {
    if (this.failure) throw new Error(this.failure);
    if (this.pending.has(boundary.id)) throw new Error('duplicate_drain_id');
    const promise = new Promise((resolve, reject) => this.pending.set(boundary.id, {resolve, reject}));
    this.output.port.postMessage({type: 'drain', ...boundary});
    return promise;
  }
  fail(reason) {
    this.failure = reason; this.onFailure(reason);
    for (const waiter of this.pending.values()) waiter.reject(new Error(reason));
    this.pending.clear();
  }
  async close() {
    for (const waiter of this.pending.values()) waiter.reject(new Error('media_closed_before_drain'));
    this.pending.clear();
    for (const item of [...this.remoteNodes]) await this.remoteProcessor.destroyProcessedStream(item.quiet.stream);
    if (this.output) this.output.disconnect();
    if (this.destination) this.destination.stream.getTracks().forEach(track => track.stop());
    if (this.context) await this.context.close();
  }
}
