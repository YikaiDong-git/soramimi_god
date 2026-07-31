#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""节奏与分词可读性 —— 全部建立在原有的"左右刷光"上, 逐级叠加。

问题 (作者提出, 两类):
  A. 时长 —— 单字时长 0.02s ~ 1.16s, 极差 58 倍, 匀速扫光把这个差异抹平了。
  B. 分词 —— 汉字连写无空格, 空耳造出的准词 (孤舵 / 此夜 / 果啊) 让自动切词失效。
     行内相邻字 92% 时间缝隙 <= 1ms, 所以分词边界**不在时间轴里**, 只能来自语义。

作者最终选定的路线:
  - 保留 \\kf 左右刷光 (否决"一个字一个字显");
  - 未唱压暗、扫过点亮;
  - 只标少数几个重点词, 不做全曲分词;
  - 重点词用**颜色**区分, 颜色按词的"温度/感觉"选。

四个方案 (逐级叠加, 每次只多一件事):
  10  刷光 + 明暗          排版一个字不动
  11  10 + 重点词留白      标注过的词两侧留白
  12  11 + 重点词着色      整词同色, 未唱时也带着这个色(暗) —— 推荐
  13  12 + 词下划线        再加一条线 (备选; 烟花段可能抢注意力)

为什么着色比下划线可靠 (踩过的坑):
  下划线要知道每个字的 x 坐标 -> 要量字体度量 -> 而 **PyonFX 量宽度时会忽略内联
  的 \\fscx**, 按 \\h 原生 68.6px 算, libass 实际渲染 30px, 于是线整体左移且逐组
  右漂 (原生抽帧实测: 第1组左偏~150px, 第5组右偏~90px)。本文件已用已知的留白
  宽度做了回补 (fix_x), 但**着色方案根本不需要 x 坐标**, 从原理上免疫这类问题。

用法:
    python rhythm_variants.py              # 全部方案 x 全部样本行
    python rhythm_variants.py 12
    python rhythm_variants.py --line=5
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

# 不碰 sys.stdout —— 本文件可能被 import (见 ENGINEERING.md §6.14)。

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"
SUBS = ROOT / "03_subs"
VDIR = SUBS / "rhythm"
OUT = ROOT / "04_output" / "rhythm"
QC = ROOT / "05_qc" / "rhythm"
FF = "C:/Users/59827/karaoke/tools/ffmpeg-shared71/bin/ffmpeg.exe"

SAMPLE_LINES = [2, 5]
PAD = 1.0
LONG_SEC = 0.45

# 未唱色 = 半透明白。\kf 从 SecondaryColour 扫成 PrimaryColour, 所以把 Secondary
# 压暗即得"未唱暗 / 唱到亮"。ASS 颜色是 &HAABBGGRR&, AA=00 全不透明; 0x96 约 59% 透明。
C_UNSUNG = r"&H96FFFFFF&"
C_OUTLINE = r"&H00301808&"

FS = 78
# 实测值 (PyonFX 量 Microsoft YaHei @78): 汉字 61.1px, 而一个 \h 有 68.6px —— 比字还宽。
GLYPH_W = 61.1
SPACE_ADV = 68.6

GAP_WORD = 30              # 重点词两侧留白 px
GAP_LONG = 26              # 被拖长的字后面再多留 px

# 温度色板 —— 作者按词的"感觉"挑。ASS 是 &HAABBGGRR&, 所以 RGB 要倒着写。
TEMP = {
    "冷": ("&H00FFC878&", "冰蓝"),
    "暖": ("&H005ABEFF&", "琥珀"),
    "热": ("&H005A6EFF&", "橙红"),
    "静": ("&H00DCE696&", "青灰"),
    "金": ("&H0000D7FF&", "鎏金"),
    "紫": ("&H00FF96C8&", "幽紫"),
    "绿": ("&H0096E696&", "草绿"),
}

# 作者尚未标注时用的草案 (与模板里预填的一致)
WORDS_DRAFT = {2: [("孤舵", "冷")], 5: [("都", "暖")]}

