"""รวมภาพหน้าจอ + ข้อความถอดเสียง (+ สรุปจาก Claude) เป็นรายงานประชุม HTML ไฟล์เดียว

Usage:
    python report.py <video> [--transcript X.timestamped.txt] [--frames X.frames]
                     [--notes notes.json] [--summary summary.md] [--offset SEC]
                     [--out FILE] [--overwrite]

Defaults look next to the video: <name>.timestamped.txt (or <name>.accurate.timestamped.txt)
and <name>.frames/. Output: <name>.report.html next to the video. Images and the
video are referenced by relative path, so keep the report beside them.

notes.json (optional, written by Claude after looking at the frames):
    {"0003_00-12-30.jpg": "สไลด์: แผนงาน Q4"}  or  {"0003_00-12-30.jpg": {"title": "...", "note": "..."}}
summary.md (optional): meeting summary shown at the top. Supports #/##/### headings,
"- " bullets, **bold**, and blank-line paragraphs.
"""

import argparse
import html
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

from _bootstrap import fmt_hms, setup_console

LINE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\]\s?(.*)$")


def read_transcript(path, offset=0.0):
    lines = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        m = LINE.match(raw.strip())
        if m:
            h, mi, s, text = m.groups()
            t = int(h) * 3600 + int(mi) * 60 + int(s) + offset
            if t >= 0:
                lines.append((round(t), text))
    return lines


def read_notes(path):
    if not path:
        return {}
    notes = {}
    for name, value in json.loads(Path(path).read_text(encoding="utf-8")).items():
        notes[name] = value if isinstance(value, dict) else {"title": str(value)}
    return notes


def inline_md(text):
    return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html.escape(text))


def markdown_to_html(md):
    """Just enough Markdown for a meeting summary."""
    out, bullets, para = [], [], []

    def flush():
        if bullets:
            out.append("<ul>" + "".join(f"<li>{inline_md(b)}</li>" for b in bullets) + "</ul>")
            bullets.clear()
        if para:
            out.append(f"<p>{inline_md(' '.join(para))}</p>")
            para.clear()

    for line in md.splitlines():
        stripped = line.strip()
        heading = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if heading:
            flush()
            level = len(heading.group(1)) + 1  # page title is h1
            out.append(f"<h{level}>{inline_md(heading.group(2))}</h{level}>")
        elif re.match(r"^[-*]\s+", stripped):
            if para:
                flush()
            bullets.append(re.sub(r"^[-*]\s+", "", stripped))
        elif not stripped:
            flush()
        else:
            if bullets:
                flush()
            para.append(stripped)
    flush()
    return "\n".join(out)


def find_default(video, candidates):
    for name in candidates:
        path = video.parent / name
        if path.exists():
            return path
    return None


def ts_link(seconds):
    return f'<a href="#" class="ts" data-t="{seconds}">{fmt_hms(seconds)}</a>'


def build_sections(frames, lines, duration):
    """Each frame owns the transcript lines from its time until the next frame."""
    if not frames:
        return [{"time": 0, "end": duration, "frame": None, "lines": lines}]
    sections = []
    for i, frame in enumerate(frames):
        start = 0 if i == 0 else frame["time"]
        end = frames[i + 1]["time"] if i + 1 < len(frames) else float("inf")
        sections.append({
            "time": frame["time"],
            "end": end if end != float("inf") else duration,
            "frame": frame,
            "lines": [(t, text) for t, text in lines if start <= t < end],
        })
    return sections


CSS = """
:root{--bg:#fafaf9;--card:#fff;--text:#1c1917;--muted:#78716c;--line:#e7e5e4;--accent:#0f766e;--accent-bg:#f0fdfa}
@media (prefers-color-scheme:dark){:root{--bg:#1c1917;--card:#292524;--text:#f5f5f4;--muted:#a8a29e;--line:#44403c;--accent:#5eead4;--accent-bg:#134e4a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.7 "Sarabun","Noto Sans Thai","Leelawadee UI","Tahoma",sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:24px 16px 80px}
h1{font-size:1.6rem;margin:0 0 4px}
.meta{color:var(--muted);margin-bottom:20px}
.player{position:sticky;top:0;z-index:5;background:var(--bg);padding:8px 0;margin-bottom:16px}
.player video{width:100%;max-height:28vh;background:#000;border-radius:8px}
.summary{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 20px;margin-bottom:24px}
.section{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,6fr);gap:20px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:16px;break-inside:avoid}
.section img{width:100%;border-radius:6px;border:1px solid var(--line);cursor:zoom-in}
.head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;margin-bottom:6px}
.title{font-weight:600}
.note{color:var(--muted);margin:0 0 8px}
.lines p{margin:0 0 6px}
.ts{color:var(--accent);background:var(--accent-bg);text-decoration:none;font-variant-numeric:tabular-nums;font-size:.85em;padding:1px 6px;border-radius:4px;margin-right:6px;white-space:nowrap}
.ts:hover{text-decoration:underline}
.empty{color:var(--muted);font-style:italic}
@media (max-width:760px){.section{grid-template-columns:1fr}}
@media print{.player{display:none}body{background:#fff;color:#000}.section,.summary{border-color:#ccc}}
"""

