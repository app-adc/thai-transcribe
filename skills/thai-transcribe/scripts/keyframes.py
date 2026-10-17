"""ดึงภาพจากวิดีโอประชุม เฉพาะตอนที่หน้าจอเปลี่ยน (สไลด์ใหม่, สลับแชร์จอ)

Usage:
    python keyframes.py <video> [--out-dir DIR] [--interval 1.0] [--change 0.02]
                        [--still 0.003] [--scene 0.3] [--settle 6] [--max-frames 60]
                        [--overwrite]

Output: <video name>.frames/ next to the video, containing
    0001_00-00-00.jpg, 0002_00-03-12.jpg, ...   (max 1280 px wide)
    index.json   {"video", "duration", "frames": [{"time", "file", "diff"}]}

How it works: one frame per --interval seconds is shrunk to 160x90 grey. The
difference between two frames is the fraction of pixels that changed by more
than 25 levels. Slides that share a template differ only in their text, which
looks no bigger than a person moving on camera, so the size of a change alone
can't tell them apart. What does: a slide or shared screen stops moving, a
camera never does. A frame becomes a candidate when
  - the picture is still (changed < --still since the previous sample) and
    differs from the last candidate by more than --change, or
  - the whole scene changed (> --scene, e.g. camera <-> screen share) and the
    picture has started to settle.
A candidate is only kept once no newer candidate follows within --settle
seconds, so clicking through windows or editing a shared sheet yields the
screen people stopped on, not every intermediate state. Moving the selected
cell or the mouse changes ~0.7% of the thumbnail; a new slide changes 3%+.

Live editing (a shared sheet being filled in) still changes the screen every
few seconds, so at most --max-frames are kept: the least novel candidates are
dropped first (see select()). A 2-hour editing session gave 342 candidates.
"""

import argparse
import io
import json
import re
import sys
import time
from pathlib import Path

from _bootstrap import fmt_duration, fmt_hms, relaunch_in_venv, setup_console

THUMB_SIZE = (160, 90)
PIXEL_CHANGE = 25  # grey levels; below this is compression noise
MAX_WIDTH = 1280
FRAME_NAME = re.compile(r"^\d{4}_\d{2}-\d{2}-\d{2}\.jpg$")


def to_image(frame):
    img = frame.to_image()
    if img.width > MAX_WIDTH:
        img = img.resize((MAX_WIDTH, round(img.height * MAX_WIDTH / img.width)))
    return img


def select(candidates, budget, scene, changed):
    """Trim to `budget` frames by repeatedly dropping the least novel one.

    Novelty is the change from the previous kept frame, so a run of small edits
    collapses into its first state while distinct screens survive. The first
    frame and whole-scene switches (camera <-> screen share) are always kept.
    """
    keep = list(candidates)
    if budget <= 0:
        return keep
    while len(keep) > budget:
        droppable = [(changed(keep[j]["thumb"], keep[j - 1]["thumb"]), j)
                     for j in range(1, len(keep)) if keep[j]["diff"] <= scene]
        if not droppable:
            break
        del keep[min(droppable)[1]]
    return keep


