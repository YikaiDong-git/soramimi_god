#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""layout_variants.py — 「原文 + 翻译 + 空耳」对照版式候选生成器。

产出: 每个候选版式渲染 1-2 帧原生 1920x1080 JPG, 汇总成一张 HTML 供作者挑选。
用法: python layout_variants.py            # 全部候选
      python layout_variants.py E3 C1      # 只跑指定候选

--------------------------------------------------------------------------
参考行的文本来源
--------------------------------------------------------------------------
本脚本读 02_lyrics/ref_ja.txt / ref_zh.txt (每行一句, 与空耳 15 行一一对应)。
文件缺失时自动落到**占位文本**, 并在画面右上角打 "PLACEHOLDER" 角标。

占位不是随便填的 —— 版式判断只依赖**文本度量**(每行多少字、注音多宽),
所以占位按真实数据生成:
  · 参考行长度  = 该行真实音节数换算的典型字数
  · 注音每格音节数 = 从 soramimi_timed.json 的 ja_syls 读真实值
    (实测 136 字里 124 字 1 音 / 11 字 2 音 / 1 字 3 音 —— 双音格挤不挤,
     占位下看到的和真文本下看到的是同一回事)
换成真文本只需把两个 txt 填上再跑一遍, 版式不用重挑。

--------------------------------------------------------------------------
三条硬约束 (踩过的坑, 见 ENGINEERING.md §6)
--------------------------------------------------------------------------
1. 空耳主行**原样复用 make_ass.build()** 的输出, 逐字扫光 / 断点 / 着色 /
   下划线全部与成品一致。本脚本只改 Dialogue 的 Layer / MarginL / MarginR /
   MarginV 四个字段, 绝不重写文本 —— 重写一遍就等于开了第二份实现, 迟早分叉。

2. 注音层的排版**不在本文件里** —— `ruby_row` / `adv` / `ref_text` 全部从
   make_ass 导入。选型脚本依赖生产脚本, 不能反过来: 一旦各写一份, 分叉之后
   这里的诊断图就证明不了成片 (§6.30)。

3. libass 的 Fontsize **不等于 em**。渲染实测 Fontsize 78 -> 全角字形前进
   59.1px, 比值 0.7577 (61.1 是**字距** = 字形 + Spacing 2, §6.28)。
   本文件启动时用两个独立实测值反查这条度量链, 对不上直接报错退出。
