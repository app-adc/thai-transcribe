# thai-transcribe

สกิลสำหรับ [Claude Code](https://claude.com/claude-code) ที่ถอดเสียงพูด**ภาษาไทย**เป็นข้อความ:
- **ไฟล์ที่รองรับ:** .m4a, .webm, .mp3, .wav, .mp4 ยาวหลายชั่วโมงได้
- **ทำงานในเครื่อง:** ฟรี และไม่ส่งไฟล์เสียงออกไปนอกเครื่อง
- **โมเดล:** [Thonburian Whisper](https://github.com/biodatlab/thonburian-whisper) ที่ฝึกมาสำหรับภาษาไทยโดยเฉพาะ

## ติดตั้ง

ใน Claude Code พิมพ์:

```
/plugin marketplace add app-adc/thai-transcribe
/plugin install thai-transcribe@thai-transcribe
```

ต้องมี Python 3.9 ขึ้นไปในเครื่อง ส่วนอย่างอื่นสกิลจะติดตั้งให้เองตอนใช้งานครั้งแรก:
- venv และ faster-whisper
- โมเดล ขนาดราว 1.6 GB

ไฟล์ทั้งหมดนี้เก็บไว้ที่ `~/.thai-transcribe` ถ้าอยากเก็บที่อื่น เช่น ไดรฟ์ D ให้ตั้งค่า env ใน `~/.claude/settings.json`:

```json
{ "env": { "THAI_TRANSCRIBE_HOME": "D:\\thai-transcribe" } }
```

## ใช้งาน

พิมพ์ใน Claude Code ได้เลย เช่น:
- `ถอดเสียงไฟล์ ประชุม.m4a`
- `/thai-transcribe recording.webm`
- `ถอดใหม่แบบแม่นยำ` เพื่อใช้ `--model accurate` โดยบันทึกเป็นไฟล์ใหม่และไม่ทับไฟล์เดิม

ผลลัพธ์จะอยู่ข้างไฟล์เสียง:
- `<ชื่อ>.txt` ข้อความล้วน
- `<ชื่อ>.timestamped.txt` มีเวลา `[HH:MM:SS]` กำกับ

ถ้างานหยุดกลางทาง สั่งใหม่แล้วจะทำต่อจากจุดเดิม

## ความเร็วและความแม่นยำ

วัดบนโน้ตบุ๊ก Ryzen 5 4500U ที่ใช้ CPU อย่างเดียว:

| โมเดล | ไฟล์ประชุม 2 ชม. 10 นาที | ความผิดพลาด (CER) จากเสียงทดสอบ |
|---|---|---|
| `fast` (ค่าเริ่มต้น) | 1 ชม. 30 นาที | ราว 2% |
| `accurate` | 1 ชม. 45 นาที | ราว 0.4% |

ถ้ามีการ์ดจอ NVIDIA ใช้ `--device cuda` จะเร็วขึ้นมาก แต่ต้องติดตั้ง CUDA 12 และ cuDNN ก่อน

## เรียกใช้นอก Claude Code

```bash
python skills/thai-transcribe/scripts/transcribe.py "ไฟล์เสียง.m4a" [--model accurate] [--suffix accurate]
```

## เครดิต
- [Thonburian Whisper](https://github.com/biodatlab/thonburian-whisper) โดย BioDataLab
- โมเดลที่แปลงเป็นรูปแบบ CTranslate2 แล้ว:
  - [pariya47/distill-whisper-th-large-v3-ct2](https://huggingface.co/pariya47/distill-whisper-th-large-v3-ct2)
  - [Vinxscribe/biodatlab-whisper-th-medium-faster](https://huggingface.co/Vinxscribe/biodatlab-whisper-th-medium-faster)
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
