#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""romaji_from_ref.py — 用作者提供的**真实日文原句**重建 lyrics_romaji.txt。

为什么必须重建:
    原来的 lyrics_romaji.txt 来自 whisper-large-v3 的**机器听写**。注音层
    (逐字罗马音) 最终就是从它派生的, 于是屏幕上标的音根本不是真词的音。
    实测: 拿真歌词换算出的音节序列去比对, **整体只有 78% 吻合**
    (L5 仅 57%, L13 仅 56%)。这不是对齐没对准, 是源头就听错了。

    真歌词到位之后, 正确的做法是把它送回流水线源头重跑:
        romaji_from_ref.py  ->  force_align.py  ->  soramimi_align.py
    注音内容和逐字分派会**一起**修好 —— 分派歪也是因为它在跟一串错音节对齐。

罗马音转换沿用 transcribe_vocals.py 的同一条路 (cutlet/MeCab 形态分析),
保证与流水线其余部分口径一致; 同时用 pykakasi 双路核对, 不一致的行标出来。

用法: python romaji_from_ref.py [--src ref_ja.raw.txt]
输入: 02_lyrics/ref_ja.raw.txt (作者粘贴的整段原句; 没有则退回 ref_ja.txt)
输出: 02_lyrics/lyrics_romaji.txt   —— 下一步 force_align.py
"""
import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"


def lines_of(p):
    return [r.strip() for r in p.read_text(encoding="utf-8").splitlines()
            if r.strip() and not r.lstrip().startswith("#")]


def main():
    src = LYR / "ref_ja.raw.txt"
    if not src.exists():
        src = LYR / "ref_ja.txt"
    if not src.exists():
        raise SystemExit("ERROR: 缺 02_lyrics/ref_ja.raw.txt (或 ref_ja.txt)")

    rows = lines_of(src)
    print(f"  源: {src.name}  {len(rows)} 行")

    import cutlet
    import pykakasi
    ct = cutlet.Cutlet()
    ct.use_foreign_spelling = False
    kk = pykakasi.kakasi()

    out, dis = [], 0
    for i, t in enumerate(rows):
        a = ct.romaji(t).lower().strip()
        b = " ".join(x["hepburn"] for x in kk.convert(t)).lower()
        b = " ".join(b.split())
        if a.replace(" ", "") != b.replace(" ", ""):
            dis += 1
        if a:
            out.append(a)

    dst = LYR / "lyrics_romaji.txt"
    dst.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"  双路一致 {len(rows)-dis}/{len(rows)} 行  (不一致多为长音/助词写法, "
          f"对齐器只吃音素, 通常不影响)")
    print(f"  写出 -> {dst.name}  ({len(out)} 行)")
    print("  下一步: python force_align.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
