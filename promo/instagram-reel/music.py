import json
import sys
import wave

import numpy as np

SR = 48000
DURATION = 30.0
BEAT = 0.5
DROP = 9.5
END = 26.5
N = int(SR * DURATION)
rng = np.random.default_rng(20261013)

dry = np.zeros((2, N))
ducked = np.zeros((2, N))
send = np.zeros((2, N))


def note(name):
    names = {"C": -9, "C#": -8, "D": -7, "D#": -6, "E": -5, "F": -4, "F#": -3, "G": -2, "G#": -1, "A": 0, "A#": 1, "B": 2}
    pitch, octave = name[:-1], int(name[-1])
    return 440.0 * 2 ** ((names[pitch] + 12 * (octave - 4)) / 12)


def seconds(duration):
    return np.arange(int(SR * duration)) / SR


def place(signal, at, gain=1.0, pan=0.0, wet=0.0, duck=False):
    start = int(round(at * SR))
    if start >= N or len(signal) == 0:
        return
    signal = signal[: N - start] * gain
    left, right = np.sqrt(0.5 * (1 - pan)), np.sqrt(0.5 * (1 + pan))
    bus = ducked if duck else dry
    bus[0, start:start + len(signal)] += signal * left
    bus[1, start:start + len(signal)] += signal * right
    if wet:
        send[0, start:start + len(signal)] += signal * left * wet
        send[1, start:start + len(signal)] += signal * right * wet


def lowpass(signal, cutoff):
    cutoff = np.broadcast_to(np.asarray(cutoff, dtype=float), signal.shape)
    alpha = 1 - np.exp(-2 * np.pi * cutoff / SR)
    out = np.empty_like(signal)
    state = 0.0
    for i, (x, a) in enumerate(zip(signal.tolist(), alpha.tolist())):
        state += a * (x - state)
        out[i] = state
    return out


def highpass(signal):
    return np.diff(signal, prepend=0.0)


def additive(freq, duration, harmonics, rolloff, detune=0.0):
    t = seconds(duration)
    wave_ = np.zeros_like(t)
    for k in range(1, harmonics + 1):
        wave_ += np.sin(2 * np.pi * freq * (1 + detune) * k * t + k) / k ** rolloff
    return wave_


def adsr(length, attack, release, sustain=1.0, decay=0.0):
    n = int(length * SR)
    env = np.full(n, sustain)
    a = max(1, int(attack * SR))
    env[:a] = np.linspace(0, 1, a)
    if decay:
        d = int(decay * SR)
        env[a:a + d] = np.linspace(1, sustain, len(env[a:a + d]))
    r = max(1, int(release * SR))
    env[-r:] *= np.linspace(1, 0, len(env[-r:]))
    return env


def kick(at, gain=1.0):
    t = seconds(0.5)
    freq = 44 + 110 * np.exp(-t / 0.04)
    body = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / 0.2)
    click = rng.standard_normal(len(t)) * np.exp(-t / 0.003) * 0.25
    place(np.tanh(1.6 * (body + click)), at, gain * 0.9)


def clap(at, gain=1.0):
    t = seconds(0.35)
    burst = np.zeros_like(t)
    for offset in (0.0, 0.011, 0.022):
        shifted = np.clip(t - offset, 0, None)
        burst += (t >= offset) * np.exp(-shifted / (0.13 if offset == 0.022 else 0.008))
    noise = highpass(lowpass(rng.standard_normal(len(t)), 3200))
    place(noise * burst * 2.4, at, gain * 0.5, pan=0.05, wet=0.35)


def hat(at, gain=1.0, decay=0.03, pan=0.25):
    t = seconds(decay * 6)
    noise = highpass(highpass(rng.standard_normal(len(t))))
    place(noise * np.exp(-t / decay) * 0.35, at, gain, pan=pan)


def crash(at, gain=1.0):
    t = seconds(2.2)
    noise = highpass(rng.standard_normal(len(t)))
    place(noise * np.exp(-t / 0.7) * 0.3, at, gain, pan=-0.15, wet=0.5)


