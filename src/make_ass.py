#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成逐字卡拉OK .ass —— 滚动扫光 (\\kf) + 逐字配色方案。

默认动画方式: 滚动扫光
    \\kf 是从左到右平滑扫过, 一行只有一条 Dialogue, 字始终待在原地。
    对眼睛最友好, 也最适合真正跟唱。
    (逐字弹出/旋转那套动画引擎保留在 effects.py + render_effects.py + make_mixed.py 里,
     需要时用 `python render_effects.py` 生成, 见 FAVORITES.md。)

配色方案怎么和扫光共存:
    ASS 里 \\kf 的语义是 SecondaryColour -> PrimaryColour。
    样式里把 Secondary 设成白色(未唱), 然后在每个字前面内联一个 \\1c 覆盖 PrimaryColour,
    这个字扫过之后就变成它自己的颜色。
    形式: {\\1c&H..&\\kf25}字
    于是"彩虹/寒冰/火焰"这些逐字渐变方案, 在滚动扫光下照样成立。

相邻行重叠的修法 (实测 13 对相邻行里有 8 对间隔 < 0.8s, 其中 1 对间隔为 0):
    整行的提前出现/延后消失量必须按"与邻行的实际间隔"逐行收缩, 不能用固定值。
    lead = min(设定值, 间隔 * SHARE), SHARE < 0.5 保证两行各让一步后仍留有空隙。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"
SUBS = ROOT / "03_subs"

PLAY_W, PLAY_H = 1920, 1080
FONT = "Microsoft YaHei"
FONT_SIZE = 78
OUTLINE = 4.0
SHADOW = 2.0
MARGIN_V = 96

C_UNSUNG = r"&H00FFFFFF&"     # 未唱: 白
C_OUTLINE = r"&H00301808&"

LEAD_IN = 350                  # ms 期望的提前出现量 (会被邻行间隔压缩)
LEAD_OUT = 350                 # ms 期望的延后消失量
GAP_SHARE = 0.40               # 每行最多吃掉间隔的 40%, 两行合计 80%, 留 20% 空隙
FADE = 110                     # ms 淡入淡出


# ---------------------------------------------------------------- 配色方案
# scheme(i, n) -> ASS 颜色 &HAABBGGRR& (BGR 倒序, AA=00 不透明)
def _rainbow(i, n):
    t = i / max(n - 1, 1)
    r, g, b = int(255 * (1 - t)), int(180 + 60 * t), int(120 + 135 * t)
    return f"&H00{b:02X}{g:02X}{r:02X}&"


def _ice(i, n):
    t = i / max(n - 1, 1)
    r = int(255 - 110 * t)
    g = int(235 - 40 * t)
    return f"&H00FF{g:02X}{r:02X}&"


def _fire(i, n):
    t = i / max(n - 1, 1)
    g = int(225 - 170 * t)
    return f"&H0000{g:02X}FF&"


SCHEMES = {
    "rainbow": (_rainbow, "彩虹：每字一个色相，沿行暖→冷渐变"),
    "ice":     (_ice, "寒冰：白→青→蓝沿行渐变，清冷"),
    "fire":    (_fire, "火焰：黄→橙→红沿行渐变"),
    "gold":    (lambda i, n: r"&H0000D7FF&", "鎏金：统一金色"),
    "cyan":    (lambda i, n: r"&H00F0C000&", "青蓝：统一冷色"),
    "yellow":  (lambda i, n: r"&H0000D7FF&", "经典 KTV 黄"),
}

# 分段方案: (起行, 止行含, 配色)  行号 0 起算; 止行为 None 表示到末尾
DEFAULT_PLAN = [(0, 8, "ice"), (9, None, "rainbow")]


def cs(t):
    return int(round(t * 100))


def ts(t):
    if t < 0:
        t = 0.0
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    return f"{h:d}:{m:02d}:{t % 60:05.2f}"


