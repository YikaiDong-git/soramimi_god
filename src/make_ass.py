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
import re
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

# \kf 是从 SecondaryColour 扫成 PrimaryColour, 连透明度一起插值, 所以把 Secondary
# 设成半透明就得到"未唱暗、扫过点亮", 和滚动扫光共存, 不需要逐字定位。
#
# ⚠ 这两个常量**必须分开**, 曾经共用同一个而踩过坑:
#   \1c 只改颜色**不改透明度** —— 已唱部分的透明度来自 Style 的 PrimaryColour。
#   把 Primary 也设成半透明的话, 整条字幕(连唱过的部分)都会发灰,
#   而样片的 header 里 Primary 是硬写的不透明色, 所以样片正常、成片发灰, 更难发现。
C_SUNG = r"&H00FFFFFF&"        # 已唱: 不透明 (真正的颜色由每个字的 \1c 覆盖)
C_UNSUNG = r"&H96FFFFFF&"      # 未唱: 半透明白 (AA=0x96 约 59% 透明)
C_OUTLINE = r"&H00301808&"

LEAD_IN = 350                  # ms 期望的提前出现量 (会被邻行间隔压缩)
LEAD_OUT = 350                 # ms 期望的延后消失量
GAP_SHARE = 0.40               # 每行最多吃掉间隔的 40%, 两行合计 80%, 留 20% 空隙
FADE = 110                     # ms 淡入淡出

# ---------------------------------------------------------------- 标注
# 汉字连写没有空格, 空耳造出来的准词读者切不开。分组边界**不在时间轴里**
# (实测行内相邻字 92% 缝隙 <= 1ms), 只能来自语义, 由作者标在
# 02_lyrics/soramimi_groups.txt 里。两种标注**互相独立**:
#
#   B03  吾待|孤舵|罢      断点: 只在写了 | 的地方留白 (写片段即可, 按片段定位)
#   C03  孤舵=冷           着色: 整词同色, 未唱时也带着这个色(只是暗)
#
# 曾经的做法是"标一个词 -> 两侧自动加空格 + 上色", 三件事绑死, 结果:
#   (a) 为了保护"我的"不被自动规则劈开而标成词, 反而制造了"的|心"这个多余空格;
#   (b) L9 只想要"瘩|当", 却得到"的|疙瘩|当年"两个空格。
# 根子是把"分组"和"留白"绑死了。作者真正要表达的是**在哪里断开**(意群边界),
# 不是"哪几个字算一个词" —— "已枯落的疙瘩"整体才是一个意群。
# 另外原先还有一条"被拖长的字后面自动留白"的规则, 它不认识词, 全曲 18 处触发、
# 劈开 4 个真词, **已整条删除** —— 空格只出现在作者明确标的位置。

# ---------------------------------------------------------------- 扫光节奏
# 日文音节时长极不均 (实测单字 0.02s ~ 1.16s, 中位 0.32s), 1:1 映射把这份不均
# 原样继承 -> 有的字只有 \kf2 (2 厘秒), 等于瞬间弹出, 根本不是"刷"。
# 修法: 给每个字的扫光时长设下限, 缺的时间从"超出下限的部分"按比例借, 整行总长不变。
# **只抬下限, 不压上限** —— 长音的"拖住"是真实的节奏信号, 压掉就把节奏抹平了。
# 0.14s 试过, **太低** —— 24fps 下只有 3.4 帧, 作者仍反映"瞬过"。
# 实测各档代价 (被抬起字数 / 借走总量 / 最大单字压缩):
#   0.14 -> 10 字 / 0.62s / 10%      0.22 -> 21 字 / 1.86s / 32%
#   0.20 -> 17 字 / 1.44s / 24%      0.25 -> 35 字 / 2.77s / 47%  (削掉近半, 会失同步)
# 取 0.22 (≈5.3 帧)。长音几乎不受影响: 最长的 1.16s 只掉到 1.07s。
MIN_WIPE = 0.22                # 单字最短扫光时长 (秒)