JS = """
const v=document.querySelector('video');
document.addEventListener('click',e=>{const a=e.target.closest('.ts');if(!a)return;e.preventDefault();
 if(!v)return;v.currentTime=+a.dataset.t;v.play();v.scrollIntoView({block:'nearest'});});
document.querySelectorAll('.section img').forEach(i=>i.addEventListener('click',()=>window.open(i.src)));
"""


def render(video, report_path, sections, notes, summary_html, duration, transcript_name):
    rel = lambda p: quote(os.path.relpath(p, report_path.parent).replace(os.sep, "/"))
    parts = []
    for s in sections:
        frame = s["frame"]
        note = notes.get(frame["file"], {}) if frame else {}
        title = html.escape(note.get("title", "")) if note.get("title") else ""
        img = (f'<img loading="lazy" src="{rel(s["frame_path"])}" alt="ภาพหน้าจอเวลา {fmt_hms(s["time"])}">'
               if frame else "")
        lines = "".join(f"<p>{ts_link(t)}{html.escape(text)}</p>" for t, text in s["lines"]) or \
            '<p class="empty">ไม่มีเสียงพูดในช่วงนี้</p>'
        parts.append(f"""
<section class="section">
  <div>{img}</div>
  <div>
    <div class="head">{ts_link(s["time"])}<span class="title">{title}</span>
      <span class="meta">ถึง {fmt_hms(s["end"])}</span></div>
    {f'<p class="note">{html.escape(note["note"])}</p>' if note.get("note") else ""}
    <div class="lines">{lines}</div>
  </div>
</section>""")

    frame_count = sum(1 for s in sections if s["frame"])
    return f"""<!doctype html>
<html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(video.stem)} · รายงานประชุม</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<h1>{html.escape(video.stem)}</h1>
<div class="meta">ยาว {fmt_hms(duration)} · {frame_count} ภาพหน้าจอ · ข้อความจาก {html.escape(transcript_name or "—")}</div>
<div class="player"><video controls preload="metadata" src="{rel(video)}"></video></div>
{f'<div class="summary">{summary_html}</div>' if summary_html else ""}
{"".join(parts)}
</div><script>{JS}</script></body></html>
"""


def main():
    setup_console()
    p = argparse.ArgumentParser(description="รวมภาพหน้าจอและข้อความถอดเสียงเป็นรายงานประชุม")
    p.add_argument("video")
    p.add_argument("--transcript")
    p.add_argument("--frames", help="folder made by keyframes.py")
    p.add_argument("--notes", help="JSON: frame file -> title or {title, note}")
    p.add_argument("--summary", help="Markdown summary placed at the top")
    p.add_argument("--offset", type=float, default=0.0,
                   help="seconds added to transcript times, for a transcript made from a separate recording")
    p.add_argument("--out", help="default: <video name>.report.html next to the video")
    p.add_argument("--overwrite", action="store_true")
    args = p.parse_args()

    video = Path(args.video).resolve()
    if not video.is_file():
        sys.exit(f"ไม่พบไฟล์: {video}")
    out = Path(args.out).resolve() if args.out else video.parent / f"{video.stem}.report.html"
    if out.exists() and not args.overwrite:
        sys.exit(f"มีรายงานอยู่แล้ว จะไม่เขียนทับ: {out.name}\nใช้ --out ชื่อใหม่ หรือ --overwrite ถ้าต้องการแทนที่จริงๆ")

    transcript = Path(args.transcript).resolve() if args.transcript else find_default(
        video, [f"{video.stem}.accurate.timestamped.txt", f"{video.stem}.timestamped.txt"])
    frames_dir = Path(args.frames).resolve() if args.frames else find_default(video, [f"{video.stem}.frames"])
    if not transcript and not frames_dir:
        sys.exit("ไม่พบทั้งไฟล์ถอดเสียงและโฟลเดอร์ภาพ — รัน transcribe.py และ/หรือ keyframes.py ก่อน")

    lines = read_transcript(transcript, args.offset) if transcript else []
    index = json.loads((frames_dir / "index.json").read_text(encoding="utf-8")) if frames_dir else {"frames": []}
    frames = index["frames"]
    duration = index.get("duration") or (lines[-1][0] if lines else 0)

    sections = build_sections(frames, lines, duration)
    for s in sections:
        if s["frame"]:
            s["frame_path"] = frames_dir / s["frame"]["file"]
    summary_html = markdown_to_html(Path(args.summary).read_text(encoding="utf-8")) if args.summary else ""

    out.write_text(
        render(video, out, sections, read_notes(args.notes), summary_html, duration,
               transcript.name if transcript else None),
        encoding="utf-8",
    )
    print(f"สร้างรายงานแล้ว: {out}", flush=True)
    print(f"  {len(frames)} ภาพ · {len(lines)} บรรทัดข้อความ", flush=True)


if __name__ == "__main__":
    main()
