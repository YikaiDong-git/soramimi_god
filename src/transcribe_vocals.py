#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""对分离出的人声做日文 ASR, 并转成 yohane 需要的罗马音。

为什么用 ASR 而不是抓歌词站:
    1. 强制对齐要的是"实际唱出来的东西"。纸面歌词和演唱常有出入 —— 省略助词、
       重复段、气声、DAOKO 的 rap 段落断句 —— 用纸面词去对齐会在这些地方崩。
    2. ASR 的分句天然贴合演唱停顿, 正好是 yohane 要求的"一行一句"。
    3. 不依赖第三方站点的可用性和反爬。

为什么必须转罗马音 (本地实测 2026-07-29):
    yohane.lyrics.normalize_uroman('打上花火')       -> ''
    yohane.lyrics.normalize_uroman('うちあげはなび') -> ''
    它的对齐模型 MMS_FA 词表只有 27 个拉丁字母 + blank, 汉字假名会被 re.sub 全部删掉,
    且不报错 —— 静默产出空转录。

双路交叉验证:
    cutlet (MeCab 形态分析) 为主, pykakasi (词典法) 为辅。两者不一致的行会被标出来,
    因为汉字读音歧义 (例: 上=うえ/かみ/じょう) 是这一步唯一的系统性错误来源。
"""
import io
import json
import os
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

os.add_dll_directory(r"C:\Users\59827\karaoke\tools\ffmpeg-shared71\bin")

ROOT = Path(__file__).resolve().parent.parent
STEMS = ROOT / "01_stems"
LYR = ROOT / "02_lyrics"
LYR.mkdir(parents=True, exist_ok=True)

MODEL_ID = "openai/whisper-large-v3"


def find_vocals():
    cands = sorted(STEMS.glob("*Vocals*.wav")) or sorted(STEMS.glob("*vocals*.wav"))
    if not cands:
        raise SystemExit(f"ERROR: {STEMS} 下没有 Vocals wav, 先跑 separate_vocals.py")
    return cands[0]


def load_audio_16k(wav):
    """自己读音频重采样到 16 kHz 单声道。

    不把文件路径丢给 transformers: 它内部走 audio_utils.ffmpeg_read(), 调的是裸
    "ffmpeg" 命令, PATH 上没有就直接 ValueError。自己读 numpy 数组能整个绕开这条依赖。
    """
    import librosa
    import numpy as np
    import soundfile as sf

    x, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    x = x.mean(axis=1)                                  # 转单声道
    if sr != 16000:
        x = librosa.resample(x, orig_sr=sr, target_sr=16000)
    print(f"audio  : {len(x)/16000:.1f}s @16kHz mono  (原 {sr} Hz)")
    return np.ascontiguousarray(x, dtype=np.float32)


def transcribe(wav):
    import torch
    from transformers import pipeline

    dev = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if dev == "cuda" else torch.float32
    print(f"device={dev} dtype={dtype}  model={MODEL_ID}")

    audio = load_audio_16k(wav)

    asr = pipeline(
        "automatic-speech-recognition",
        model=MODEL_ID,
        dtype=dtype,
        device=dev,
        chunk_length_s=30,
        stride_length_s=5,
    )
    out = asr(
        {"raw": audio, "sampling_rate": 16000},
        return_timestamps=True,
        generate_kwargs={"language": "japanese", "task": "transcribe"},
    )
    if dev == "cuda":
        print(f"peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
    return out


def romanize(lines):
    import cutlet
    import pykakasi

    ct = cutlet.Cutlet()
    ct.use_foreign_spelling = False
    kks = pykakasi.kakasi()

    rows = []
    for i, t in enumerate(lines):
        a = ct.romaji(t).lower()
        b = " ".join(x["hepburn"] for x in kks.convert(t)).lower()
        norm = lambda s: "".join(c for c in s if c.isalpha() or c == " ").split()
        rows.append({
            "i": i,
            "ja": t,
            "romaji_cutlet": a,
            "romaji_pykakasi": b,
            "agree": norm(a) == norm(b),
        })
    return rows


def main():
    wav = find_vocals()
    print(f"vocals : {wav.name}  ({wav.stat().st_size/1e6:.1f} MB)\n")

    res = transcribe(wav)
    chunks = res.get("chunks") or []
    segs = []
    for c in chunks:
        ts = c.get("timestamp") or (None, None)
        txt = (c.get("text") or "").strip()
        if not txt:
            continue
        segs.append({"start": ts[0], "end": ts[1], "ja": txt})

    print(f"\nASR: {len(segs)} 段")
    (LYR / "asr_segments.json").write_text(
        json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8")

    rows = romanize([s["ja"] for s in segs])
    for r, s in zip(rows, segs):
        r["start"] = s["start"]
        r["end"] = s["end"]

    (LYR / "romaji_check.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    # yohane 输入: 一行一句纯罗马音 (ASCII), 空行会被它丢掉所以先滤掉
    romaji_lines = [r["romaji_cutlet"] for r in rows if r["romaji_cutlet"].strip()]
    (LYR / "lyrics_romaji.txt").write_text("\n".join(romaji_lines) + "\n",
                                           encoding="ascii", errors="ignore")

    n_dis = sum(1 for r in rows if not r["agree"])
    print(f"罗马音双路一致: {len(rows)-n_dis}/{len(rows)}   不一致 {n_dis} 行 (见 romaji_check.json)")
    print(f"写出 -> {LYR/'lyrics_romaji.txt'}  ({len(romaji_lines)} 行)")
    print(f"      -> {LYR/'asr_segments.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
