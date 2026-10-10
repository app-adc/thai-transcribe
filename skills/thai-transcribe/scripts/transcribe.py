"""ถอดเสียงภาษาไทยเป็นข้อความ (รองรับไฟล์ยาวหลายชั่วโมง, ทำต่อจากจุดเดิมได้)

Usage (any Python >= 3.9; the first run creates its own venv and installs faster-whisper):
    python transcribe.py <audio file> [--out-dir DIR] [--model fast|accurate|<hf-id>|<dir>]
                         [--suffix NAME] [--window 20] [--beam-size 5] [--threads N]
                         [--device cpu|cuda] [--restart] [--overwrite]
    python transcribe.py --setup     # only install, then exit

Venv, models and the Hugging Face cache live in $THAI_TRANSCRIBE_HOME
(default ~/.thai-transcribe, ~3.5 GB with both models).

Outputs (next to the input file unless --out-dir):
    <name>.txt              plain text, grouped into paragraphs
    <name>.timestamped.txt  one line per speech window: [HH:MM:SS] text

How it works: voice-activity detection finds the speech, which is packed into
windows of at most --window seconds. Each window is transcribed in one call.
Short windows matter: the Thai fine-tuned models stop emitting text after
~20 s of dense speech, so a full 30 s Whisper window silently loses words.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

SAMPLE_RATE = 16000
DATA_DIR = Path(os.environ.get("THAI_TRANSCRIBE_HOME") or Path.home() / ".thai-transcribe").expanduser()
VENV_DIR = DATA_DIR / ".venv"
VENV_PYTHON = VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = ["faster-whisper>=1.1"]
# Benchmarked on a Ryzen 5 4500U (CPU, int8), 20 s windows:
#   fast     ~0.96x real time, CER ~2%  (mostly digits vs spelled-out numbers)
#   accurate ~0.68x real time, CER ~0.4%
MODELS = {
    "fast": "pariya47/distill-whisper-th-large-v3-ct2",
    "accurate": "Vinxscribe/biodatlab-whisper-th-medium-faster",
}
PARAGRAPH_GAP_SEC = 2.0
PARAGRAPH_MAX_CHARS = 600
MAX_SAME_IN_A_ROW = 3
REWRITE_OUTPUT_EVERY = 10  # windows


def in_venv():
    return Path(sys.prefix).resolve() == VENV_DIR.resolve()


def ensure_venv():
    """Create DATA_DIR/.venv with faster-whisper on first use."""
    if VENV_PYTHON.exists():
        return
    print(f"ติดตั้งครั้งแรก: สร้าง venv ที่ {VENV_DIR} และติดตั้ง faster-whisper…", flush=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
    subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "-q", *REQUIREMENTS])
    print("ติดตั้งเสร็จ", flush=True)


def fmt_hms(seconds):
    seconds = int(seconds)
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def fmt_duration(seconds):
    seconds = int(seconds)
    h, m = seconds // 3600, seconds % 3600 // 60
    return f"{h} ชม. {m} นาที" if h else f"{m} นาที {seconds % 60} วินาที"


def speech_windows(audio, window_sec):
    """[(start, end)] sample ranges: VAD speech pieces packed into windows <= window_sec."""
    from faster_whisper.vad import VadOptions, get_speech_timestamps

    pieces = get_speech_timestamps(
        audio, VadOptions(max_speech_duration_s=window_sec, min_silence_duration_ms=300)
    )
    windows, limit = [], window_sec * SAMPLE_RATE
    for p in pieces:
        if windows and p["end"] - windows[-1][0] <= limit:
            windows[-1][1] = p["end"]
        else:
            windows.append([p["start"], p["end"]])
    return [tuple(w) for w in windows]


def collapse_repeats(text):
    # "ครับครับครับครับครับ" -> "ครับ" (a common Whisper hallucination loop)
    return re.sub(r"(.{1,30}?)\1{4,}", r"\1", text)


def clean_segments(segments):
    out, run = [], 0
    for seg in segments:
        text = collapse_repeats(seg["text"]).strip()
        if not text:
            continue
        run = run + 1 if out and out[-1]["text"] == text else 1
        if run > MAX_SAME_IN_A_ROW:
            continue
        out.append({**seg, "text": text})
    return out


def write_outputs(segments, base):
    segments = clean_segments(segments)

    lines = [f"[{fmt_hms(s['start'])}] {s['text']}" for s in segments]
    Path(f"{base}.timestamped.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    paragraphs, current, last_end = [], [], None
    for s in segments:
        too_long = sum(len(t) for t in current) > PARAGRAPH_MAX_CHARS
        if current and (s["start"] - last_end > PARAGRAPH_GAP_SEC or too_long):
            paragraphs.append(" ".join(current))
            current = []
        current.append(s["text"])
        last_end = s["end"]
    if current:
        paragraphs.append(" ".join(current))
    Path(f"{base}.txt").write_text("\n\n".join(paragraphs) + "\n", encoding="utf-8")


def resolve_model(name):
    """Local folder for a model, downloading it into DATA_DIR/models on first use."""
    if Path(name).is_dir():
        return name
    repo_id = MODELS.get(name, name)
    local_dir = DATA_DIR / "models" / repo_id.split("/")[-1]
    if not (local_dir / "model.bin").exists():
        print(f"กำลังดาวน์โหลดโมเดล {repo_id} ไปที่ {local_dir} (ครั้งแรกครั้งเดียว)", flush=True)
        from huggingface_hub import snapshot_download

        snapshot_download(repo_id, local_dir=str(local_dir))
    return str(local_dir)


def load_progress(path, fingerprint):
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("fingerprint") == fingerprint:
            return data
        print("ไฟล์ความคืบหน้าเดิมไม่ตรงกับการตั้งค่าครั้งนี้ — เริ่มใหม่", flush=True)
    return {"fingerprint": fingerprint, "segments": []}


def save_progress(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(description="ถอดเสียงภาษาไทยเป็นข้อความ")
    p.add_argument("input", nargs="?")
    p.add_argument("--setup", action="store_true", help="install the venv and exit")
    p.add_argument("--out-dir")
    p.add_argument("--model", default="fast", help="fast | accurate | Hugging Face id | local folder")
    p.add_argument("--window", type=float, default=20, help="max seconds of speech per model call")
    p.add_argument("--beam-size", type=int, default=5)
    p.add_argument("--threads", type=int, default=os.cpu_count() or 4)
    p.add_argument("--device", default="cpu", choices=["cpu", "cuda"], help="cuda needs an NVIDIA GPU + CUDA 12 libs")
    p.add_argument("--suffix", default="", help='added to output names, e.g. "accurate" -> <name>.accurate.txt')
    p.add_argument("--restart", action="store_true", help="ignore saved progress")
    p.add_argument("--overwrite", action="store_true", help="allow replacing existing transcripts")
    args = p.parse_args()

    if not in_venv():
        ensure_venv()
        if args.setup:
            return
        sys.exit(subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]]))
    if args.setup:
        return
    if not args.input:
        p.error("ต้องระบุไฟล์เสียง")

    src = Path(args.input).resolve()
    if not src.is_file():
        sys.exit(f"ไม่พบไฟล์: {src}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / (f"{src.stem}.{args.suffix}" if args.suffix else src.stem)
    progress_path = Path(f"{base}.progress.json")

    existing = [f for f in (Path(f"{base}.txt"), Path(f"{base}.timestamped.txt")) if f.exists()]
    resuming = progress_path.exists() and not args.restart
    if existing and not resuming and not args.overwrite:
        sys.exit(
            "มีไฟล์ผลลัพธ์อยู่แล้ว จะไม่เขียนทับ: " + ", ".join(f.name for f in existing)
            + "\nใช้ --suffix <ชื่อ> เพื่อบันทึกเป็นไฟล์ใหม่ หรือ --overwrite ถ้าต้องการเขียนทับจริงๆ"
        )
    os.environ.setdefault("HF_HOME", str(DATA_DIR / "hf-home"))

    from faster_whisper import WhisperModel, decode_audio

    print(f"กำลังอ่านไฟล์เสียง: {src.name}", flush=True)
    audio = decode_audio(str(src), sampling_rate=SAMPLE_RATE)
    total_sec = len(audio) / SAMPLE_RATE
    print(f"ความยาว {fmt_duration(total_sec)} · กำลังหาช่วงที่มีเสียงพูด…", flush=True)
    windows = speech_windows(audio, args.window)
    speech_sec = sum(e - s for s, e in windows) / SAMPLE_RATE
    print(f"มีเสียงพูดรวม {fmt_duration(speech_sec)} · {len(windows)} ท่อน", flush=True)

    stat = src.stat()
    fingerprint = [stat.st_size, int(stat.st_mtime), MODELS.get(args.model, args.model), args.window]
    if args.restart and progress_path.exists():
        progress_path.unlink()
    progress = load_progress(progress_path, fingerprint)
    done = len(progress["segments"])
    if done:
        print(f"ทำต่อจากครั้งก่อน: เสร็จแล้ว {done}/{len(windows)} ท่อน", flush=True)

    print(f"กำลังโหลดโมเดล {MODELS.get(args.model, args.model)}", flush=True)
    model = WhisperModel(
        resolve_model(args.model),
        device=args.device,
        compute_type="float16" if args.device == "cuda" else "int8",
        cpu_threads=args.threads,
    )

    started, processed_sec, last_report = time.time(), 0.0, time.time()
    for i in range(done, len(windows)):
        s, e = windows[i]
        segments, _ = model.transcribe(
            audio[s:e],
            language="th",
            task="transcribe",
            beam_size=args.beam_size,
            without_timestamps=True,
            condition_on_previous_text=False,
            # Thai UTF-8 always looks "highly compressible", so the default 2.4
            # threshold triggers pointless temperature re-decodes (3x slower).
            compression_ratio_threshold=None,
            temperature=0.0,
        )
        text = " ".join(seg.text.strip() for seg in segments)
        progress["segments"].append({"start": round(s / SAMPLE_RATE, 2), "end": round(e / SAMPLE_RATE, 2), "text": text})
        save_progress(progress_path, progress)

        processed_sec += (e - s) / SAMPLE_RATE
        finished = i + 1 == len(windows)
        if finished or (i + 1) % REWRITE_OUTPUT_EVERY == 0:
            write_outputs(progress["segments"], base)
        if finished or time.time() - last_report >= 60:
            last_report = time.time()
            elapsed = time.time() - started
            remaining = sum(we - ws for ws, we in windows[i + 1 :]) / SAMPLE_RATE
            print(
                f"ท่อน {i + 1}/{len(windows)} [{fmt_hms(e / SAMPLE_RATE)}/{fmt_hms(total_sec)}] · "
                f"ผ่านไป {fmt_duration(elapsed)} · คาดว่าเหลือ ~{fmt_duration(elapsed / processed_sec * remaining)}",
                flush=True,
            )

    write_outputs(progress["segments"], base)
    progress_path.unlink(missing_ok=True)
    print("เสร็จสิ้น", flush=True)
    print(f"  {base}.txt", flush=True)
    print(f"  {base}.timestamped.txt", flush=True)


if __name__ == "__main__":
    main()