def bass(at, freq, duration, gain=1.0):
    tone = additive(freq, duration, 7, 1.2) + 0.6 * np.sin(2 * np.pi * freq * seconds(duration))
    place(tone * adsr(duration, 0.004, 0.03, sustain=0.75, decay=0.08), at, gain * 0.32, duck=True)


def pad(at, freqs, duration, gain=1.0):
    total = np.zeros(int(duration * SR))
    for f in freqs:
        total += additive(f, duration, 6, 1.6, detune=0.0035) + additive(f, duration, 6, 1.6, detune=-0.0035)
    env = adsr(duration, 0.35, 0.7)
    place(total * env, at, gain * 0.05, pan=-0.35, wet=0.5, duck=True)
    place(total * env, at + 0.012, gain * 0.05, pan=0.35, wet=0.5, duck=True)


def pluck(at, freq, gain=1.0, pan=0.0, decay=0.28):
    t = seconds(decay * 5)
    tone = sum(np.sin(2 * np.pi * freq * k * t) / k ** 2 for k in (1, 3, 5)) + 0.4 * np.sin(4 * np.pi * freq * t)
    place(tone * np.exp(-t / decay) * np.minimum(1, t / 0.002), at, gain * 0.22, pan=pan, wet=0.45)


def bell(at, freq, gain=1.0, pan=0.0):
    t = seconds(2.5)
    tone = np.zeros_like(t)
    for ratio, amp, decay in ((1, 1, 1.1), (2.0, 0.5, 0.6), (2.76, 0.35, 0.4), (5.4, 0.2, 0.2)):
        tone += amp * np.sin(2 * np.pi * freq * ratio * t) * np.exp(-t / decay)
    place(tone * np.minimum(1, t / 0.003), at, gain * 0.16, pan=pan, wet=0.6)


def impact(at, gain=1.0):
    t = seconds(2.0)
    freq = 34 + 40 * np.exp(-t / 0.12)
    boom = np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t / 0.6)
    hit = lowpass(rng.standard_normal(len(t)), 1800) * np.exp(-t / 0.12) * 1.4
    place(np.tanh(1.3 * (boom + hit)), at, gain * 0.8, wet=0.4)


def riser(start, end, gain=1.0):
    t = seconds(end - start)
    progress = t / t[-1]
    noise = lowpass(rng.standard_normal(len(t)), 300 + 7000 * progress ** 2)
    sweep = np.sin(2 * np.pi * np.cumsum(220 + 900 * progress ** 2) / SR) * 0.25
    place((noise + sweep) * progress ** 2.2, start, gain * 0.5, wet=0.4)


def whoosh(center, gain=1.0, span=0.55):
    t = seconds(span)
    shape = np.sin(np.pi * t / span) ** 2
    noise = lowpass(rng.standard_normal(len(t)), 400 + 5200 * shape)
    place(noise * shape * 1.6, center - span * 0.6, gain * 0.45, pan=-0.3, wet=0.3)


