#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""yohane 音节级强制对齐 —— 走库调用而非 CLI。

为什么不用 CLI:
    CLI 只会把结果渲染成 .ass。我需要的是每个音节的浮点起止秒, 好把时间轴重新
    映射到中文空耳字上。yohane.subtitles.time_lyrics() 就返回这个:
        @dataclass
        class TimedSyllable:
            value: str; start_s: float; end_s: float
    返回 list[list[TimedSyllable | None]], 每行一个 list, None 表示词边界(空格)。

对齐模型:
    NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn —— 在 MMS-300m 上针对
    日文卡拉OK微调过的版本 (~1.18 GiB)。作者说它专门缓解"行尾音节被压短"的问题,
    那是默认 MMS_FA 的已知缺陷。

显存:
    对齐器不分块 —— 整首歌一次前向 (yohane/audio.py: emission, _ = self.model(waveform))
    所以 VRAM 随时长线性增长, 全程 fp32 无 autocast。4-5 分钟估算峰值 3-4 GB, 8 GB 够。
    本脚本实测并打印峰值, 不靠估算。

坑:
    - 输入音频文件名不能带多余的点。yohane 用 with_suffix() 推导输出路径,
      'x.vocals.wav' 会被当成 stem='x' -> 静默覆盖别的结果。
    - 路径不存在时它不报错, 而是把字符串丢给 yt-dlp 去下载。
    - time_lyrics() 内部断言消耗完所有 token span, 不匹配会抛
      RuntimeError('not all spans were used')。
"""
import io
import json
import os
import sys
import inspect
import shutil
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

os.add_dll_directory(r"C:\Users\59827\karaoke\tools\ffmpeg-shared71\bin")
os.environ["PATH"] = r"C:\Users\59827\karaoke\tools\ffmpeg\bin" + os.pathsep + os.environ["PATH"]

ROOT = Path(__file__).resolve().parent.parent
STEMS = ROOT / "01_stems"
LYR = ROOT / "02_lyrics"
ALIGNER = "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"


def find_vocals():
    c = sorted(STEMS.glob("*Vocals*.wav")) or sorted(STEMS.glob("*vocals*.wav"))
    if not c:
        raise SystemExit(f"ERROR: {STEMS} 下没有 Vocals wav")
    return c[0]


def main():
    import torch
    from yohane import Yohane
    from yohane.subtitles import time_lyrics

    # 先自省真实签名, 不盲信文档
    print("=== Yohane.__init__ 签名 ===")
    print("  ", inspect.signature(Yohane.__init__))
    print("=== time_lyrics 签名 ===")
    print("  ", inspect.signature(time_lyrics))
    print()

    src = find_vocals()
    # 拷成无多余点的文件名, 规避 with_suffix 截断坑
    clean = STEMS / "vocals.wav"
    if not clean.exists() or clean.stat().st_mtime < src.stat().st_mtime:
        shutil.copy2(src, clean)
    print(f"vocals : {clean.name}  ({clean.stat().st_size/1e6:.1f} MB)")

    romaji = LYR / "lyrics_romaji.txt"
    if not romaji.exists():
        raise SystemExit(f"ERROR: 缺 {romaji}, 先跑 transcribe_vocals.py")
    text = romaji.read_text(encoding="ascii", errors="ignore")
    n_lines = len([l for l in text.splitlines() if l.strip()])
    print(f"lyrics : {n_lines} 行罗马音\n")

    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    y = Yohane(separator=None, forced_aligner=ALIGNER)
    y.load_song(clean)
    y.load_lyrics(text)
    print("对齐中 (首次运行需下载 ~1.18 GiB 模型)...")
    y.force_align()

    if torch.cuda.is_available():
        print(f"峰值显存: {torch.cuda.max_memory_allocated()/1e9:.2f} GB "
              f"/ {torch.cuda.get_device_properties(0).total_memory/1e9:.2f} GB")

    lines = time_lyrics(
        y.lyrics, *y.forced_aligned_audio,
        y.forced_aligner.tokenize, *y.forced_alignment,
    )

    out = []
    for idx, (ln, syls) in enumerate(zip(y.lyrics.lines, lines)):
        items = []
        for s in syls:
            if s is None:
                items.append(None)          # 词边界
            else:
                items.append({"v": s.value, "start_s": round(s.start_s, 4),
                              "end_s": round(s.end_s, 4)})
        real = [i for i in items if i]
        out.append({
            "line": idx,
            "raw": ln.raw,
            "n_syllables": len(real),
            "start_s": real[0]["start_s"] if real else None,
            "end_s": real[-1]["end_s"] if real else None,
            "syllables": items,
        })

    p = LYR / "syllables_ja.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

    tot = sum(o["n_syllables"] for o in out)
    print(f"\n对齐完成: {len(out)} 行 / {tot} 音节")
    print(f"写出 -> {p}")
    print("\n前 3 行时间轴抽查:")
    for o in out[:3]:
        print(f"  L{o['line']}  {o['start_s']:.2f}s - {o['end_s']:.2f}s  "
              f"({o['n_syllables']} syl)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
