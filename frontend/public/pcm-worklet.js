// AudioWorklet: mic -> 16 kHz mono s16le frames (40 ms) + a coarse VAD hint.
// Runs on the audio thread, so it stays allocation-light and dependency-free.
const TARGET_RATE = 16000;
const FRAME_SAMPLES = 640; // 40 ms at 16 kHz
const VAD_THRESHOLD = 0.02; // RMS
const VAD_ON_BLOCKS = 2; // ~5 ms blocks above threshold before "speaking"
const VAD_OFF_MS = 400;

class PcmCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.acc = 0;
    this.count = 0;
    this.out = new Int16Array(FRAME_SAMPLES);
    this.outLen = 0;
    this.loudBlocks = 0;
    this.quietSince = null;
    this.speaking = false;
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0];
    if (!input) return true;

    let sumSq = 0;
    for (let i = 0; i < input.length; i++) {
      const s = input[i];
      sumSq += s * s;
      // Box-filter decimation to 16 kHz.
      this.acc += s;
      this.count += 1;
      if (this.count >= this.ratio) {
        const v = Math.max(-1, Math.min(1, this.acc / this.count));
        this.out[this.outLen++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        this.acc = 0;
        this.count -= this.ratio;
        if (this.outLen === FRAME_SAMPLES) {
          const frame = this.out.slice().buffer;
          this.port.postMessage({ type: "pcm", buffer: frame }, [frame]);
          this.outLen = 0;
        }
      }
    }

    const rms = Math.sqrt(sumSq / input.length);
    if (rms > VAD_THRESHOLD) {
      this.loudBlocks += 1;
      this.quietSince = null;
      if (!this.speaking && this.loudBlocks >= VAD_ON_BLOCKS) {
        this.speaking = true;
        this.port.postMessage({ type: "vad", speaking: true });
      }
    } else {
      this.loudBlocks = 0;
      if (this.speaking) {
        if (this.quietSince === null) this.quietSince = currentTime;
        if ((currentTime - this.quietSince) * 1000 > VAD_OFF_MS) {
          this.speaking = false;
          this.quietSince = null;
          this.port.postMessage({ type: "vad", speaking: false });
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-capture", PcmCapture);