def main():
    setup_console()
    p = argparse.ArgumentParser(description="ดึงภาพตอนหน้าจอเปลี่ยนจากวิดีโอ")
    p.add_argument("input")
    p.add_argument("--out-dir", help="default: <video name>.frames next to the video")
    p.add_argument("--interval", type=float, default=1.0, help="seconds between sampled frames")
    p.add_argument("--change", type=float, default=0.02, help="changed-pixel fraction that counts as a new still screen")
    p.add_argument("--still", type=float, default=0.003, help="changed-pixel fraction between samples below which the picture is still")
    p.add_argument("--scene", type=float, default=0.3, help="changed-pixel fraction that counts as a whole new scene")
    p.add_argument("--settle", type=float, default=6, help="a frame is kept only if the screen then stays put this many seconds")
    p.add_argument("--max-frames", type=int, default=60, help="keep at most this many frames, dropping the least novel (0 = no limit)")
    p.add_argument("--overwrite", action="store_true", help="replace frames from an earlier run")
    args = p.parse_args()
    relaunch_in_venv(__file__, sys.argv[1:])

    import av
    import numpy as np

    src = Path(args.input).resolve()
    if not src.is_file():
        sys.exit(f"ไม่พบไฟล์: {src}")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else src.parent / f"{src.stem}.frames"
    index_path = out_dir / "index.json"
    previous = [f for f in out_dir.iterdir() if FRAME_NAME.match(f.name) or f == index_path] if out_dir.is_dir() else []
    if previous:
        if not args.overwrite:
            sys.exit(f"มีภาพจากรอบก่อนอยู่แล้ว จะไม่เขียนทับ: {out_dir}\nใช้ --out-dir อื่น หรือ --overwrite ถ้าต้องการแทนที่จริงๆ")
        for old in previous:
            old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    container = av.open(str(src))
    if not container.streams.video:
        sys.exit("ไฟล์นี้ไม่มีภาพวิดีโอ")
    stream = container.streams.video[0]
    stream.thread_type = "AUTO"
    duration = container.duration / 1_000_000 if container.duration else float(stream.duration * stream.time_base)
    print(f"วิดีโอ {src.name} · ยาว {fmt_duration(duration)} · {stream.width}x{stream.height}", flush=True)

    changed = lambda a, b: float((np.abs(a - b) > PIXEL_CHANGE).mean())
    candidates, reference, prev, pending = [], None, None, None
    next_t, started, last_report = 0.0, time.time(), time.time()

    def commit(c):
        buf = io.BytesIO()
        c.pop("image").save(buf, "JPEG", quality=85)
        candidates.append({**c, "jpeg": buf.getvalue()})

    for frame in container.decode(stream):
        t = frame.time
        if t is None or t < next_t:
            continue
        next_t = t + args.interval
        small = frame.reformat(width=THUMB_SIZE[0], height=THUMB_SIZE[1], format="gray").to_ndarray().astype(np.int16)

        if reference is None:
            candidate, diff = True, 0.0
        else:
            diff = changed(small, reference)
            motion = changed(small, prev)
            new_still_screen = motion < args.still and diff > args.change
            new_scene = diff > args.scene and motion < diff / 2
            candidate = new_still_screen or new_scene
        prev = small

        if pending and t - pending["time"] >= args.settle:
            commit(pending)
            pending = None
        if candidate:
            # A newer candidate within --settle replaces the pending one, but the
            # first frame of the video is always kept.
            if pending and candidates:
                diff = max(diff, pending["diff"])
            elif pending:
                commit(pending)
            pending = {"time": t, "image": to_image(frame), "thumb": small, "diff": diff}
            reference = small

        if time.time() - last_report >= 30:
            last_report = time.time()
            print(f"  {t / duration:.0%} [{fmt_hms(t)}/{fmt_hms(duration)}] · เข้าเกณฑ์ {len(candidates)} ภาพ", flush=True)

    if pending:
        commit(pending)
    container.close()

    kept = select(candidates, args.max_frames, args.scene, changed)
    frames = []
    for c in kept:
        name = f"{len(frames) + 1:04d}_{fmt_hms(c['time']).replace(':', '-')}.jpg"
        (out_dir / name).write_bytes(c["jpeg"])
        frames.append({"time": round(c["time"], 2), "file": name, "diff": round(c["diff"], 3)})
    index_path.write_text(
        json.dumps({"video": src.name, "duration": round(duration, 2), "frames": frames}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    dropped = f" (คัดจาก {len(candidates)} ภาพที่เข้าเกณฑ์)" if len(kept) < len(candidates) else ""
    print(f"เสร็จสิ้น · ได้ {len(frames)} ภาพ{dropped} · ใช้เวลา {fmt_duration(time.time() - started)}", flush=True)
    print(f"  {out_dir}", flush=True)


if __name__ == "__main__":
    main()
