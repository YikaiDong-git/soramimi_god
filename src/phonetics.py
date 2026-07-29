#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把日文罗马音音节和中文拼音音节投影到同一个发音特征空间。

这是整条流水线里唯一没有现成工具的部分。

问题: 强制对齐给出的是"日文音节 -> 时间"。字幕上要显示的是用户的中文空耳。
      两边的单位数还不一样 (实例: 用户第 2 行 7 个汉字, 对应的日文行有 10 拍)。
      按字数比例平摊会在快歌段明显跑偏。

解法: 空耳本来就是照着"听起来像"写的, 所以音素相似度本身就是最强的对齐信号。
      把两边都拆成 (声母/辅音, 韵腹/元音, 韵尾) 三元组, 每一维用发音特征向量表示,
      得到一个跨语言可比的距离, 再在这个距离上做 DTW。

特征定义参考 IPA 的发音部位/发音方法/清浊, 以及元音的高低-前后-圆唇三维。
数值是为"跨语言粗粒度相似"调的, 不追求语音学精确 —— 目标是让 ka/卡、shi/西
这类对应拿到低代价, 让 ka/mu 这类拿到高代价。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ---------------------------------------------------------------- 辅音特征
# (place, manner, voiced)
#   place : 0 双唇 .15 唇齿 .3 齿龈 .45 龈后/卷舌 .6 龈腭 .7 硬腭 .85 软腭 1.0 声门
#   manner: 0 塞音 .25 塞擦 .5 擦音 .75 鼻音 .9 边/闪 1.0 半元音
CONS = {
    # --- 共有 ---
    "":    (0.5, 0.5, 0.5),   # 零声母: 中性, 与任何辅音距离都不大
    "p":   (0.00, 0.00, 0.0), "b": (0.00, 0.00, 1.0),
    "m":   (0.00, 0.75, 1.0),
    "f":   (0.15, 0.50, 0.0), "v": (0.15, 0.50, 1.0),
    "t":   (0.30, 0.00, 0.0), "d": (0.30, 0.00, 1.0),
    "n":   (0.30, 0.75, 1.0),
    "s":   (0.30, 0.50, 0.0), "z": (0.30, 0.50, 1.0),
    "ts":  (0.30, 0.25, 0.0), "dz": (0.30, 0.25, 1.0),
    "l":   (0.30, 0.90, 1.0), "r": (0.30, 0.90, 1.0),
    "sh":  (0.60, 0.50, 0.0), "j": (0.60, 0.25, 1.0),
    "ch":  (0.60, 0.25, 0.0),
    "y":   (0.70, 1.00, 1.0),
    "k":   (0.85, 0.00, 0.0), "g": (0.85, 0.00, 1.0),
    "ng":  (0.85, 0.75, 1.0),
    "h":   (1.00, 0.50, 0.0),
    "w":   (0.00, 1.00, 1.0),
    # --- 拼音专有 (卷舌/龈腭) ---
    "zh":  (0.45, 0.25, 0.0), "sr": (0.45, 0.50, 0.0),
    "q":   (0.60, 0.25, 0.0), "x": (0.60, 0.50, 0.0),
    "c":   (0.30, 0.25, 0.0),
}
# 拼音 sh 与日文 sh 发音部位不同 (卷舌 vs 龈腭), 单独区分
CONS_PINYIN_OVERRIDE = {
    "sh": (0.45, 0.50, 0.0),
    "ch": (0.45, 0.25, 0.0),
    "r":  (0.45, 0.50, 1.0),   # 拼音 r 是卷舌浊擦音, 不是闪音
    "j":  (0.60, 0.25, 0.0),   # 拼音 j 不送气清塞擦, 非浊音
}

# ---------------------------------------------------------------- 元音特征
# (height, backness, round)  height: 1 高 .5 中 0 低 ; backness: 0 前 1 后
VOW = {
    "":  (0.5, 0.5, 0.0),
    "i": (1.00, 0.00, 0.0),
    "y": (1.00, 0.00, 1.0),    # 拼音 ü
    "u": (1.00, 1.00, 1.0),
    "v": (1.00, 1.00, 0.0),    # 日文 u 实际是非圆唇后高元音
    "e": (0.50, 0.00, 0.0),
    "o": (0.50, 1.00, 1.0),
    "a": (0.00, 0.50, 0.0),
    "@": (0.50, 0.50, 0.0),    # 央元音 (拼音 e)
    "r": (0.50, 0.60, 0.0),    # 儿化/空韵
}

W_CONS, W_VOW, W_CODA = 0.40, 0.45, 0.15

# ---------------------------------------------------------------- 日文罗马音
JA_ONSETS = ["sh", "ch", "ts", "ky", "gy", "ny", "hy", "by", "py", "my", "ry",
             "j", "k", "g", "s", "z", "t", "d", "n", "h", "b", "p", "m", "y",
             "r", "w", "f", "v"]


@dataclass(frozen=True)
class Phone:
    """一个音节的音素三元组。"""
    onset: str
    vowel: str
    coda: str
    src: str = ""

    def __repr__(self):
        return f"<{self.src}:{self.onset}|{self.vowel}|{self.coda}>"


