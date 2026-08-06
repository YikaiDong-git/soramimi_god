#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""measure_metrics.py — 直接从 libass 的渲染结果量排版度量, 不靠推算。

为什么需要它:
    make_ass.py 里的 GLYPH_W=61.1 / SPACE_ADV=68.6 是历史上"实测"来的, 但没有
    留下测法。PIL 量同一个字体给出全角 61.0 (吻合) 而空格只有 18.0 (差 3.8 倍) ——
    两者必有一个错。版式脚本要按格子对齐注音, 差 1px 都会累积成肉眼可见的错位,
    所以这里用**渲染 -> 数像素**的办法把真值钉死。

测法:
    在纯黑底上左对齐画一串已知内容, 扫出墨迹的最右列。
    两串只差一个待测元素, 相减即得该元素的前进宽度。
    (单串绝对值会含描边外扩, 相减刚好抵消。)

用法: python measure_metrics.py
"""
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "05_qc" / "_metrics"
FF = "C:/Users/59827/karaoke/tools/ffmpeg/bin/ffmpeg.exe"
FONT = "Microsoft YaHei"
SIZE = 78

HDR = f"""[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: M,{FONT},{SIZE},&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def right_edge(png):
    """返回墨迹最右列的 x (无墨迹返回 -1)。"""
    im = Image.open(png).convert("L")
    w, h = im.size
    px = im.load()
    for x in range(w - 1, -1, -1):
        for y in range(0, h, 2):
            if px[x, y] > 40:
                return x
    return -1


def measure(label, text):
    WORK.mkdir(parents=True, exist_ok=True)
    ass = WORK / "m.ass"
    ass.write_text(HDR + f"Dialogue: 0,0:00:00.00,0:00:10.00,M,,0,0,0,,"
                         rf"{{\an7\pos(0,300)\bord0\shad0}}{text}" + "\n",
                   encoding="utf-8-sig")
    out = WORK / f"{label}.png"
    cmd = [FF, "-y", "-loglevel", "error", "-f", "lavfi",
           "-i", "color=c=black:s=1920x1080:d=0.1",
           "-vf", f"ass={ass.name}", "-frames:v", "1", str(out)]
    r = subprocess.run(cmd, cwd=str(ass.parent), capture_output=True, text=True)
    if not out.exists():
        raise SystemExit(f"render failed: {r.stderr[-400:]}")
    return right_edge(out)


def main():
    G = "好"
    N = 20
    base = measure("base", G * N)                     # N 个全角
    base2 = measure("base2", G * (N + 1))             # N+1 个全角
    glyph = base2 - base
    print(f"全角前进宽度  GLYPH_W = {glyph:.1f} px   "
          f"(make_ass 写的是 {61.1})")

    probes = {
        r"\h  (硬空格)": G * (N // 2) + r"\h" + G * (N // 2),
        "U+3000 全角空格": G * (N // 2) + "\u3000" + G * (N // 2),
        "U+0020 半角空格": G * (N // 2) + " " + G * (N // 2),
    }
    print()
    for name, s in probes.items():
        w = measure("p" + str(abs(hash(name)) % 999), s) - base
        print(f"{name:<18} = {w:6.1f} px    ({w / glyph:.3f} 个全角)")

    # \fscx 是否线性作用于 \h
    print()
    for pct in (25, 50, 100, 200):
        s = G * (N // 2) + rf"{{\fscx{pct}}}\h{{\fscx100}}" + G * (N // 2)
        w = measure(f"f{pct}", s) - base
        print(rf"\fscx{pct:<4} \h        = {w:6.1f} px")

    # Spacing 的作用位置
    print()
    for fsp in (0, 2, 6):
        s = rf"{{\fsp{fsp}}}" + G * N
        w = measure(f"s{fsp}", s)
        print(rf"\fsp{fsp} 下 {N} 个全角右缘 = {w:6.1f} px  "
              f"(每字 {(w + 1) / N:.2f})")


if __name__ == "__main__":
    main()
