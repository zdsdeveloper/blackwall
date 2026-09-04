#!/usr/bin/env python3
"""Synthesise the release sting: audio/release.mp3.

Original, built from oscillators here, and shaped to the reconnection sequence
in Model.js -- RELEASE_MS is 4600, and the phases it runs through are breach,
press, surge, shatter. The sound follows the same arc rather than being laid
over the top of it:

  0.00  breach  a low rumble as the seal starts to give
  1.20  press   pitch climbing, tension partials arriving under it
  3.10  surge   everything rising at once, the wall about to go
  3.95  shatter the break: a bright transient, then the mass falling away
  4.10+ open    what is left after it, thinning out into nothing

The point is that it ends in space rather than in a chord. The wall has just
opened; the last half second should sound like room, not like an instrument
finishing.

Usage:  python3 tools/make-release-sound.py
"""
import math
import os
import random
import struct
import subprocess
import sys
import wave

RATE = 44100
DUR = 4.75                       # a little past RELEASE_MS, so the tail lands
N = int(RATE * DUR)
BREAK_AT = 3.95

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_WAV = os.path.join(HERE, "..", "audio", "release.wav")
OUT_MP3 = os.path.join(HERE, "..", "audio", "release.mp3")


def soft(x):
    return math.tanh(x * 1.1)


def main():
    rnd = random.Random(0x09E4)
    left = []
    hold, held = 0, 0.0

    for i in range(N):
        t = i / RATE
        s = 0.0

        if t < BREAK_AT:
            u = t / BREAK_AT                     # 0..1 up to the break

            # --- the mass, climbing ------------------------------------------
            # Starts where the ambience sits and rises most of an octave, so
            # the release feels like the same object being lifted rather than
            # a new sound arriving.
            f = 37.0 * (1.0 + 0.85 * u ** 2.1)
            grow = u ** 1.6
            s += 0.55 * grow * math.sin(2 * math.pi * f * t)
            s += 0.26 * grow * math.sin(2 * math.pi * f * 1.5 * t + 0.4)
            s += 0.14 * grow * math.sin(2 * math.pi * f * 2.0 * t + 1.1)

            # --- tension -----------------------------------------------------
            # A partial a semitone-ish off the fifth, so it never settles.
            if t > 1.20:
                v = (t - 1.20) / (BREAK_AT - 1.20)
                s += 0.18 * (v ** 2) * math.sin(2 * math.pi * f * 1.43 * t)

            # --- strain ------------------------------------------------------
            # Held noise, thickening as it goes. The seal working.
            if hold <= 0:
                held = rnd.uniform(-1, 1)
                hold = rnd.randint(4, 20)
            hold -= 1
            s += 0.20 * (u ** 3) * held

            # --- the surge ---------------------------------------------------
            if t > 3.10:
                v = (t - 3.10) / (BREAK_AT - 3.10)
                s += 0.30 * v * v * math.sin(2 * math.pi * (140 + 900 * v) * t)

        else:
            d = t - BREAK_AT                     # seconds since the break

            # --- the break ---------------------------------------------------
            # Bright and short. This is the only moment in the whole plugin
            # that is allowed to be loud and high.
            crack = math.exp(-d * 26.0)
            s += 0.60 * crack * (rnd.uniform(-1, 1) * 0.6
                                 + math.sin(2 * math.pi * 3100 * t) * 0.4)

            # --- the mass falling away ---------------------------------------
            fall = math.exp(-d * 2.4)
            ff = 68.0 * math.exp(-d * 0.55)
            s += 0.50 * fall * math.sin(2 * math.pi * ff * t)
            s += 0.20 * fall * math.sin(2 * math.pi * ff * 0.5 * t)

            # --- what is left ------------------------------------------------
            # Thin, high, and going: the room after the wall, not a chord.
            air = math.exp(-d * 1.5) * 0.10
            s += air * math.sin(2 * math.pi * 1850 * t)
            s += air * 0.7 * math.sin(2 * math.pi * 2470 * t + 1.3)
            s += air * 0.5 * rnd.uniform(-1, 1)

        left.append(soft(s))

    # A few samples of offset on the right, for width.
    lag = 13
    right = [0.0] * lag + left[:-lag]

    peak = max(max(abs(v) for v in left), 1e-9)
    gain = 0.86 / peak
    frames = bytearray()
    for a, b in zip(left, right):
        frames += struct.pack("<hh",
                              int(max(-1, min(1, a * gain)) * 32000),
                              int(max(-1, min(1, b * gain)) * 32000))

    os.makedirs(os.path.dirname(OUT_WAV), exist_ok=True)
    with wave.open(OUT_WAV, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(RATE)
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
