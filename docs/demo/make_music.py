"""An original 128 BPM EDM backing track, synthesised from scratch (no samples, no copyrighted material)."""
import numpy as np
from scipy import signal
from scipy.io import wavfile

SR = 44100
BPM = 128
BEAT = 60 / BPM
BARS = 46
N = int(SR * BEAT * 4 * BARS)
rng = np.random.default_rng(7)
t_all = np.arange(N) / SR

def env_exp(n, decay):
    return np.exp(-np.arange(n) / (decay * SR))

def lowpass(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "low"); return signal.lfilter(b, a, x)

def highpass(x, fc, order=2):
    b, a = signal.butter(order, fc / (SR / 2), "high"); return signal.lfilter(b, a, x)

def bandpass(x, lo, hi):
    b, a = signal.butter(2, [lo / (SR / 2), hi / (SR / 2)], "band"); return signal.lfilter(b, a, x)

def place(track, sig, start_s, gain=1.0):
    i = int(start_s * SR)
    if i >= len(track): return
    j = min(len(track), i + len(sig))
    track[i:j] += sig[: j - i] * gain

def midi_hz(m): return 440.0 * 2 ** ((m - 69) / 12)

# --- drum voices ---
def kick():
    n = int(0.38 * SR); t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 38)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * env_exp(n, 0.12) * 1.0 + np.tanh(np.sin(ph) * 3) * 0.2 * env_exp(n, 0.05)

def clap():
    n = int(0.22 * SR)
    noise = bandpass(rng.standard_normal(n), 900, 4200)
    bursts = np.zeros(n)
    for off in (0, 0.012, 0.024):
        i = int(off * SR); bursts[i:] += noise[: n - i] * env_exp(n - i, 0.012) * 0.6
    return (bursts + noise * env_exp(n, 0.09) * 0.5) * 0.8

def hat(open_=False):
    n = int((0.22 if open_ else 0.05) * SR)
    return highpass(rng.standard_normal(n), 7000) * env_exp(n, 0.09 if open_ else 0.018) * 0.35

def saw(f, n, detune=0.0):
    t = np.arange(n) / SR
    return signal.sawtooth(2 * np.pi * f * (1 + detune) * t)

drums = np.zeros(N); music = np.zeros(N); bass = np.zeros(N)
K, C = kick(), clap()
chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]  # Am F C G
roots = [33, 29, 36, 31]
penta = [57, 60, 62, 64, 67, 69, 72, 74]

def bar_section(b):
    if b < 4: return "intro"
    if b < 8: return "build"
    if b < 16: return "drop1"
    if b < 20: return "break"
    if b < 36: return "drop2"
    if b < 42: return "drop1"
    return "outro"

kick_times = []
for b in range(BARS):
    sec = bar_section(b)
    t0 = b * BEAT * 4
    # kick: four on the floor from the build onwards (half-time hits in the break)
    if sec in ("build", "drop1", "drop2", "outro") or (sec == "intro" and b >= 2):
        for q in range(4):
            place(drums, K, t0 + q * BEAT, 0.9); kick_times.append(t0 + q * BEAT)
    elif sec == "break":
        place(drums, K, t0, 0.8); kick_times.append(t0)
    if sec in ("drop1", "drop2"):
        for q in (1, 3): place(drums, C, t0 + q * BEAT, 0.55)
    if sec in ("build", "drop1", "drop2", "outro") or b >= 2:
        for e in range(8):
            place(drums, hat(False), t0 + e * BEAT / 2 + BEAT / 4 * (e % 2 == 0) * 0, 0.5 if e % 2 else 0.2)
        place(drums, hat(True), t0 + BEAT * 0.5, 0.6); place(drums, hat(True), t0 + BEAT * 2.5, 0.6)
    if sec in ("drop2",):
        for s16 in range(16): place(drums, hat(False), t0 + s16 * BEAT / 4, 0.12)
    # snare-ish riser in the last bar of the build
    if b == 7:
        n = int(BEAT * 4 * SR); noise = highpass(rng.standard_normal(n), 2500)
        riser = noise * np.linspace(0.02, 0.9, n) ** 2 * 0.5
        place(drums, riser, t0, 0.8)

    # harmony
    ch = chords[(b // 2) % 4]; root = roots[(b // 2) % 4]
    n_bar = int(BEAT * 4 * SR)
    if sec != "intro" or b >= 1:
        pad = sum(saw(midi_hz(m + 12), n_bar, d) for m in ch for d in (-0.004, 0.0, 0.004))
        pad = lowpass(pad, 1800 if sec != "break" else 900) * 0.045
        swell = np.minimum(1, np.arange(n_bar) / (0.4 * SR)) * 0.9 + 0.1
        place(music, pad * swell, t0, 1.0)
    if sec in ("drop1", "drop2", "outro", "build"):
        # offbeat plucked sub bass with a little saw bite
        for e in range(8):
            if e % 2 == 1:
                n = int(BEAT / 2 * SR * 0.9)
                f = midi_hz(root)
                note = (np.sin(2 * np.pi * f * np.arange(n) / SR) + 0.35 * lowpass(saw(f, n), 400)) * env_exp(n, 0.22)
                place(bass, note, t0 + e * BEAT / 2, 0.55)
    # arpeggiated plucks
    if sec in ("drop1", "drop2", "break"):
        pattern = [0, 2, 4, 2, 5, 4, 2, 1] if sec != "break" else [0, 4, 2, 4]
        step = BEAT / 2 if sec != "break" else BEAT
        for k in range(int(4 * BEAT / step)):
            m = penta[(pattern[k % len(pattern)] + (b // 2) % 4 * 0) % len(penta)] + (12 if (sec == "drop2" and k % 4 == 3) else 0)
            n = int(0.28 * SR)
            note = lowpass(saw(midi_hz(m), n) + saw(midi_hz(m), n, 0.006), 3200) * env_exp(n, 0.11) * 0.09
            place(music, note, t0 + k * step, 1.0)
    if sec == "drop2" and b % 4 == 0:  # a bright stab on the one
        n = int(0.5 * SR)
        stab = sum(lowpass(saw(midi_hz(m + 24), n), 4500) for m in ch) * env_exp(n, 0.16) * 0.04
        place(music, stab, t0, 1.0)

# sidechain pump: duck everything but the drums on each kick
duck = np.ones(N)
for kt in kick_times:
    i = int(kt * SR); n = int(0.28 * SR)
    curve = 1 - 0.75 * np.exp(-np.arange(min(n, N - i)) / (0.09 * SR))
    duck[i : i + len(curve)] = np.minimum(duck[i : i + len(curve)], curve)
mix = drums * 0.95 + (music + bass) * duck

# simple dynamics: fade in/out, gentle limiter, stereo width via short delay
fade_in = np.minimum(1, t_all / 3.0); fade_out = np.minimum(1, (t_all[-1] - t_all) / 5.0)
mix *= fade_in * fade_out
mix = np.tanh(mix * 1.4) / np.tanh(1.4)
d = int(0.017 * SR)
left = mix + 0.25 * np.concatenate([np.zeros(d), mix[:-d]])
right = mix + 0.25 * np.concatenate([np.zeros(2 * d), mix[:-2 * d]])
stereo = np.stack([left, right], axis=1)
stereo = stereo / np.max(np.abs(stereo)) * 0.9
wavfile.write("edm.wav", SR, (stereo * 32767).astype(np.int16))
print("edm", N / SR, "s")