def header(tag):
    return f"""[Script Info]
; 空耳卡拉OK — 打上花火
; make_ass.py  滚动扫光(\\kf) + 配色方案: {tag}
Title: dashanghuahuo soramimi ({tag})
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: {PLAY_W}
PlayResY: {PLAY_H}

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sora,{FONT},{FONT_SIZE},{C_UNSUNG},{C_UNSUNG},{C_OUTLINE},&H80000000&,-1,0,0,0,100,100,2,0,1,{OUTLINE},{SHADOW},2,60,60,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def scheme_for(idx, plan):
    for lo, hi, name in plan:
        if idx >= lo and (hi is None or idx <= hi):
            return name
    return plan[-1][2]


def build(lines, plan):
    ev, report = [], []
    for k, line in enumerate(lines):
        chars = line["chars"]
        t0, t1 = chars[0]["start"], chars[-1]["end"]

        # 按与邻行的真实间隔收缩 lead, 保证永不重叠
        gap_prev = (t0 - lines[k - 1]["chars"][-1]["end"]) if k > 0 else 99.0
        gap_next = (lines[k + 1]["chars"][0]["start"] - t1) if k + 1 < len(lines) else 99.0
        lin = min(LEAD_IN / 1000, max(gap_prev, 0) * GAP_SHARE)
        lout = min(LEAD_OUT / 1000, max(gap_next, 0) * GAP_SHARE)

        name = scheme_for(line["line"], plan)
        color = SCHEMES[name][0]
        n = len(chars)

        parts = []
        # 提前出现的那一段用一个 \k 空拍占位, 这样扫光仍从第一个字的真实起点开始
        if lin > 0.01:
            parts.append(rf"{{\k{cs(lin)}}}")
        for i, c in enumerate(chars):
            nxt = chars[i + 1]["start"] if i + 1 < n else c["end"]
            dur = cs(max(nxt - c["start"], 0.04))     # gapless: 到下一个字的起点
            parts.append(rf"{{\1c{color(i, n)}\kf{dur}}}{c['char']}{c['trailing']}")

        fade_in = min(FADE, int(lin * 1000)) if lin > 0 else 0
        fade_out = min(FADE, int(lout * 1000)) if lout > 0 else 0
        text = rf"{{\fad({fade_in},{fade_out})}}" + "".join(parts)
        ev.append(f"Dialogue: 0,{ts(t0 - lin)},{ts(t1 + lout)},Sora,,0,0,0,,{text}")
        report.append((line["line"] + 1, t0 - lin, t1 + lout, name, gap_prev, gap_next))
    return ev, report


def main():
    argv = sys.argv[1:]
    if argv:
        plan = []
        for a in argv:
            rng, _, name = a.partition(":")
            lo, _, hi = rng.partition("-")
            plan.append((int(lo), int(hi) if hi else None, name))
    else:
        plan = DEFAULT_PLAN
    for _, _, nm in plan:
        if nm not in SCHEMES:
            raise SystemExit(f"ERROR: 未知配色 {nm}\n可用: {', '.join(SCHEMES)}")

    lines = json.loads((LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    SUBS.mkdir(parents=True, exist_ok=True)

    print("配色方案:")
    for lo, hi, nm in plan:
        rng = f"L{lo+1}-L{hi+1}" if hi is not None else f"L{lo+1}-末尾"
        print(f"  {rng:12s} {nm:9s} {SCHEMES[nm][1]}")
    print()

    ev, report = build(lines, plan)
    tag = "_".join(nm for _, _, nm in plan)
    out = SUBS / f"soramimi_{tag}.ass"
    out.write_text(header(tag) + "\n".join(ev) + "\n", encoding="utf-8-sig")

    print(f"{'行':>3} {'显示区间':>16} {'配色':>8}   {'前隔':>7} {'后隔':>7}")
    print("-" * 56)
    prev_end = -1.0
    overlap = 0
    for ln, a, b, nm, gp, gn in report:
        mark = ""
        if a < prev_end - 1e-6:
            mark = "  <== 重叠!"
            overlap += 1
        prev_end = b
        gps = f"{gp:.2f}s" if gp < 90 else "—"
        gns = f"{gn:.2f}s" if gn < 90 else "—"
        print(f"L{ln:>2} {a:>7.2f}-{b:<7.2f} {nm:>8}   {gps:>7} {gns:>7}{mark}")
    print("-" * 56)
    print(f"重叠行对: {overlap}   (应为 0)")
    print(f"\n写出 -> {out.name}  ({len(ev)} 行)")
    print(f"压制: python burn.py {tag}")
    return 1 if overlap else 0


if __name__ == "__main__":
    sys.exit(main())
