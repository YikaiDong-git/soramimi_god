#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""check_ruby_align.py — 数值核对注音层与主行是否逐格对齐。

为什么不靠看图:
    肉眼看竖线"偏窄"其实是错觉 —— 竖线落在每格**中心**, 而字的墨迹几乎铺满整格
    还带 4px 描边, 所以竖线跨度天然比文字跨度窄一个字宽。本项目已经因为凭截图
    判断位置返工过三次 (ENGINEERING.md §6.25), 所以位置一律用数字判。

做法:
    从 ZZ 诊断帧里按 y 带切出竖线层, 逐根求墨迹质心 -> 实测格心;
    再按主行的排版公式算出理论格心; 两者相减。
    偏差 > 2px 就是排版公式错了。

用法: python check_ruby_align.py [ZZ_L15.jpg ...]
"""
import json
import sys
from pathlib import Path

# 不要在这里再包一层 sys.stdout —— layout_variants 导入时已经包过, 两层包装里
# 先被回收的那个会把底层 buffer 关掉, 后面所有 print 报 "closed file"。
import numpy as np
from PIL import Image

ARGV = sys.argv[1:]
sys.argv = [sys.argv[0]]
import layout_variants as LV                              # noqa: E402
import make_ass as M                                      # noqa: E402

QC = LV.ROOT / "05_qc" / "layout_options"


def tick_centers(img, y0, y1, thresh=110):
    """在 [y0,y1) 这条带里找竖线, 返回每根线的墨迹质心 x。"""
    a = np.asarray(Image.open(img).convert("L"), dtype=np.float32)[y0:y1]
    col = a.max(axis=0)
    on = col > thresh
    runs, i = [], 0
    while i < len(on):
        if on[i]:
            j = i
            while j + 1 < len(on) and on[j + 1]:
                j += 1
            w = col[i:j + 1]
            runs.append(float((np.arange(i, j + 1) * w).sum() / w.sum()))
            i = j + 1
        else:
            i += 1
    return runs


def predicted_centers(line):
    """按主行排版公式算每格中心 x。主行居中于 [MarginL, 1920-MarginR]。

    只返回**字格**的中心 —— 注音层每个字一根竖线, 标点格里是空的。
    """
    chars = line["chars"]
    gaps, _, _ = M.layout(chars,
                          M.load_breaks(line["line"], chars),
                          M.load_colors(line["line"], chars))
    cells = []                                            # (前进宽度, 是否字格)
    for i, c in enumerate(chars):
        cells.append((LV.GLYPH, True))
        for _ in c["trailing"].strip():
            cells.append((LV.GLYPH, False))
        if gaps[i] > 0:
            nn = max(int(round(100 * gaps[i] / M.SPACE_ADV)), 1)
            cells.append((LV.H_ADV * nn / 100, False))
    total = sum(w for w, _ in cells) + LV.FSP * (len(cells) - 1)
    x = (1920 - 60 - 60) / 2 + 60 - total / 2
    out = []
    for w, is_char in cells:
        if is_char:
            out.append(x + w / 2)
        x += w + LV.FSP
    return out, total


def invariant_check(lines):
    """解析式核对: **每个注音组的中心必须等于它那个字的格心**。

    为什么要有这条 (它是被一次真实回归逼出来的):
        渲染式核对靠 ZZ 诊断帧, 而那张帧每格只发一根等宽的 `|` —— "多拍格子太宽"
        这条路径根本不会被触发。于是曾经给宽格子加了"向邻居借宽度", 真实注音整行
        偏掉, 而诊断仍然报 0.87px 通过。**夹具不同形的测试, 只能证明它自己没错。**
        这条检查直接读排版用的那几个量, 与内容宽窄无关, 那次回归会被它一眼抓住。
    """
    bad = 0
    for line in lines:
        chars = line["chars"]
        gaps, _, _ = M.layout(chars, M.load_breaks(line["line"], chars),
                              M.load_colors(line["line"], chars))
        x_main = x_ruby = 0.0
        for i, c in enumerate(chars):
            n_p = len(c["trailing"].strip())
            # 字格和标点格是**分开**的两格, 两层都如此。把它们并成一格算
            # (PITCH*(1+标点数)) 会让带标点的字虚报 31.55px 偏移 —— 我这条检查
            # 第一版就是这么写的, 报了 6 处假警。检查本身也要按真实排版建模。
            cm = x_main + LV.GLYPH / 2                 # 正文里这个字的中心
            cr = x_ruby + LV.PITCH / 2                 # 注音这一组的中心
            if abs(cm - cr) > 1.5:
                print(f"  L{line['line']+1} 第{i+1}字 '{c['char']}' "
                      f"注音中心偏离 {cr-cm:+.2f}px")
                bad += 1
            x_main += LV.PITCH * (1 + n_p)
            x_ruby += LV.PITCH * (1 + n_p)
            if gaps[i] > 0:
                nn = max(int(round(100 * gaps[i] / M.SPACE_ADV)), 1)
                g = LV.H_ADV * nn / 100 + LV.FSP
                x_main += g
                x_ruby += g
    print(f"  逐格居中不变量: {'OK' if not bad else f'**{bad} 处偏离**'}"
          f"   (共 {sum(len(l['chars']) for l in lines)} 字)")
    return bad


def main():
    shots = ARGV or ["ZZ_L15.jpg", "ZZ_L03.jpg"]
    lines = json.loads((LV.LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    bad = invariant_check(lines)
    print()
    idx = {"L15": 14, "L03": 2}
    bad = 0
    for s in shots:
        p = QC / s
        if not p.exists():
            print(f"  缺 {s}")
            continue
        line = lines[idx[Path(s).stem.split("_")[1]]]
        pred, total = predicted_centers(line)
        # 竖线带: MarginV = 96+84 = 180 -> 距底 180..180+34
        got = tick_centers(p, 1080 - 180 - 40, 1080 - 180 + 4)
        print(f"\n=== {s} ===  理论行宽 {total:.1f}px  "
              f"格数 理论 {len(pred)} / 实测竖线 {len(got)}")
        if len(got) != len(pred):
            print("  !! 竖线根数对不上, 无法逐格比对")
            bad += 1
            continue
        d = [g - p_ for g, p_ in zip(got, pred)]
        print("  格号  理论x    实测x    偏差")
        for i, (p_, g, dd) in enumerate(zip(pred, got, d)):
            flag = "  <<<" if abs(dd) > 2 else ""
            print(f"  {i:>3}  {p_:7.1f}  {g:7.1f}  {dd:+6.2f}{flag}")
        mx = max(abs(v) for v in d)
        print(f"  最大偏差 {mx:.2f}px  平均 {sum(d)/len(d):+.2f}px  "
              f"{'OK' if mx <= 2 else '**超标**'}")
        bad += mx > 2
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