# ---------------------------------------------------------------- 扫光速度限幅
# 每个字宽度一样但时长不同 -> 扫光**速度**不同。眼睛跟着光的前沿走, 前沿每过一个字
# 就变一次速, 这就是"唐突/突然感"的物理来源。实测相邻字速度最大跳变 4.1 倍。
#
# 试过两条路 (同样把跳变压到 1.5x 时的"字被点亮 vs 该被唱到"的最大偏移):
#   全局混合 (把每个字的时长往"按宽度匀速"拽)  -> 偏移 0.62s   ✗
#   速度限幅 (只动跳变过大的相邻对)            -> 偏移 0.20s   ✓  差 3 倍
# 限幅只削突变、不改整体形状 (动画与控制系统里的 slew rate limiting), 所以代价小得多。
# 完全匀速 (跳变 1.0x) 的偏移达 0.88s —— 光和人声脱节近一秒, 不可取。
#
# 取 1.7: 跳变 4.1x -> 1.7x, 偏移仅 0.17s。0 或 None 关闭。
WIPE_LIMIT = 1.7
GAP_MAX_SEC = 0.05             # 留白最多占走多少扫光时间 —— 光走在空白里是"看不见"的,
                               # 不封顶的话短字会被留白偷走大半时间, 显得更快
GAP_BREAK = 34                 # 一个断点留多少 px 白
SPACE_ADV = 68.6               # 实测: 一个 \h 有 68.6px, 比汉字(61.1px)还宽
GLYPH_W = 61.1                 # 实测: Microsoft YaHei @78 的全角字宽

TEMP = {                       # 温度色板, 作者按词的"感觉"挑。ASS 是 &HAABBGGRR&
    "冷": "&H00FFC878&", "暖": "&H005ABEFF&", "热": "&H005A6EFF&",
    "静": "&H00DCE696&", "金": "&H0000D7FF&", "紫": "&H00FF96C8&",
    "绿": "&H0096E696&",
}