def glitch(at, gain=1.0):
    length = rng.uniform(0.018, 0.07)
    t = seconds(length)
    freq = rng.uniform(300, 2600)
    square = np.sign(np.sin(2 * np.pi * freq * t))
    held = np.repeat(rng.uniform(-1, 1, len(t) // 40 + 1), 40)[: len(t)]
    place((square * 0.5 + held * 0.6) * np.hanning(len(t)) ** 0.3, at, gain * 0.16, pan=rng.uniform(-0.7, 0.7))


def tick(at, gain=1.0):
    t = seconds(0.012)
    noise = highpass(rng.standard_normal(len(t)))
    place(noise * np.exp(-t / 0.0025), at, gain * rng.uniform(0.6, 1.0) * 0.5, pan=rng.uniform(-0.2, 0.2))


def blip(at, freq, gain=1.0):
    t = seconds(0.09)
    place(np.sin(2 * np.pi * freq * t) * np.exp(-t / 0.025), at, gain * 0.18, pan=0.1, wet=0.25)


def zap(at, gain=1.0):
    t = seconds(0.4)
    freq = 1400 * np.exp(-t / 0.08) + 90
    square = np.sign(np.sin(2 * np.pi * np.cumsum(freq) / SR))
    place((square * 0.4 + rng.standard_normal(len(t)) * 0.3) * np.exp(-t / 0.12), at, gain * 0.35, wet=0.2)


def drone(start, end, freqs, gain=1.0):
    t = seconds(end - start)
    tone = sum(additive(f, end - start, 5, 1.4) for f in freqs)
    tremolo = 0.75 + 0.25 * np.sin(2 * np.pi * (2 + 6 * t / t[-1]) * t)
    place(tone * tremolo * adsr(end - start, 0.02, 0.3), start, gain * 0.12, wet=0.3)


def typing(start, count, rate, gain=1.0):
    for k in range(count):
        tick(start + k / rate + rng.uniform(-0.006, 0.006), gain)


def reverb(signal, seconds_=1.9):
    t = seconds(seconds_)
    out = np.zeros_like(signal)
    size = 1 << int(np.ceil(np.log2(signal.shape[1] + len(t))))
    for channel in range(2):
        response = rng.standard_normal(len(t)) * np.exp(-t / (seconds_ / 5.5))
        response[: int(0.012 * SR)] = 0
        response /= np.sqrt(np.sum(response ** 2))
        wet = np.fft.irfft(np.fft.rfft(signal[channel], size) * np.fft.rfft(response, size), size)
        out[channel] = wet[: signal.shape[1]]
    return out


def sidechain(kicks):
    env = np.ones(N)
    t = seconds(0.32)
    duck = 1 - 0.6 * np.exp(-t / 0.09)
    for at in kicks:
        start = int(at * SR)
        stop = min(N, start + len(t))
        env[start:stop] = np.minimum(env[start:stop], duck[: stop - start])
    return env


PROGRESSION = [
    ("A1", ["A3", "C4", "E4"]),
    ("F1", ["A3", "C4", "F4"]),
    ("C2", ["G3", "C4", "E4"]),
    ("G1", ["G3", "B3", "D4"]),
]
PENTATONIC = ["A4", "C5", "D5", "E5", "G5", "A5", "C6", "D6", "E6", "G6", "A6"]


def compose(cues):
    beats = cues["beats"]

    impact(0.0, 1.0)
    drone(0.0, 3.6, [note("A1"), note("E2")], 1.0)
    flips = np.sort(np.concatenate([rng.uniform(0.05, 2.55, 40), 0.05 + 2.5 * rng.power(2.2, 30)]))
    for at in flips:
        glitch(at, 1.0)
    bell(2.05, note("E4"), 0.7)
    riser(2.45, beats["proof"], 0.9)

    impact(beats["proof"], 0.55)
    whoosh(beats["proof"], 0.7)
    for k in range(12):
        kick(beats["proof"] + k * 1.0, 0.45)
    for k in range(int((DROP - 4.0) / 0.25)):
        at = 4.0 + k * 0.25
        hat(at, 0.08 if k % 2 else 0.14)
    for k in range(int((DROP - beats["proof"]) / 0.25)):
        bass(beats["proof"] + k * 0.25, note("A1"), 0.22, 0.55 if k % 4 == 0 else 0.3)
    typing(3.8, 25, 34, 0.9)
    typing(4.6, 38, 52, 0.9)
    for at, freq in ((5.30, "A5"), (5.55, "D#5"), (5.85, "E5"), (6.05, "E5"), (6.40, "C5"), (6.75, "A5"), (7.10, "C6"), (7.25, "E6"), (7.35, "A6")):
        blip(at, note(freq), 1.0)
    sweep = cues["healSweep"]
    for k, name in enumerate(PENTATONIC):
        pluck(sweep + k * 0.1, note(name), 0.7, pan=-0.5 + k / len(PENTATONIC))
    pad(sweep, [note("A3"), note("C4"), note("E4")], DROP - sweep + 0.4, 0.9)
    for name, pan in (("A4", -0.3), ("C5", 0.0), ("E5", 0.3)):
        bell(7.55, note(name), 0.8, pan)
    riser(8.3, DROP, 1.1)
    for k in range(8):
        hat(8.5 + k * 0.125, 0.06 + 0.03 * k, decay=0.02, pan=-0.2)

    impact(DROP, 1.1)
    crash(DROP, 1.0)
    kicks = [DROP + k * BEAT for k in range(int((DURATION - 0.5 - DROP) / BEAT))]
    for at in kicks:
        kick(at, 0.95 if at < END else 0.7)
    for k, at in enumerate(kicks):
        if k % 2 == 1:
            clap(at, 0.9 if at < END else 0.6)
        hat(at + BEAT / 2, 0.22, pan=0.3)
        hat(at + BEAT / 4, 0.06, decay=0.015, pan=-0.3)
        hat(at + 3 * BEAT / 4, 0.06, decay=0.015, pan=-0.3)
    bar = 0
    at = DROP
    while at < END:
        root, chord = PROGRESSION[bar % len(PROGRESSION)]
        pad(at, [note(n) for n in chord], 2.1, 1.0)
        for k in range(8):
            bass(at + k * 0.25, note(root) * (2 if k in (3, 6) else 1), 0.22, 0.85)
        for k in range(8):
            if bar >= 2:
                arp = [note(n) * 2 for n in chord]
                pluck(at + k * 0.25, arp[k % 3], 0.22, pan=0.4 if k % 2 else -0.4, decay=0.12)
        bar += 1
        at += 2.0
    for center in (beats["inside"], beats["command"], beats["box"]):
        whoosh(center, 1.0)
    for row, start in ((0, 12.9), (1, 13.9)):
        for k in range(8):
            blip(start + k * 0.08, note(PENTATONIC[k]) * (0.5 if row else 1), 0.5)
    zap(cues["damage"], 1.0)
    for k in range(6):
        glitch(cues["damage"] + (k % 3) * 0.05 + rng.uniform(0, 0.4), 1.6)
    for k, at in enumerate(cues["heals"]):
        bell(at, note(["E5", "G5", "A5", "C6", "D6", "E6"][k]), 0.8, pan=-0.4 + 0.16 * k)
    typing(19.05, 22, 44, 0.8)
    typing(20.0, 38, 52, 0.8)
    for name, pan in (("C5", -0.2), ("E5", 0.0), ("A5", 0.2)):
        bell(20.85, note(name), 0.5, pan)
    blip(21.25, note("E5"), 0.8)
    for k, at in enumerate(cues["chips"]):
        pluck(at, note(PENTATONIC[k]), 0.9, pan=-0.3 + 0.07 * k, decay=0.2)

    impact(END, 0.9)
    crash(END, 0.8)
    pad(END, [note("A3"), note("C4"), note("E4"), note("A4")], DURATION - END, 1.3)
    for k in range(14):
        bass(END + k * 0.25, note("A1"), 0.22, 0.6)
    for name, pan in (("A4", -0.3), ("C5", 0.0), ("E5", 0.3), ("A5", 0.1)):
        bell(27.25, note(name), 0.55, pan)

    return kicks


def master(kicks):
    music = dry + ducked * sidechain([at for at in kicks if at >= DROP]) + reverb(send) * 0.55
    t = np.arange(N) / SR
    fade = np.clip((DURATION - t) / 0.6, 0, 1)
    music *= fade
    music = np.tanh(music * 1.4) / np.tanh(1.4)
    peak = np.max(np.abs(music))
    return music / peak * 0.89


def write(path, music):
    pcm = (np.clip(music, -1, 1) * 32767).astype("<i2").T.copy()
    with wave.open(path, "wb") as out:
        out.setnchannels(2)
        out.setsampwidth(2)
        out.setframerate(SR)
        out.writeframes(pcm.tobytes())


if __name__ == "__main__":
    with open(sys.argv[1]) as handle:
        cues = json.load(handle)
    write(sys.argv[2], master(compose(cues)))
