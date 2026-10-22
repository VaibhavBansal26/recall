/** Browser audio: microphone capture (AudioWorklet) and jitter-buffered playback. */

export interface MicHandlers {
  onFrame: (pcm: ArrayBuffer) => void;
  onSpeaking: (speaking: boolean) => void;
}

export class MicCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  streaming = false;

  constructor(private handlers: MicHandlers) {}

  get active(): boolean {
    return this.ctx !== null;
  }

  async start(): Promise<void> {
    if (this.ctx) return;
    // Echo cancellation matters: without it the assistant's own voice would barge in on itself.
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    const ctx = new AudioContext();
    await ctx.resume(); // iOS Safari starts contexts suspended
    await ctx.audioWorklet.addModule("/pcm-worklet.js");
    const source = ctx.createMediaStreamSource(this.stream);
    const node = new AudioWorkletNode(ctx, "pcm-capture", { numberOfOutputs: 0 });
    node.port.onmessage = (e: MessageEvent) => {
      const msg = e.data as { type: string; buffer?: ArrayBuffer; speaking?: boolean };
      if (!this.streaming) return;
      if (msg.type === "pcm" && msg.buffer) this.handlers.onFrame(msg.buffer);
      else if (msg.type === "vad") this.handlers.onSpeaking(Boolean(msg.speaking));
    };
    source.connect(node);
    this.ctx = ctx;
  }

  async stop(): Promise<void> {
    this.streaming = false;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    await this.ctx?.close();
    this.ctx = null;
  }
}

const SAMPLE_RATE = 16000;
const JITTER_LEAD_S = 0.08; // buffer ahead before the first chunk so network jitter is absorbed

export class PcmPlayer {
  private ctx: AudioContext | null = null;
  private nextTime = 0;
  private sources = new Set<AudioBufferSourceNode>();

  /** `onPlayingChange` fires when audio starts or fully drains, so the UI can follow it. */
  constructor(private onPlayingChange: (playing: boolean) => void = () => undefined) {}

  get playing(): boolean {
    return this.sources.size > 0;
  }

  /** Must be created/resumed from a user gesture (browsers block autoplay audio). */
  async unlock(): Promise<void> {
    if (!this.ctx) {
      try {
        this.ctx = new AudioContext({ sampleRate: SAMPLE_RATE });
      } catch {
        // Some Safari versions reject a custom rate; buffers are resampled to the device rate.
        this.ctx = new AudioContext();
      }
    }
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  enqueue(base64Pcm: string): void {
    const ctx = this.ctx;
    if (!ctx || ctx.state !== "running") return;
    const bytes = Uint8Array.from(atob(base64Pcm), (c) => c.charCodeAt(0));
    const samples = new Int16Array(bytes.buffer, 0, Math.floor(bytes.byteLength / 2));
    const buffer = ctx.createBuffer(1, samples.length, SAMPLE_RATE);
    const channel = buffer.getChannelData(0);
    for (let i = 0; i < samples.length; i++) channel[i] = samples[i] / 0x8000;

    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const startAt = Math.max(ctx.currentTime + JITTER_LEAD_S, this.nextTime);
    source.start(startAt);
    this.nextTime = startAt + buffer.duration;
    if (this.sources.size === 0) this.onPlayingChange(true);
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      if (this.sources.size === 0) this.onPlayingChange(false);
    };
  }

  /** Stop everything immediately (barge-in). */
  flush(): void {
    for (const source of this.sources) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        /* already stopped */
      }
    }
    const wasPlaying = this.sources.size > 0;
    this.sources.clear();
    this.nextTime = 0;
    if (wasPlaying) this.onPlayingChange(false);
  }
}
