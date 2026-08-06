#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_ref_lines.py — 校验参考行文本 (日文原句 / 中文翻译) 和时间轴对不对得上。

为什么需要它:
    贴官方歌词进来最容易出错的不是字打错, 而是**断行**。官方歌词本的分行是按
    印刷排版来的, 和我们这 15 行空耳的断句没有任何理由一致 —— 本片的 ASR 分段
    就只有 14 段, 且其中一段横跨 0.54-70.45 秒。断行错一行, 后面所有行全错位,
    而画面上看起来"每行都有字", 不抽帧根本发现不了。

    所以这里做一件事: 把你写的每一行日文换算成**拍数(mora)**, 和对齐器在那一段
    音频里实际数到的音节数比。差得多 = 这一行的断句不对, 或者少贴/多贴了一行。

    中译只查行数和明显空行 —— 译文长度本来就该自由。

用法: python check_ref_lines.py
      非零退出 = 有硬问题, 别急着压片。
"""
import io
import json
import sys
from pathlib import Path

sys.argv = [sys.argv[0]]                      # make_ass 会读 argv, import 前清空
import make_ass as M                          # noqa: E402

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"

# 小书写假名附着在前一拍上, 不单独计一拍; ー / っ / ん 各算一拍。
SMALL = set("ぁぃぅぇぉゃゅょゎァィゥェォャュョヮ")
SKIP = set(" 　、。，,.!?！？「」『』・…ー～~-—()（）")


def morae(text):
    """把一行日文换算成拍数。汉字先转假名再数。"""
    import pykakasi
    kana = "".join(x["kana"] for x in pykakasi.kakasi().convert(text))
    n = 0
    for ch in kana:
        if ch in SKIP and ch != "ー":
            continue
        if ch in SMALL:
            continue                       # 拗音: 与前一拍合成一拍
        if ch.strip():
            n += 1
    return n


def main():
    lines = json.loads((LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    n_lines = len(lines)
    # 对齐器在每一行那段音频里实际数到的音节数
    want = [L.get("n_ja_syls") or len(L.get("ja_syls") or L["chars"]) for L in lines]

    hard = 0
    for kind, label in (("ja", "日文原句"), ("zh", "中文翻译")):
        p = LYR / f"ref_{kind}.txt"
        print(f"\n=== {label}  {p.name} ===")
        if not p.exists():
            print(f"  未提供 —— 当前走占位文本, 成片右上角会有 PLACEHOLDER 角标")
            continue
        # 用 make_ass 的读取函数, 不自己再写一遍过滤规则 —— 校验器和渲染器
        # 对"哪些行算正文"的理解必须完全一致, 否则校验的是另一个文件
        rows = M.read_ref(kind)
        print(f"  行数 {len(rows)}  (需要 {n_lines})")
        if len(rows) != n_lines:
            print(f"  ** 行数对不上 —— 空耳有 {n_lines} 行, 一一对应才能贴上去")
            hard += 1
            continue
        if kind == "zh":
            print("  OK (译文长度不做限制)")
            continue

        print(f"  {'行':>3}  {'你的拍数':>8} {'音频音节':>8} {'差':>5}   判断")
        bad = 0
        for i, (r, w) in enumerate(zip(rows, want)):
            m = morae(r)
            d = m - w
            # 阈值: 差 2 拍以内属正常 (转写/长音写法差异), 超过 3 拍且超过 30% 判为断行可疑
            flag = "" if abs(d) <= 2 or abs(d) <= 0.3 * w else "  <== 断句可疑"
            if flag:
                bad += 1
            print(f"  L{i+1:<2}  {m:>8} {w:>8} {d:>+5}   {flag}")
        if bad:
            print(f"  ** {bad} 行拍数与音频差得多 —— 多半是断行没对上, "
                  f"不是字打错。核对这几行的起止位置")
            hard += 1
        else:
            print(f"  OK: {n_lines} 行拍数都和音频吻合")

    print()
    if hard:
        print(f"有 {hard} 处硬问题, 先修再压片。")
    else:
        print("参考行校验通过。可以跑:")
        print("  python make_ass.py --layout=E3")
        print("  python burn.py ice_rainbow --layout=E3 --trim=2.85 --preview=90")
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