# 词下划线 —— 标注 `U15  果啊`。位置在**文字下方**, 与声乐谱的惯例一致
# (连接歌词音节的记号画在文字基线下; 上方那条是给音符用的连音线)。
#
# 实现必须用 ASS 内建的 \u1/\u0, 绝不自己算 x 坐标:
#   试过 PyonFX 量 (它忽略内联 \fscx -> 线整体左移并逐组右漂) 和自己解析建模
#   (整行比实际宽约 80px), 两条路都是在猜渲染器的行为, 都对不齐。
#   \u1 由渲染器自己排, 跟着字走, 不可能错。见 ENGINEERING.md §6.16。
#
# 但 \u1 的线色**跟随填充色**, 没法单独指定成深色。所以单独画一层:
# 同一行再排一遍, 只有目标词可见(深色 + \u1), 其余字全透明, 放在正文层**下面** ——
# 线露在字的下方, 而深色字身被上层同位置的正文完全盖住。
# 颜色注意两点 (都踩过):
#   (1) \1c 只吃 6 位十六进制 &HBBGGRR&, 写成 8 位 (带 alpha) 解析不对, 透明度要用 \1a;
#   (2) 纯深色的线在暗背景的镜头上等于隐形 —— 乐谱是黑墨白纸, 视频不是。
#       所以照正文的思路反过来做: 深色线 + 一圈浅色细描边, 明暗背景都看得见。
C_ULINE = r"&H303030&"         # 线本身: 偏黑
C_ULINE_EDGE = r"&HF0F0F0&"    # 细描边: 浅色, 保证在暗背景上也分得出来
ULINE_DROP = 11                # 下划线层比正文低多少 px (靠 Dialogue 的 MarginV 实现)
ULINE_H = 5                    # 线粗 px
SPACING = 2                    # 与 Style 里的 Spacing 一致 —— 算线长要用


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
Style: Sora,{FONT},{FONT_SIZE},{C_SUNG},{C_UNSUNG},{C_OUTLINE},&H80000000&,-1,0,0,0,100,100,2,0,1,{OUTLINE},{SHADOW},2,60,60,{MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def scheme_for(idx, plan):
    for lo, hi, name in plan:
        if idx >= lo and (hi is None or idx <= hi):
            return name
    return plan[-1][2]


def _display(chars):
    """行的显示串 (含标点) + 每个字在串里的起始下标 + 反查表。"""
    # trailing 里的字面空格在渲染时会被去掉, 这里也必须去 —— 否则标注按"含空格"的
    # 串定位, 而屏幕上是"不含空格"的串, 片段会找不到 (例: 想写 `B05 开|似`)。
    text, slots, acc = "", [], 0
    for c in chars:
        slots.append(acc)
        t = c["char"] + c["trailing"].strip()
        text += t
        acc += len(t)
    return text, slots


def _read_spec(li, prefix):
    """收集 02_lyrics/soramimi_groups.txt 里所有 `<prefix><nn>` 开头的标注。

    同一行可以分散写成多条 (审美标注 / 补丁各写各的), 必须**全部合并** ——
    只取第一条会把后面的静默丢掉 (踩过)。
    """
    f = LYR / "soramimi_groups.txt"
    if not f.exists():
        return []
    out = []
    for ln in f.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if ln.startswith("#"):
            continue
        m = re.match(rf"^{prefix}{li+1:02d}\s+(.+)$", ln)
        if m:
            out += m.group(1).split()
    return out


def load_breaks(li, chars):
    """读断点标注 `B03  吾待|孤舵|罢`, 返回"在第几个字之后留白"的下标集合。

    只认作者写的 | —— 没有任何自动插空格的规则。
    """
    text, slots = _display(chars)
    slot_owner = {}
    for i, s in enumerate(slots):
        for k in range(1 + len(chars[i]["trailing"].strip())):
            slot_owner[s + k] = i

    out = set()
    for frag in _read_spec(li, "B"):
        if "|" not in frag:
            raise SystemExit(f"ERROR: L{li+1} 的断点标注 '{frag}' 里没有 | ")
        plain = frag.replace("|", "")
        p = text.find(plain)
        if p < 0:
            raise SystemExit(f"ERROR: L{li+1} 断点片段 '{plain}' 在歌词里找不到 (整行: {text})")
        off, cnt = [], 0
        for chch in frag:
            if chch == "|":
                off.append(cnt)
            else:
                cnt += 1
        for o in off:
            if o == 0 or o == len(plain):
                continue                    # 片段头尾的 | 无意义, 忽略
            out.add(slot_owner[p + o - 1])  # 在这个字之后断开
    return out


def load_colors(li, chars):
    """读作者标注的重点词, 返回 [(首字下标, 末字下标, 颜色 or None), ...]。

    标注形如 `C03  孤舵=冷`。**只上色, 不加空格** —— 空格完全由 B 标注决定。
    词按"含标点的显示串"做子串定位; 找不到就报错, 不静默跳过 —— 作者改了用字
    而忘了同步标注时必须立刻发现。
    """
    spec = [tok.partition("=")[::2] for tok in _read_spec(li, "C")]
    if not spec:
        return []
    text, slots = _display(chars)
    s2c = {s: i for i, s in enumerate(slots)}

    out = []
    for w, t in spec:
        p = text.find(w)
        if p < 0:
            raise SystemExit(f"ERROR: L{li+1} 词表里的 '{w}' 在歌词里找不到 (整行: {text})")
        if p not in s2c:
            raise SystemExit(f"ERROR: L{li+1} 的 '{w}' 从标点中间起头, 请调整词表")
        if t and t not in TEMP:
            raise SystemExit(f"ERROR: 未知温度 '{t}', 可选: {' '.join(TEMP)}")
        i0 = s2c[p]
        i1 = max(k for k in s2c.values() if slots[k] < p + len(w))
        out.append((i0, i1, TEMP[t] if t else None))
    return out


def floor_durations(durs, floor):
    """给每个字的扫光时长设下限, 缺的从"超出下限的部分"按比例借, 总时长不变。

    只抬下限、不压上限, 所以长音的"拖住"完整保留。
    迭代是必要的: 借出去之后捐助者自己可能掉到下限以下, 下一轮再从剩下的借。
    """
    d = list(durs)
    total = sum(d)
    n = len(d)
    if n == 0:
        return d
    if total <= floor * n:
        return [total / n] * n           # 整行本来就挤, 只能平均分
    for _ in range(6):
        deficit = sum(max(floor - x, 0.0) for x in d)
        if deficit < 1e-6:
            break
        pool = sum(max(x - floor, 0.0) for x in d)
        d = [floor if x <= floor else x - deficit * (x - floor) / pool for x in d]
    return d


def load_underlines(li, chars):
    """读下划线标注 `U15  果啊`, 返回 [(首字下标, 末字下标), ...]。只加线, 不加空格。"""
    spec = [w for w in _read_spec(li, "U")]
    if not spec:
        return []
    text, slots = _display(chars)
    s2c = {s: i for i, s in enumerate(slots)}
    out = []
    for w in spec:
        p = text.find(w)
        if p < 0:
            raise SystemExit(f"ERROR: L{li+1} 下划线标注的 '{w}' 在歌词里找不到 (整行: {text})")
        if p not in s2c:
            raise SystemExit(f"ERROR: L{li+1} 的 '{w}' 从标点中间起头")
        out.append((s2c[p], max(k for k in s2c.values() if slots[k] < p + len(w))))
    return out


def limit_velocity(durs, widths, ratio):
    """限制相邻字的扫光速度比。**每次只调一对, 且保持这一对的总时长不变**,
    所以整行总长严格不变, 只有内部边界微动。

    对每一对解出满足 v_fast/v_slow == ratio 的分割点:
        v1 = w1/x, v2 = w2/(T-x), T = 本对总时长
        v1 快时:  x = w1*T / (w1 + ratio*w2)
        v2 快时:  x = ratio*w1*T / (w2 + ratio*w1)
    反复扫到收敛 (相邻对互相牵制, 一遍不够)。
    """
    if not ratio or ratio <= 1.0:
        return list(durs)
    x = list(durs)
    for _ in range(60):
        moved = False
        for i in range(len(x) - 1):
            v1, v2 = widths[i] / x[i], widths[i + 1] / x[i + 1]
            if max(v1, v2) / min(v1, v2) <= ratio + 1e-9:
                continue
            T = x[i] + x[i + 1]
            if v1 > v2:
                a = widths[i] * T / (widths[i] + ratio * widths[i + 1])
            else:
                a = ratio * widths[i] * T / (widths[i + 1] + ratio * widths[i])
            x[i], x[i + 1] = a, T - a
            moved = True
        if not moved:
            break
    return x


def layout(chars, breaks, colors):
    """算出每个字后面留多少 px 白, 以及每个字的着色覆盖。

    留白**只来自 breaks** (作者写的 |), 没有任何自动规则 —— 上一版有一条
    "被拖长的字后面自动留白", 它不认识词, 全曲 18 处触发、劈开 4 个真词,
    而且"标一个词就两侧加空格"还会制造作者没要的间隔 (如"的|心")。
    """
    n = len(chars)
    gaps = [GAP_BREAK if (i in breaks and i + 1 < n) else 0 for i in range(n)]
    pri = [None] * n
    for i0, i1, col in colors:
        if col:
            for i in range(i0, i1 + 1):
                pri[i] = col
    ul = {i for i0, i1, _ in colors for i in range(i0, i1 + 1)}
    return gaps, pri, ul


def build(lines, plan):
    ev, report = [], []
    stat_raised, stat_min = 0, 99.0
    stat_jump = stat_jump2 = 1.0
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

        gaps, wcol, wset = layout(chars,
                                  load_breaks(line["line"], chars),
                                  load_colors(line["line"], chars))

        # gapless 原始时长 -> 抬下限 (整行总长不变)
        raw = [max((chars[i + 1]["start"] if i + 1 < n else chars[i]["end"]) - chars[i]["start"], 0.0)
               for i in range(n)]
        durs = floor_durations(raw, MIN_WIPE)
        stat_raised += sum(1 for a, b in zip(raw, durs) if b > a + 1e-6)
        stat_min = min(stat_min, min(raw))

        # 再削掉相邻字之间的速度突变 (整行总长不变)。
        # **必须和下限交替迭代**: 限幅是成对调整的, 会把某个字压回下限以下
        # (实测出现过 0.20s < 下限 0.22s), 只跑一遍两个约束不能同时成立。
        widths = [GLYPH_W * (1 + len(c["trailing"].strip())) for c in chars]
        vel_before = [widths[i] / durs[i] for i in range(n)]
        for _ in range(8):
            prev = durs
            durs = floor_durations(limit_velocity(durs, widths, WIPE_LIMIT), MIN_WIPE)
            if max(abs(a - b) for a, b in zip(prev, durs)) < 1e-4:
                break
        vel_after = [widths[i] / durs[i] for i in range(n)]
        if n > 1:
            stat_jump = max(stat_jump,
                            max(max(a, b) / min(a, b) for a, b in zip(vel_before, vel_before[1:])))
            stat_jump2 = max(stat_jump2,
                             max(max(a, b) / min(a, b) for a, b in zip(vel_after, vel_after[1:])))

        parts = []
        # 提前出现的那一段用一个 \k 空拍占位, 这样扫光仍从第一个字的真实起点开始
        if lin > 0.01:
            parts.append(rf"{{\k{cs(lin)}}}")
        for i, c in enumerate(chars):
            dur = cs(durs[i])
            # 去掉歌词里的字面空格 —— 一个空格就是一整个字宽的间隔, 而本项目的原则是
            # "留白只出现在作者用 B 标注明确指定的位置"。作者写在词句之间的空格是给自己
            # 断句看的, 不该原样变成屏幕上的间隔 (踩过: L5 因此多了一个没人要的间隔)。
            txt = c["char"] + c["trailing"].strip()
            # \fscx / \2c / \u 都是**持续生效**的, 必须每个字显式复位, 否则第一个
            # 留白或第一个重点词之后, 后面所有字会一直沿用 (只有抽帧才看得出来)。
            tag = (rf"\1c{wcol[i] or color(i, n)}"
                   rf"\2c{wcol[i] or '&HFFFFFF&'}"
                   r"\fscx100\u0")
            # 标点**永远单独成段**。ASS 的 \u1 / \1c 作用于整个文本段, 标点跟在字后面
            # 同一段里的话, 装饰会一起罩上去 —— 作者反映"逗号也被划了线"。
            # 拆开之后, 装饰只落在字上, 标点退回本行的基础配色、不带线。
            # 拆分不影响观感: 时间按宽度分配, 扫光速度不变。
            punct = c["trailing"].strip()
            g = gaps[i]
            w_m = GLYPH_W
            w_p = GLYPH_W * len(punct)

            d_g = 0
            if g > 0:
                # 留白用 {\fscxNN}\h —— \h 原生 68.6px 太宽, 缩到指定像素。
                # 时间按宽度分, 但**给留白封顶**: 光走在空白里是看不见的, 不封顶的话
                # 短字大半时间都花在空白上, 字本身反而刷得更快。
                d_g = min(dur * g / (w_m + w_p + g), cs(GAP_MAX_SEC))
                d_g = max(min(int(round(d_g)), dur - cs(MIN_WIPE) // 2), 1)
            rest = dur - d_g
            d_p = max(int(round(rest * w_p / (w_m + w_p))), 1) if punct else 0
            d_m = max(rest - d_p, 1)

            parts.append(rf"{{{tag}\kf{d_m}}}{c['char']}")
            if punct:
                parts.append(rf"{{\1c{color(i, n)}\2c&HFFFFFF&\fscx100\u0\kf{d_p}}}{punct}")
            if d_g:
                parts.append(rf"{{\u0\fscx{max(int(round(100*g/SPACE_ADV)),1)}\kf{d_g}}}\h")

        fade_in = min(FADE, int(lin * 1000)) if lin > 0 else 0
        fade_out = min(FADE, int(lout * 1000)) if lout > 0 else 0
        text = rf"{{\fad({fade_in},{fade_out})}}" + "".join(parts)

        # 下划线层 (layer 0, 压在正文下面)。同一行再排一遍, 只有目标词可见。
        # 排版完全一致 —— 同样的字、同样的 \fscx 留白, 所以线必然对齐, 不需要算坐标。
        uw = load_underlines(line["line"], chars)
        if uw:
            # 这一层的关键约束: **每一格恰好输出一次**, 且留白照原样补上 ——
            # 只要总宽和正文层不等, 两层各自居中就会整体错位。曾经用"标志位 + continue"
            # 写, 犯了两个错: 词尾标点被发两遍(多一个全角字宽 -> 左移半个字), 以及
            # 非下划线字的留白被 continue 跳过(有断点的行会错位)。改成显式区段循环。
            uset = {i for a, b in uw for i in range(a, b + 1)}
            HID = r"{\1a&HFF&\3a&HFF&\4a&HFF&\bord0\shad0\fscx100\fsp2}"

            def hgap(px):
                return (rf"{{\1a&HFF&\3a&HFF&\4a&HFF&\bord0\shad0\u0\fscx"
                        rf"{max(int(round(100*px/SPACE_ADV)),1)}}}\h")

            up, i = [], 0
            while i < n:
                if i in uset:
                    # 连续的一段合成同一个 {} 段 + \fsp0, 让 \u1 连成一条不断开。
                    # 遇到标点或留白就断段 —— 它们要按正文层原样补回去。
                    j = i
                    while (j + 1 < n and (j + 1) in uset
                           and not chars[j]["trailing"].strip() and gaps[j] == 0):
                        j += 1
                    # 用**全角空格 U+3000** 而不是原字: 等宽(排版不变)、无墨迹, 而 \u1 仍按
                    # 前进宽度画线。用原字的话, 本层下移之后深色字身会从正文底下露出来 ——
                    # \u1 的线和字身共用同一份颜色/透明度, 没法只藏字不藏线。
                    up.append(rf"{{\1c{C_ULINE}\3c{C_ULINE_EDGE}\1a&H20&\3a&H50&"
                              rf"\bord1\shad0\fscx100\fsp0\u1}}" + "　" * (j - i + 1))
                else:
                    j = i
                    up.append(HID + chars[j]["char"])
                if chars[j]["trailing"].strip():
                    up.append(HID + chars[j]["trailing"].strip())
                if gaps[j] > 0:
                    up.append(hgap(gaps[j]))
                i = j + 1
            # MarginV 调小 = 整层往下挪, 让线离开字身。用 Dialogue 自己的 MarginV
            # 字段做, 不用 \pos —— \pos 还得给 x, 又回到"自己算坐标"那条死路上。
            ev.append(f"Dialogue: 0,{ts(t0 - lin)},{ts(t1 + lout)},Sora,,0,0,"
                      f"{MARGIN_V - ULINE_DROP},,"
                      rf"{{\fad({fade_in},{fade_out})}}" + "".join(up))

        ev.append(f"Dialogue: 1,{ts(t0 - lin)},{ts(t1 + lout)},Sora,,0,0,0,,{text}")
        report.append((line["line"] + 1, t0 - lin, t1 + lout, name, gap_prev, gap_next))
    print(f"  扫光下限 {MIN_WIPE:.2f}s: 抬起 {stat_raised} 个字 "
          f"(原最短 {stat_min:.3f}s —— \\kf{cs(stat_min)} 等于瞬间弹出)")
    print(f"  速度限幅 {WIPE_LIMIT}x: 相邻字扫光速度跳变 "
          f"{stat_jump:.1f}x -> {stat_jump2:.1f}x")
    return ev, report


def main():
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
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

    inv = {v: k for k, v in TEMP.items()}
    nw = nb = 0
    for line in lines:
        ch = line["chars"]
        for i in sorted(load_breaks(line["line"], ch)):
            print(f"  断点   L{line['line']+1:<2} {ch[i]['char']} ‿ "
                  f"{ch[i+1]['char'] if i+1 < len(ch) else ''}")
            nb += 1
        for i0, i1, col in load_colors(line["line"], ch):
            w = "".join(ch[k]["char"] + ch[k]["trailing"] for k in range(i0, i1 + 1))
            print(f"  着色   L{line['line']+1:<2} {w:8s} {inv.get(col, '?')}")
            nw += 1
    nu = sum(len(load_underlines(l["line"], l["chars"])) for l in lines)
    print(f"  (断点 {nb} 处 / 着色 {nw} 个 / 下划线 {nu} 个)")
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
