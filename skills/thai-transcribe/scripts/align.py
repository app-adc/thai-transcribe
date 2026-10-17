"""หาว่าไฟล์สองไฟล์ของการประชุมเดียวกันเริ่มอัดห่างกันกี่วินาที

Use it when a transcript was made from one recording (e.g. a phone's .m4a) and
the report is built on another (e.g. the screen-recorded .mp4): pass the result
to report.py --offset instead of transcribing the video again.

Usage:
    python align.py <recording the transcript came from> <video> [--max-lag 900]

Prints the offset in seconds (video time = transcript time + offset). Works by
cross-correlating the loudness envelopes of both audio tracks at 50 Hz.
"""

import argparse
import sys

from _bootstrap import fmt_hms, relaunch_in_venv, setup_console

RATE = 16000
HOP = 320  # 20 ms -> 50 envelope points per second


def envelope(path, np):
    from faster_whisper import decode_audio

    audio = decode_audio(path, sampling_rate=RATE)
    n = len(audio) // HOP
    rms = np.sqrt(np.square(audio[: n * HOP].reshape(n, HOP)).mean(axis=1))
    env = np.log1p(rms * 1000)
    return (env - env.mean()) / (env.std() + 1e-9)


def main():
    setup_console()
    p = argparse.ArgumentParser(description="หาเวลาคลาดระหว่างไฟล์อัดสองไฟล์ของการประชุมเดียวกัน")
    p.add_argument("reference", help="recording the transcript was made from")
    p.add_argument("target", help="recording the report is built on (usually the video)")
    p.add_argument("--max-lag", type=float, default=900, help="largest offset to search, seconds")
    args = p.parse_args()
    relaunch_in_venv(__file__, sys.argv[1:])

    import numpy as np

    print("กำลังอ่านเสียงทั้งสองไฟล์…", flush=True)
    a, b = envelope(args.reference, np), envelope(args.target, np)
    size = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    corr = np.fft.irfft(np.fft.rfft(b, size) * np.conj(np.fft.rfft(a, size)), size)
    max_lag = int(args.max_lag * RATE / HOP)
    lags = np.concatenate([np.arange(0, max_lag + 1), np.arange(-max_lag, 0)])
    scores = np.concatenate([corr[: max_lag + 1], corr[-max_lag:]])
    best = int(np.argmax(scores))
    offset = lags[best] * HOP / RATE

    # Confidence: how far the peak stands above the rest of the search range
    others = np.delete(scores, range(max(0, best - 50), min(len(scores), best + 51)))
    strength = (scores[best] - others.mean()) / (others.std() + 1e-9)
    sign = "+" if offset >= 0 else "-"
    print(f"offset = {offset:+.2f} วินาที ({sign}{fmt_hms(abs(offset))}) · ความมั่นใจ {strength:.1f}", flush=True)
    print("  (เวลาในวิดีโอ = เวลาใน transcript + offset · ความมั่นใจ > 8 ถือว่าเชื่อได้)", flush=True)


if __name__ == "__main__":
    main()
