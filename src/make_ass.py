#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成逐字卡拉OK .ass (单层空耳)。

ASS 卡拉OK的颜色语义 (容易搞反):
    SecondaryColour = 还没唱到时的颜色
    PrimaryColour   = 已经唱过之后的颜色
    所以"白字唱到变黄"要写成 Secondary=白, Primary=黄。

用 \\kf 而不是 \\k:
    \\k  是整字瞬间跳色
    \\kf 是从左到右平滑扫过 (经典 KTV 观感), libass 支持
    时长单位都是厘秒 (cs)。

时长必须 gapless:
    每个字的 \\kf 值 = 下一个字的起点 - 本字起点。若用本字自己的 end,
    字与字之间的空隙会让扫光停顿, 看起来一顿一顿的。最后一个字才用自己的 end。

颜色写法 &HAABBGGRR& —— BGR 倒序, 且 AA 是"透明度"(00=不透明)。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"
SUBS = ROOT / "03_subs"
SUBS.mkdir(parents=True, exist_ok=True)

PLAY_W, PLAY_H = 1920, 1080
FONT = "Microsoft YaHei"
FONT_SIZE = 78
OUTLINE = 4.0
SHADOW = 2.0
MARGIN_V = 96

# name -> (未唱 Secondary, 已唱 Primary, 描边 Outline)
PALETTES = {
    "ktv_yellow": ("&H00FFFFFF&", "&H0000D7FF&", "&H00202020&"),   # 白 -> 金黄
    "hanabi_pink": ("&H00FFFFFF&", "&H008C5AFF&", "&H00201028&"),  # 白 -> 烟花橙粉
    "cool_cyan":  ("&H00FFFFFF&", "&H00F0C000&", "&H00301808&"),   # 白 -> 青蓝
}


def cs(t: float) -> int:
    return int(round(t * 100))


def ts(t: float) -> str:
    """秒 -> ASS 的 H:MM:SS.cc"""
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def header(pal_name: str) -> str:
    sec, pri, out = PALETTES[pal_name]
    return f"""[Script Info]
; 空耳卡拉OK — 打上花火
; 生成: make_ass.py  配色: {pal_name}
Title: dashanghuahuo soramimi ({pal_name})
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sora,{FONT},{FONT_SIZE},{pri},{sec},{out},&H80000000&,-1,0,0,0,100,100,2,0,1,{OUTLINE},{SHADOW},2,60,60,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def build_line(line: dict) -> str:
    """一行 -> 一条 Dialogue。"""
    chars = line["chars"]
    start = chars[0]["start"]
    end = chars[-1]["end"]

    parts = []
    for i, c in enumerate(chars):
        nxt = chars[i + 1]["start"] if i + 1 < len(chars) else c["end"]
        dur = cs(max(nxt - c["start"], 0.04))       # gapless, 且不给 0
        parts.append(f"{{\\kf{dur}}}{c['char']}{c['trailing']}")

    text = "{\\fad(120,120)}" + "".join(parts)
    return (f"Dialogue: 0,{ts(start)},{ts(end + 0.25)},Sora,,0,0,0,,{text}")


def main():
    p = LYR / "soramimi_timed.json"
    if not p.exists():
        raise SystemExit(f"ERROR: 缺 {p}, 先跑 soramimi_align.py")
    lines = json.loads(p.read_text(encoding="utf-8"))

    for name in PALETTES:
        body = [build_line(l) for l in lines]
        out = SUBS / f"soramimi_{name}.ass"
        out.write_text(header(name) + "\n".join(body) + "\n", encoding="utf-8-sig")
        print(f"写出 -> {out.name}  ({len(body)} 行)")

    # 抽查第一行, 便于肉眼核对 \kf 值
    if lines:
        print("\n第 1 行 Dialogue 抽查:")
        print(" ", build_line(lines[0])[:300])
        tot = sum(len(l["chars"]) for l in lines)
        span = lines[-1]["end"] - lines[0]["start"]
        print(f"\n共 {len(lines)} 行 / {tot} 字, 覆盖 {lines[0]['start']:.1f}s - {lines[-1]['end']:.1f}s ({span:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
