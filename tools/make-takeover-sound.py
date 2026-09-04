#!/usr/bin/env python3
"""Synthesise the takeover sting: sounds/takeover.mp3.

An original sound, built from oscillators here rather than lifted from
anywhere. It is written as a script and committed alongside its output so the
sound can be re-made and adjusted instead of sitting in the tree as an opaque
binary nobody can change.

Shaped to the tear in takeover.frag, which runs 2.4s:

  0.00  a crack as the rift opens
  0.00+ a sub-bass swell rising under everything, the pressure behind it
  0.15  a resonant sweep falling from 1.4kHz to 90Hz, detuned for a metal edge
  0.30+ gated noise bursts, the picture coming apart in strips
  1.55  the impact as the tear takes the screen
  1.60+ a low drone settling, handing over to the wall's own ambience

Usage:  python3 tools/make-takeover-sound.py
"""
import math
import os
import random
import struct
import subprocess
import sys
import wave

RATE = 44100
DUR = 2.45
N = int(RATE * DUR)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_WAV = os.path.join(HERE, "..", "sounds", "takeover.wav")
OUT_MP3 = os.path.join(HERE, "..", "sounds", "takeover.mp3")


def env(t, attack, hold, release):
    """A simple attack/hold/release envelope, 0..1."""
    if t < 0:
        return 0.0
    if t < attack:
        return t / attack if attack else 1.0
    if t < attack + hold:
        return 1.0
    fall = t - attack - hold
    if fall >= release:
        return 0.0
    return 1.0 - fall / release


def soft(x):
    """Soft clip, so a stacked mix never wraps around into a click."""
    return math.tanh(x * 1.15)


def main():
    rnd = random.Random(0x4E57)   # fixed, so the file is reproducible
    left, right = [], []

    # A little correlated noise, held between samples, for the tearing bursts.
    noise_hold, noise_val = 0, 0.0

    for i in range(N):
        t = i / RATE
        s = 0.0

        # --- the sub-bass swell -------------------------------------------
        # Rises in pitch and weight the whole way; it is the pressure behind
        # the tear rather than an event in it.
        sub_f = 38.0 + 16.0 * (t / DUR)
        s += 0.55 * env(t, 0.35, 1.35, 0.70) * math.sin(2 * math.pi * sub_f * t)
        s += 0.18 * env(t, 0.40, 1.30, 0.70) * math.sin(2 * math.pi * sub_f * 2 * t)

        # --- the opening crack --------------------------------------------
        if t < 0.30:
            e = env(t, 0.004, 0.010, 0.28)
            s += 0.42 * e * (rnd.uniform(-1, 1) * 0.7
                             + math.sin(2 * math.pi * 2400 * t) * 0.3)

        # --- the resonant fall --------------------------------------------
        # 1.4kHz down to 90Hz on a curve, two voices a few cents apart so it
        # beats slightly and reads as metal rather than as a test tone.
        if 0.15 <= t < 1.70:
            u = (t - 0.15) / 1.55
            f = 1400.0 * math.pow(90.0 / 1400.0, u ** 0.62)
            e = env(t - 0.15, 0.06, 1.05, 0.44)
            s += 0.30 * e * math.sin(2 * math.pi * f * t)
            s += 0.20 * e * math.sin(2 * math.pi * f * 1.004 * t + 0.7)
            s += 0.10 * e * math.sin(2 * math.pi * f * 0.499 * t)

        # --- tearing ------------------------------------------------------
        # Bursts of held noise, denser as the rift widens.
        if 0.30 <= t < 1.90:
            u = (t - 0.30) / 1.60
            if noise_hold <= 0:
                noise_val = rnd.uniform(-1, 1)
                noise_hold = rnd.randint(6, 26)
            noise_hold -= 1
            gate = 1.0 if rnd.random() < (0.08 + 0.30 * u) else 0.0
            s += 0.22 * gate * noise_val * env(t - 0.30, 0.05, 1.2, 0.35)

        # --- the impact ----------------------------------------------------
        if t >= 1.55:
            e = env(t - 1.55, 0.006, 0.02, 0.80)
            s += 0.70 * e * math.sin(2 * math.pi * 54.0 * (t - 1.55))
            s += 0.30 * e * math.sin(2 * math.pi * 81.0 * (t - 1.55))

        # --- the settle -----------------------------------------------------
        # What the wall's own ambience takes over from.
        if t >= 1.60:
            e = env(t - 1.60, 0.15, 0.15, 0.55)
            s += 0.22 * e * math.sin(2 * math.pi * 47.0 * t)

        # A few cents of delay on one side gives it width without smearing
        # the transients.
        s = soft(s)
        left.append(s)
        right.append(s)

    # Widen: the right channel lags by 11 samples, which is inaudible as an
    # echo and reads as space.
    lag = 11
    right = [0.0] * lag + right[:-lag]

    frames = bytearray()
    for a, b in zip(left, right):
        frames += struct.pack("<hh", int(max(-1, min(1, a)) * 32000),
                              int(max(-1, min(1, b)) * 32000))

    os.makedirs(os.path.dirname(OUT_WAV), exist_ok=True)
    with wave.open(OUT_WAV, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(bytes(frames))
    print("wrote %s (%.1f KB)" % (OUT_WAV, os.path.getsize(OUT_WAV) / 1024))

    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", OUT_WAV,
                        "-codec:a", "libmp3lame", "-b:a", "160k", OUT_MP3],
                       check=True)
        os.remove(OUT_WAV)
        print("wrote %s (%.1f KB)" % (OUT_MP3, os.path.getsize(OUT_MP3) / 1024))
    except (OSError, subprocess.CalledProcessError) as exc:
        print("ffmpeg unavailable (%s); leaving the wav" % exc, file=sys.stderr)


if __name__ == "__main__":
    main()