HEADER_TMPL = """[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sora,Microsoft YaHei,{fs},&H00F0C000&,{unsung},{outline},&H80000000&,-1,0,0,0,100,100,2,0,1,4,2,2,60,60,96,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(sec: float) -> str:
    cs = max(int(round(sec * 100)), 0)
    s, cs = divmod(cs, 100)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def ice(i: int, n: int) -> str:
    """寒冰配色 (与 make_ass.py 的 ice 一致): 白 -> 青 -> 蓝。"""
    t = i / max(n - 1, 1)
    if t < 0.5:
        u = t / 0.5
        r, g, b = int(255 - 55 * u), 255, 255
    else:
        u = (t - 0.5) / 0.5
        r, g, b = int(200 - 80 * u), int(255 - 40 * u), 255
    return rf"&H00{b:02X}{g:02X}{r:02X}&"


def dialog(t0, t1, text, layer=0):
    return f"Dialogue: {layer},{ts(t0)},{ts(t1)},Sora,,0,0,0,,{text}"


def total_cs(ch, i) -> int:
    """gapless \\kf 值 (厘秒): 下一字起点 - 本字起点; 最后一字用自己的 end。"""
    nxt = ch[i + 1]["start"] if i + 1 < len(ch) else ch[i]["end"]
    return max(int(round((nxt - ch[i]["start"]) * 100)), 1)


def disp(ch):
    """行的显示串 (含标点), 以及每个字在串里的起始下标。"""
    s, slots, acc = "", [], 0
    for c in ch:
        slots.append(acc)
        t = c["char"] + c["trailing"]
        s += t
        acc += len(t)
    return s, slots


# ---------------------------------------------------------------- 重点词

def load_words(li: int, ch):
    """读作者标注的重点词, 返回 [(首字下标, 末字下标, 颜色 or None), ...]。

    标注文件格式:  L03  孤舵=冷  此夜
    没标就用 WORDS_DRAFT。词按显示串做子串定位, 找不到会报错而不是静默跳过。
    """
    f = LYR / "soramimi_groups.txt"
    spec = None
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln.startswith("#"):
                continue
            m = re.match(rf"^L{li+1:02d}\s+(.+)$", ln)
            if m:
                spec = []
                for tok in m.group(1).split():
                    w, _, t = tok.partition("=")
                    spec.append((w, t or None))
                break
    if spec is None:
        spec = WORDS_DRAFT.get(li, [])

    text, slots = disp(ch)
    slot_to_char = {s: i for i, s in enumerate(slots)}
    out = []
    for w, t in spec:
        p = text.find(w)
        if p < 0:
            raise SystemExit(f"ERROR: L{li+1} 找不到词 '{w}'  (整行: {text})")
        if p not in slot_to_char:
            raise SystemExit(f"ERROR: L{li+1} 词 '{w}' 从标点中间起头, 请调整")
        i0 = slot_to_char[p]
        i1 = max(k for k in slot_to_char.values() if slots[k] < p + len(w))
        if t is not None and t not in TEMP:
            raise SystemExit(f"ERROR: 未知温度 '{t}', 可选: {' '.join(TEMP)}")
        out.append((i0, i1, TEMP[t][0] if t else None))
    return out


def gaps_after(ch, words, use_gap: bool):
    """每个字后面留多少 px 白。重点词两侧留白, 拖长的字后面再多留一点。"""
    out = [0] * len(ch)
    if not use_gap:
        return out
    for i, c in enumerate(ch):
        if (c["end"] - c["start"]) > LONG_SEC and i + 1 < len(ch):
            out[i] += GAP_LONG
    for i0, i1, _ in words:
        if i0 > 0:
            out[i0 - 1] += GAP_WORD          # 词前
        if i1 + 1 < len(ch):
            out[i1] += GAP_WORD              # 词后
    return out


def colors_for(ch, words, use_color: bool):
    """返回每个字的 (已唱色, 未唱色)。重点词整词同色, 且未唱时也带着这个色。"""
    n = len(ch)
    pri = [ice(i, n) for i in range(n)]
    sec = [None] * n
    if use_color:
        for i0, i1, col in words:
            if col is None:
                continue
            for i in range(i0, i1 + 1):
                pri[i] = col
                sec[i] = col                 # \2c: 未唱时就带温度, 只是被 style 的 alpha 压暗
    return pri, sec


# ---------------------------------------------------------------- 构建

def build_line(line, gaps, pri, sec, underline=()):
    """单条 Dialogue: 逐字 \\kf 刷光 + 逐字配色, 按 gaps 插入定宽留白。

    留白用 `{\\fscxNN}\\h` —— \\h 原生 68.6px 太宽, 用 \\fscx 压到指定像素。
    每个字都显式写 \\fscx100: \\fscx 是**持续生效**的, 漏掉的话第一个留白之后
    所有字会一直被横向压扁 (只有抽帧才看得出来)。

    下划线用 ASS 内建的 \\u1 / \\u0, **不自己算坐标**。
    踩过的坑 (两条路都试过, 都不可靠):
      (a) PyonFX 量 —— 它忽略内联 \\fscx, 把留白按 \\h 原生 68.6px 计, 而 libass
          实际渲染 30px, 于是线整体左移并逐组右漂;
      (b) 自己按 "字宽 61.1 + Spacing 2" 解析建模 —— 逐字画框标定后发现模型整行
          比实际宽约 80px, 依然对不上。
    两条路的共同问题是**在猜渲染器的行为**。\\u1 由渲染器自己排, 跟着字走, 不可能错。
    """
    ch = line["chars"]
    ul = set()
    for i0, i1 in underline:
        ul.update(range(i0, i1 + 1))
    parts = []
    for i, c in enumerate(ch):
        T, g = total_cs(ch, i), gaps[i]
        tag = rf"\1c{pri[i]}" + (rf"\2c{sec[i]}" if sec[i] else r"\2c&HFFFFFF&") + r"\fscx100"
        tag += r"\u1" if i in ul else r"\u0"
        txt = c["char"] + c["trailing"]
        if g > 0:
            w_c = GLYPH_W * len(txt)
            t_c = max(int(round(T * w_c / (w_c + g))), 1)
            parts.append(rf"{{{tag}\kf{t_c}}}{txt}")
            # 留白本身不带下划线, 否则线会跨到词外面去
            parts.append(rf"{{\u0\fscx{max(int(round(100*g/SPACE_ADV)),1)}\kf{max(T-t_c,1)}}}\h")
        else:
            parts.append(rf"{{{tag}\kf{T}}}{txt}")
    return "".join(parts)


VARIANTS = {
    "10": ("dim", "刷光 + 明暗", dict(gap=False, color=False, ul=False)),
    "11": ("gap", "+ 重点词留白", dict(gap=True, color=False, ul=False)),
    "12": ("color", "+ 重点词着色", dict(gap=True, color=True, ul=False)),
    "13": ("ul", "+ 词下划线", dict(gap=True, color=True, ul=True)),
}


def main():
    args = sys.argv[1:]
    pick = [a for a in args if a in VARIANTS] or sorted(VARIANTS)
    la = [int(a.split("=")[1]) for a in args if a.startswith("--line=")]
    todo = la or SAMPLE_LINES
    for d in (VDIR, OUT, QC):
        d.mkdir(parents=True, exist_ok=True)

    data = json.loads((LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    mv = next(p for p in (ROOT / "00_source").glob("*.mp4") if not p.name.endswith(".part"))
    header = HEADER_TMPL.format(fs=FS, unsung=C_UNSUNG, outline=C_OUTLINE)

    for li in todo:
        line = data[li]
        ch = line["chars"]
        w0, w1 = line["start"] - PAD, line["end"] + PAD
        words = load_words(li, ch)
        txt_ = "".join(c["char"] + c["trailing"] for c in ch)
        shown = "  ".join(txt_[0:0].join([]) or
                          "".join(ch[k]["char"] + ch[k]["trailing"] for k in range(a, b + 1))
                          + (f"({[n for n, v in TEMP.items() if v[0] == col][0]})" if col else "")
                          for a, b, col in words) or "无"
        print(f"\n===== L{li+1}  {line['text']}")
        print(f"      重点词: {shown}")

        for key in pick:
            name, desc, opt = VARIANTS[key]
            gp = gaps_after(ch, words, opt["gap"])
            pri, sec = colors_for(ch, words, opt["color"])
            ulw = [(a, b) for a, b, _ in words] if opt["ul"] else ()
            text = build_line(line, gp, pri, sec, ulw)
            t0, t1 = line["start"] - 0.35, line["end"] + 0.35

            tag = f"{key}_{name}_L{li+1}"
            ass = VDIR / f"{tag}.ass"
            ass.write_text(header + dialog(t0, t1, text) + "\n", encoding="utf-8-sig")

            body = []
            for ln in ass.read_text(encoding="utf-8-sig").splitlines():
                if ln.startswith("Dialogue:"):
                    head, a, b, rest = ln.split(",", 3)
                    def sh(st):
                        h, mi, s = st.split(":")
                        return ts(int(h) * 3600 + int(mi) * 60 + float(s) - w0)
                    ln = f"{head},{sh(a)},{sh(b)},{rest}"
                body.append(ln)
            ass.write_text("\n".join(body) + "\n", encoding="utf-8-sig")

            out = OUT / f"{tag}.mp4"
            r = subprocess.run(
                [FF, "-y", "-loglevel", "error", "-ss", str(w0), "-t", str(w1 - w0),
                 "-i", str(mv), "-vf", f"ass={ass.name}",
                 "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23",
                 "-b:v", "0", "-pix_fmt", "yuv420p", "-an", str(out)],
                cwd=str(VDIR), capture_output=True, text=True,
                encoding="utf-8", errors="replace")
            if r.returncode != 0 or not out.exists():
                print(f"      FAIL {tag}: {r.stderr.strip()[:200]}")
                continue

            # QC 一律用**原生分辨率**只裁字幕带 —— 缩放过的图判断不了像素级对齐
            for frac in (0.45, 0.85):
                t = (line["start"] + (line["end"] - line["start"]) * frac) - w0
                j = QC / f"{tag}_{int(frac*100)}.jpg"
                subprocess.run([FF, "-y", "-loglevel", "error", "-ss", f"{t:.2f}",
                                "-i", str(out), "-frames:v", "1", "-q:v", "2",
                                "-vf", "crop=1920:170:0:880", str(j)], check=False)
            print(f"      {key} {desc:16s} {out.stat().st_size/1e6:5.1f} MB")

    print(f"\n样片: {OUT}\n抽帧(原生分辨率字幕带): {QC}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