"""
import io
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import json

from PIL import ImageFont

ARGV = sys.argv[1:]                           # 先存下来 —— make_ass 会读 argv,
sys.argv = [sys.argv[0]]                      # 下一行 import 之前必须清空
import make_ass as M                          # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"
SRC = ROOT / "00_source"
OUTD = ROOT / "05_qc" / "layout_options"
FF = "C:/Users/59827/karaoke/tools/ffmpeg/bin/ffmpeg.exe"
FONT_FILE = "C:/Windows/Fonts/msyh.ttc"

# --------------------------------------------------------------------------
# 排版度量 —— 全部由 measure_metrics.py 从 libass 的渲染结果数像素得来, 不是推算。
# (2026-08-06 实测, Microsoft YaHei @ Fontsize 78, ScaledBorderAndShadow yes)
#
# 顺带查出 make_ass.py 里两个常量名不副实, 见 ENGINEERING.md §6.28:
#   GLYPH_W = 61.1  实为**字距**(字形 59.1 + Spacing 2), 不是字形宽度
#   SPACE_ADV = 68.6 实测只有 15.6 —— 差 4.4 倍
# 这两处在 make_ass 内部自洽 (主行和下划线层用同一个公式, 所以仍然对齐),
# 但本脚本要跨层对齐, 必须用真值。
# --------------------------------------------------------------------------
# 度量与注音排版**全部取自 make_ass** —— 选型脚本依赖生产脚本, 不能反过来。
# 两份实现迟早分叉, 而一旦分叉, 这里的诊断图就证明不了成片 (§6.30)。
GLYPH = M.GLYPH_TRUE      # 全角字形前进宽度 @78
FSP = 2                   # Style Sora 的 Spacing
PITCH = M.PITCH           # 主行每格的实际前进 = 61.1 (= make_ass 的 GLYPH_W)
H_ADV = M.H_ADV           # \h 字形前进 @78
EM = M.EM_RATIO           # Fontsize -> em 比值 0.7577; 全角 = 1 em
adv = M.adv
ref_text = M.ref_text
ruby_syls = M.ruby_syls
ruby_row = M.ruby_row

# 参考行配色
C_JA = r"&HE8E8E8&"      # 日文原句: 近白
C_ZH = r"&HC8DCE6&"      # 中译: 微暖白
C_RUBY = r"&HB4E6E6&"    # 注音: 淡青
A_JA = r"&H30&"          # 透明度 (00=不透明, FF=全透)
A_ZH = r"&H40&"
A_RUBY = r"&H28&"



def _selfcheck():
    """拿两个独立实测值反查 PIL 度量链, 对不上就别往下跑了。"""
    g = adv("好", M.FONT_SIZE)
    io_ = adv("　", M.FONT_SIZE)
    if abs(g - GLYPH) > 0.5:
        raise SystemExit(f"ERROR: 全角宽度对不上 —— PIL {g:.2f} vs 渲染实测 {GLYPH}")
    if abs(io_ - GLYPH) > 0.5:
        raise SystemExit(f"ERROR: U+3000 应等于 1 em —— PIL {io_:.2f} vs {GLYPH}")
    print(f"  度量自检 OK: 全角 {g:.2f}px · 字距 {PITCH:.1f}px · "
          rf"\h {H_ADV:.1f}px · em 比值 {EM:.4f}")


# --------------------------------------------------------------------------
# 参考行文本
# --------------------------------------------------------------------------






# --------------------------------------------------------------------------
# 注音层 (flow 排版, 零绝对坐标)
# --------------------------------------------------------------------------


def tick_row(chars, gaps, size, line=None):
    """诊断用: 每格中央一根竖线。走的是**和成片同一段** ruby_row, 所以这张诊断图
    验的确实是成片的排版, 不是另一份实现的排版。

    竖线**必须挂在真实注音后面**, 不能只发一根光秃秃的 `|`:
    全是等宽窄 token 的话, "多拍格子太宽"这条路径根本不会被触发 —— 曾经因此漏掉
    一次真实回归 (给宽格子向邻居借宽度, 整行注音都偏了, 而诊断仍报 0.87px 通过)。
    测试夹具必须和真实内容同形, 否则它只证明"在它自己那种输入下没错"。
    """
    return ruby_row(chars, gaps, size, "", syls=[["|"] for _ in chars])


# --------------------------------------------------------------------------
# 候选版式
# --------------------------------------------------------------------------
# geom : ffmpeg 画面几何 (None = 原样)
# sora : 空耳主行的 MarginL / MarginR / MarginV
# ruby : 注音 (size, mv, sep) —— mv 是距底距离
# ja/zh: 参考行 (an=8 顶部 / an=2 底部, mv 是距该边距离, size 字号)
# band : 半透明色带 (y, h, 颜色, 透明度), 画在最底层
BASE_MV = M.MARGIN_V

VARIANTS = [
    # ---------------- A 三行叠压 (画面不动) ----------------
    dict(key="A1", grp="A 三行叠压", name="日文 / 中译 / 空耳",
         desc="全部堆在底部, 画面不缩。最省事, 但底部约 300px 被压住。",
         sora=dict(mv=BASE_MV),
         ja=dict(an=2, mv=BASE_MV + 196, size=42),
         zh=dict(an=2, mv=BASE_MV + 126, size=42)),
    dict(key="A2", grp="A 三行叠压", name="中译 / 日文 / 空耳",
         desc="把中译放最上 —— 中文观众先读懂意思, 再往下看原文和空耳。",
         sora=dict(mv=BASE_MV),
         zh=dict(an=2, mv=BASE_MV + 196, size=42),
         ja=dict(an=2, mv=BASE_MV + 128, size=38)),
    dict(key="A3", grp="A 三行叠压", name="日文+中译合并一行 / 空耳",
         desc="原文和译文并排挤一行, 省掉一整行高度。行长会变长。",
         sora=dict(mv=BASE_MV), merge=True,
         ja=dict(an=2, mv=BASE_MV + 128, size=38)),
    dict(key="A4", grp="A 三行叠压", name="日文(小) / 空耳 / 中译(底)",
         desc="空耳夹在中间当主角, 原文在上、译文在下, 视觉重心不被抢。",
         sora=dict(mv=BASE_MV + 66),
         ja=dict(an=2, mv=BASE_MV + 166, size=38),
         zh=dict(an=2, mv=BASE_MV - 4, size=40)),

    # ---------------- B 左右分栏 ----------------
    dict(key="B1", grp="B 左右分栏", name="画面居左 982x552 · 右栏三行",
         desc="文字栏留满宽。画面掉到整屏面积的 26% —— 手机上会很小。",
         geom="scale=940:529,pad=1920:1080:0:276:0x0A0A0F",
         sora=dict(mv=442, ml=968, mr=32),
         ja=dict(an=2, mv=652, size=40, ml=968, mr=32),
         zh=dict(an=2, mv=578, size=40, ml=968, mr=32)),
    dict(key="B2", grp="B 左右分栏", name="画面 1120x630 · 右栏窄 · 空耳缩到 62px",
         desc="多留点画面给 MV, 代价是空耳字号被压小, 扫光的存在感下降。",
         geom="scale=1120:630,pad=1920:1080:0:225:0x0A0A0F",
         sora=dict(mv=460, ml=1140, mr=30, fs=62),
         ja=dict(an=2, mv=610, size=36, ml=1140, mr=30),
         zh=dict(an=2, mv=550, size=36, ml=1140, mr=30)),

    # ---------------- C 底部信息带 (仍是标准 16:9) ----------------
    dict(key="C1", grp="C 底部信息带", name="画面 1920x810 + 270px 黑带 · 带内放原文译文",
         desc="画面零遮挡, 文字永远在纯色上。画面线性缩到 75%。",
         geom="scale=1920:810,pad=1920:1080:0:0:0x000000",
         sora=dict(mv=286),
         ja=dict(an=2, mv=150, size=44),
         zh=dict(an=2, mv=76, size=44)),
    dict(key="C2", grp="C 底部信息带", name="带内放空耳+中译 · 日文顶部浮在画面上",
         desc="空耳搬进色带里, 扫光背景永远干净; 只有日文一行轻压画面。",
         geom="scale=1920:810,pad=1920:1080:0:0:0x000000",
         sora=dict(mv=110),
         ja=dict(an=8, mv=34, size=40),
         zh=dict(an=2, mv=32, size=40)),
    dict(key="C3", grp="C 底部信息带", name="画面 1920x756 + 324px 带 · 三行全在带内",
         desc="画面 0 遮挡的极端版。带子占 30% 画高, 但读区完全独立。",
         geom="scale=1920:756,pad=1920:1080:0:0:0x000000",
         sora=dict(mv=104),
         ja=dict(an=2, mv=254, size=42),
         zh=dict(an=2, mv=190, size=42)),
    dict(key="C4", grp="C 底部信息带", name="半透明带 (画面透出来) · 不缩画面",
         desc="画面不缩, 底部铺一层半透明暗色。折中: 遮挡但不全遮, 也不损失画幅。",
         sora=dict(mv=BASE_MV),
         band=(786, 294, r"&H0C0A08&", r"&H58&"),
         ja=dict(an=2, mv=BASE_MV + 196, size=42),
         zh=dict(an=2, mv=BASE_MV + 126, size=42)),

    # ---------------- D 上下分置 ----------------
    dict(key="D1", grp="D 上下分置", name="日文顶 / 空耳+中译底",
         desc="原文送到画面顶部, 底部只留空耳和中译。遮挡分散到两处。",
         sora=dict(mv=BASE_MV + 62),
         ja=dict(an=8, mv=44, size=42),
         zh=dict(an=2, mv=BASE_MV - 6, size=40)),
    dict(key="D2", grp="D 上下分置", name="日文+中译都在顶 / 空耳独占底",
         desc="底部完全留给空耳, 参考信息统一在顶部。眼睛要上下跑一趟。",
         sora=dict(mv=BASE_MV),
         ja=dict(an=8, mv=36, size=40),
         zh=dict(an=8, mv=100, size=40)),
    dict(key="D3", grp="D 上下分置", name="中译顶 / 日文+空耳底",
         desc="意思放顶部、声音放底部 —— 按「读什么」而不是按「哪国字」分区。",
         sora=dict(mv=BASE_MV),
         zh=dict(an=8, mv=40, size=42),
         ja=dict(an=2, mv=BASE_MV + 128, size=38)),

    # ---------------- E 逐字注音 ----------------
    dict(key="E1", grp="E 逐字注音", name="注音 + 空耳 (不放原文和译文)",
         desc="最克制的一版: 只把「这个字读什么音」摆出来, 只多占 45px。",
         sora=dict(mv=BASE_MV),
         ruby=dict(size=34, mv=BASE_MV + 84, sep="")),
    dict(key="E2", grp="E 逐字注音", name="注音 + 空耳 + 中译",
         desc="加一行中译补意思。原文汉字省掉 —— 中文观众本来也读不了。",
         sora=dict(mv=BASE_MV + 56),
         ruby=dict(size=34, mv=BASE_MV + 140, sep=""),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),
    dict(key="E3", grp="E 逐字注音", name="注音 + 空耳 + 日文顶 + 中译底  ★推荐",
         desc="三者各司其职: 注音负责证明, 中译负责意思, 原文只作证不指望读。",
         sora=dict(mv=BASE_MV + 56),
         ruby=dict(size=34, mv=BASE_MV + 140, sep=""),
         ja=dict(an=8, mv=40, size=40),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),
    dict(key="E4", grp="E 逐字注音", name="注音放在字**下方**",
         desc="声乐谱把辅助记号放下方。代价: 注音离下一行更近, 更容易看串。",
         sora=dict(mv=BASE_MV + 52),
         ruby=dict(size=34, mv=BASE_MV - 2, sep=""),
         ja=dict(an=8, mv=40, size=40)),
    dict(key="E5", grp="E 逐字注音", name="注音带音节点 na·ka",
         desc="双音字中间加分隔点, 让「一个字扛两拍」这件事更直白。",
         sora=dict(mv=BASE_MV + 56),
         ruby=dict(size=34, mv=BASE_MV + 140, sep="·"),
         ja=dict(an=8, mv=40, size=40),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),
    dict(key="E6", grp="E 逐字注音", name="注音 + 空耳 + 底部色带放原文译文",
         desc="E 和 C 的组合: 画面缩 25% 换零遮挡, 注音仍然贴着空耳。",
         geom="scale=1920:810,pad=1920:1080:0:0:0x000000",
         sora=dict(mv=286),
         ruby=dict(size=32, mv=286 + 82, sep=""),
         ja=dict(an=2, mv=150, size=42),
         zh=dict(an=2, mv=76, size=42)),

    # ---------------- F 注音细节档位 (都基于 E3) ----------------
    dict(key="F1", grp="F 注音档位", name="注音 28px (最轻)",
         desc="注音退到几乎是脚注, 完全不抢戏 —— 但小屏上可能看不清。",
         sora=dict(mv=BASE_MV + 50),
         ruby=dict(size=28, mv=BASE_MV + 132, sep=""),
         ja=dict(an=8, mv=40, size=40),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),
    dict(key="F2", grp="F 注音档位", name="注音 42px (最重)",
         desc="注音几乎和参考行一样大, 证据感最强, 但版面开始拥挤。",
         sora=dict(mv=BASE_MV + 66),
         ruby=dict(size=42, mv=BASE_MV + 156, sep=""),
         ja=dict(an=8, mv=40, size=40),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),
    dict(key="F3", grp="F 注音档位", name="注音跟随字色 (不用统一灰青)",
         desc="注音染成和它头顶那个字一样的颜色, 对应关系再加一重视觉线索。",
         sora=dict(mv=BASE_MV + 56),
         ruby=dict(size=34, mv=BASE_MV + 140, sep="", follow=True),
         ja=dict(an=8, mv=40, size=40),
         zh=dict(an=2, mv=BASE_MV - 8, size=40)),

    # ---------------- 诊断 ----------------
    dict(key="ZZ", grp="Z 诊断", name="格宽诊断: 每格中央一根竖线",
         desc="竖线必须落在每个字正中。歪了就是格宽算错, 不是渲染器的问题。",
         sora=dict(mv=BASE_MV), tick=dict(size=34, mv=BASE_MV + 84), black=True),
]


# --------------------------------------------------------------------------
# ASS 组装
# --------------------------------------------------------------------------
def styles_block():
    return (
        f"Style: Ref,{M.FONT},40,&H00FFFFFF&,&H00FFFFFF&,&H00201008&,&H80000000&,"
        f"0,0,0,0,100,100,0,0,1,2.4,1.4,2,60,60,40,1\n"
        f"Style: Ruby,{M.FONT},34,&H00FFFFFF&,&H00FFFFFF&,&H00201008&,&H80000000&,"
        f"0,0,0,0,100,100,0,0,1,2.0,0,2,60,60,40,1\n"
        f"Style: Box,{M.FONT},40,&H00FFFFFF&,&H00FFFFFF&,&H00000000&,&H00000000&,"
        f"0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
    )


def retime(dialogue, layer=None, ml=None, mr=None, mv=None):
    """改写一条 Dialogue 的 Layer / MarginL / MarginR / MarginV, 文本一字不动。"""
    head, _, rest = dialogue.partition(":")
    f = rest.split(",", 9)                      # 前 9 字段固定, 第 10 个是文本
    f = [x.strip() for x in f[:9]] + [f[9]]
    if layer is not None:
        f[0] = str(layer)
    if ml is not None:
        f[5] = str(ml)
    if mr is not None:
        f[6] = str(mr)
    if mv is not None:
        f[7] = str(mv)
    return head + ": " + ",".join(f)


def build_ass(v, lines, plan):
    ev, _ = M.build(lines, plan)                # 主行 = 成品同款, 不重写

    so = v.get("sora", {})
    body = []
    for d in ev:
        lay = int(d.partition(":")[2].split(",", 1)[0])
        body.append(retime(d, layer=lay + 2,    # 给色带腾出 layer 0/1
                           ml=so.get("ml"), mr=so.get("mr"),
                           mv=so.get("mv") if lay == 1 else
                              (so.get("mv", BASE_MV) - M.ULINE_DROP)))

    if v.get("sora", {}).get("fs"):             # 需要改字号时整体 \fs 前置
        fs = v["sora"]["fs"]
        body = [b.replace(",,{\\fad", ",,{\\fs%d\\fad" % fs)
                if ",,{\\fad" in b else b for b in body]

    extra = []
    if v.get("band"):
        y, h, col, alp = v["band"]
        extra.append(f"Dialogue: 0,0:00:00.00,0:10:00.00,Box,,0,0,0,,"
                     rf"{{\p1\an7\pos(0,{y})\1c{col}\1a{alp}\bord0\shad0}}"
                     f"m 0 0 l 1920 0 l 1920 {h} l 0 {h}")

    placeholder = False
    for k, line in enumerate(lines):
        chars = line["chars"]
        t0, t1 = chars[0]["start"], chars[-1]["end"]
        gp = (t0 - lines[k - 1]["chars"][-1]["end"]) if k > 0 else 99.0
        gn = (lines[k + 1]["chars"][0]["start"] - t1) if k + 1 < len(lines) else 99.0
        lin = min(M.LEAD_IN / 1000, max(gp, 0) * M.GAP_SHARE)
        lout = min(M.LEAD_OUT / 1000, max(gn, 0) * M.GAP_SHARE)
        a, b = M.ts(t0 - lin), M.ts(t1 + lout)
        fi = min(M.FADE, int(lin * 1000)) if lin > 0 else 0
        fo = min(M.FADE, int(lout * 1000)) if lout > 0 else 0
        fad = rf"{{\fad({fi},{fo})}}"

        gaps, _, _ = M.layout(chars,
                              M.load_breaks(line["line"], chars),
                              M.load_colors(line["line"], chars))
        n_syl = len(line.get("ja_syls") or []) or len(chars)

        if v.get("ruby"):
            r = v["ruby"]
            syls = [ruby_syls(c, i) for i, c in enumerate(chars)]
            cols = None
            if r.get("follow"):
                # 复刻主行的取色: 词级着色优先, 否则按配色方案的位置渐变
                _, wcol, _ = M.layout(chars, M.load_breaks(line["line"], chars),
                                      M.load_colors(line["line"], chars))
                fn = M.SCHEMES[M.scheme_for(line["line"], M.DEFAULT_PLAN)][0]
                cols = [wcol[i] or fn(i, len(chars)) for i in range(len(chars))]
            row = ruby_row(chars, gaps, r["size"], r["sep"], syls, cols)
            extra.append(f"Dialogue: 4,{a},{b},Ruby,,{so.get('ml', 60)},"
                         f"{so.get('mr', 60)},{r['mv']},,"
                         rf"{fad}{{\fs{r['size']}\1c{C_RUBY}\1a{A_RUBY}}}{row}")

        if v.get("tick"):
            t = v["tick"]
            extra.append(f"Dialogue: 4,{a},{b},Ruby,,60,60,{t['mv']},,"
                         rf"{fad}{{\fs{t['size']}\1c&H00FFFF&\1a&H00&}}"
                         + tick_row(chars, gaps, t["size"]))

        if v.get("merge") and v.get("ja"):
            ja, p1 = ref_text("ja", k, n_syl)
            zh, p2 = ref_text("zh", k, n_syl)
            placeholder |= p1 or p2
            cfg = v["ja"]
            extra.append(f"Dialogue: 4,{a},{b},Ref,,{cfg.get('ml',60)},"
                         f"{cfg.get('mr',60)},{cfg['mv']},,"
                         rf"{fad}{{\an{cfg['an']}\fs{cfg['size']}\1c{C_JA}\1a{A_JA}}}"
                         rf"{ja}{{\1c{C_ZH}}}　—　{zh}")
        else:
            for kind, col, alp in (("ja", C_JA, A_JA), ("zh", C_ZH, A_ZH)):
                cfg = v.get(kind)
                if not cfg:
                    continue
                txt, ph = ref_text(kind, k, n_syl)
                placeholder |= ph
                extra.append(f"Dialogue: 4,{a},{b},Ref,,{cfg.get('ml',60)},"
                             f"{cfg.get('mr',60)},{cfg['mv']},,"
                             rf"{fad}{{\an{cfg['an']}\fs{cfg['size']}\1c{col}\1a{alp}}}{txt}")

    if placeholder:
        extra.append(r"Dialogue: 5,0:00:00.00,0:10:00.00,Ref,,0,24,20,,"
                     r"{\an9\fs26\1c&H8080F0&\1a&H30&}PLACEHOLDER 参考行为占位文本")

    hdr = M.header("layout")
    hdr = hdr.replace("[Events]", styles_block() + "\n[Events]")
    return hdr + "\n".join(body + extra) + "\n"


# --------------------------------------------------------------------------
# 渲染
# --------------------------------------------------------------------------
SHOTS = [("L15", 82.6), ("L03", 37.5)]         # 最长一行(带下划线) / 带着色词的一行


def render(v, ass_path, mv_path, tag, t):
    out = OUTD / f"{v['key']}_{tag}.jpg"
    vf = (v["geom"] + ",") if v.get("geom") else ""
    # 诊断帧把画面刷黑再叠字幕: 位置要靠数像素判, 亮背景 (L15 那盏灯) 会让阈值
    # 分割整片连成一块, 竖线根数直接数错。用 drawbox 而不是换成 lavfi 纯色源 ——
    # 纯色源没有真实时间戳, .ass 的绝对时间对不上, 出来是一张全黑的空帧。
    black = "drawbox=x=0:y=0:w=iw:h=ih:c=black:t=fill," if v.get("black") else ""
    # -copyts + 输入 seek: 时间戳不归零, .ass 里的绝对时间才对得上 (§6.6)
    cmd = [FF, "-y", "-loglevel", "error", "-copyts", "-ss", f"{t:.2f}",
           "-i", str(mv_path), "-vf", f"{vf}{black}ass={ass_path.name}",
           "-frames:v", "1", "-q:v", "2", str(out)]
    r = subprocess.run(cmd, cwd=str(ass_path.parent), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if not out.exists() or out.stat().st_size < 4000:
        print(f"    FAILED {v['key']} {tag}: {r.stderr.strip()[:200]}")
        return None
    return out


def main():
    keys = [a for a in ARGV if not a.startswith("--")]
    todo = [v for v in VARIANTS if not keys or v["key"] in keys]
    if not todo:
        raise SystemExit(f"没有匹配的候选。可用: {', '.join(v['key'] for v in VARIANTS)}")

    _selfcheck()
    lines = json.loads((LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    mv = next(p for p in SRC.glob("*.mp4") if not p.name.endswith(".part"))
    OUTD.mkdir(parents=True, exist_ok=True)
    work = OUTD / "_ass"
    work.mkdir(exist_ok=True)

    ref_real = (LYR / "ref_ja.txt").exists() and (LYR / "ref_zh.txt").exists()
    print(f"  参考行文本: {'真实文件' if ref_real else '占位 (ref_ja.txt / ref_zh.txt 未提供)'}")
    print(f"  候选 {len(todo)} 个 x {len(SHOTS)} 帧\n")

    made = []
    for v in todo:
        ass = work / f"{v['key']}.ass"
        ass.write_text(build_ass(v, lines, M.DEFAULT_PLAN), encoding="utf-8-sig")
        shots = []
        for tag, t in SHOTS:
            p = render(v, ass, mv, tag, t)
            if p:
                shots.append(p.name)
        print(f"  {v['key']:<4} {v['name'][:44]:<46} {len(shots)}/{len(SHOTS)} 帧")
        made.append((v, shots))

    (OUTD / "index.json").write_text(json.dumps(
        [dict(key=v["key"], grp=v["grp"], name=v["name"], desc=v["desc"],
              geom=v.get("geom"), shots=s) for v, s in made],
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n输出 -> {OUTD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