def parse_romaji(syl: str) -> Phone:
    """日文罗马音音节 -> Phone。yohane 的 auto_split 会产出 'n'(拨音) 和 't'(促音) 这类无元音节。"""
    s = syl.strip().lower()
    if not s:
        return Phone("", "", "", syl)
    # 拨音 / 促音: 无元音
    if s == "n":
        return Phone("", "", "n", syl)
    if len(s) == 1 and s in "ktspbdgz":
        return Phone(s, "", "", syl)          # 促音, 视为纯辅音

    onset = ""
    for o in JA_ONSETS:
        if s.startswith(o):
            onset, s = o, s[len(o):]
            break
    # 拗音 ky/gy/... 归一化: 主辅音 + 腭化 (腭化并入部位偏移)
    if len(onset) == 2 and onset.endswith("y") and onset != "sh":
        onset = onset[0]
    vowel = ""
    for v in ["a", "i", "u", "e", "o"]:
        if v in s:
            vowel = v
            break
    if vowel == "u":
        vowel = "v"                            # 日文 u 非圆唇
    coda = "n" if s.endswith("n") else ""
    return Phone(onset, vowel, coda, syl)


# ---------------------------------------------------------------- 中文拼音
PY_FINAL_MAP = {
    # final -> (主元音, 韵尾)
    "a": ("a", ""),   "o": ("o", ""),   "e": ("@", ""),   "i": ("i", ""),
    "u": ("u", ""),   "v": ("y", ""),   "ü": ("y", ""),
    "ai": ("a", "i"), "ei": ("e", "i"), "ao": ("a", "u"), "ou": ("o", "u"),
    "an": ("a", "n"), "en": ("@", "n"), "ang": ("a", "ng"), "eng": ("@", "ng"),
    "ong": ("o", "ng"), "er": ("r", ""),
    "ia": ("a", ""),  "ie": ("e", ""),  "iao": ("a", "u"), "iu": ("o", "u"),
    "iou": ("o", "u"), "ian": ("a", "n"), "in": ("i", "n"),
    "iang": ("a", "ng"), "ing": ("i", "ng"), "iong": ("o", "ng"),
    "ua": ("a", ""),  "uo": ("o", ""),  "uai": ("a", "i"), "ui": ("e", "i"),
    "uei": ("e", "i"), "uan": ("a", "n"), "un": ("@", "n"), "uen": ("@", "n"),
    "uang": ("a", "ng"), "ueng": ("@", "ng"),
    "ve": ("e", ""),  "üe": ("e", ""),  "van": ("a", "n"), "üan": ("a", "n"),
    "vn": ("y", "n"), "ün": ("y", "n"),
}


def parse_pinyin(initial: str, final: str) -> Phone:
    """拼音 (声母, 韵母) -> Phone。"""
    ini = (initial or "").lower()
    fin = (final or "").lower().strip()
    fin = re.sub(r"[0-9]", "", fin)
    # 介音: 归入声母的腭化/唇化, 主元音取韵腹
    v, c = PY_FINAL_MAP.get(fin, ("", ""))
    if not v:
        for k in sorted(PY_FINAL_MAP, key=len, reverse=True):
            if fin.endswith(k):
                v, c = PY_FINAL_MAP[k]
                break
    if not v and fin:
        v = fin[0] if fin[0] in "aoeiuv" else "@"
    return Phone(ini, v, c, initial + final)


def _feat_c(name: str, pinyin: bool):
    if pinyin and name in CONS_PINYIN_OVERRIDE:
        return CONS_PINYIN_OVERRIDE[name]
    return CONS.get(name, CONS[""])


def phone_distance(a: Phone, b: Phone, a_pinyin=False, b_pinyin=True) -> float:
    """两个音节的发音距离, 归一化到 [0,1]。"""
    ca, cb = _feat_c(a.onset, a_pinyin), _feat_c(b.onset, b_pinyin)
    dc = sum(abs(x - y) for x, y in zip(ca, cb)) / 3.0

    va, vb = VOW.get(a.vowel, VOW[""]), VOW.get(b.vowel, VOW[""])
    dv = sum(abs(x - y) for x, y in zip(va, vb)) / 3.0

    # 韵尾: 完全一致 0, 都无 0, 一有一无 0.5, 不同 1
    if a.coda == b.coda:
        dk = 0.0
    elif not a.coda or not b.coda:
        dk = 0.5
    else:
        dk = 1.0

    # 无元音的音节 (促音/拨音) 只比辅音和韵尾
    if not a.vowel or not b.vowel:
        return W_CONS / (W_CONS + W_CODA) * dc + W_CODA / (W_CONS + W_CODA) * dk

    return W_CONS * dc + W_VOW * dv + W_CODA * dk


def romaji_syllables_to_phones(syls) -> list:
    return [parse_romaji(s) for s in syls]


def hanzi_to_phones(text: str) -> tuple:
    """中文字符串 -> (保留的汉字列表, Phone 列表)。标点空格被丢弃。"""
    from pypinyin import Style, lazy_pinyin

    chars = [c for c in text if "一" <= c <= "鿿"]
    if not chars:
        return [], []
    ini = lazy_pinyin(chars, style=Style.INITIALS, strict=False)
    fin = lazy_pinyin(chars, style=Style.FINALS, strict=False)
    phones = [parse_pinyin(i, f) for i, f in zip(ini, fin)]
    for p, c in zip(phones, chars):
        object.__setattr__(p, "src", c)
    return chars, phones


if __name__ == "__main__":
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    print("=== 自检: 空耳应当比随机汉字距离更小 ===")
    pairs = [
        ("ha", "哈"), ("na", "那"), ("bi", "笔"),      # hanabi -> 哈那笔
        ("ka", "卡"), ("shi", "西"), ("to", "拖"),
        ("ha", "木"), ("na", "去"), ("bi", "光"),      # 对照: 不像的
    ]
    for r, h in pairs:
        pj = parse_romaji(r)
        _, ph = hanzi_to_phones(h)
        d = phone_distance(pj, ph[0], a_pinyin=False, b_pinyin=True)
        print(f"  {r:4s} vs {h}   d={d:.3f}   {pj} {ph[0]}")
