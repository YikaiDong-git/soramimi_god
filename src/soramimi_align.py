#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把日文音节的时间轴重新映射到用户的中文空耳字上 (子序列 DTW)。

问题的本质:
    强制对齐给的是 [日文音节 -> (start,end)]。字幕上要显示的是中文空耳。
    两边单位数不等 —— 用户第 2 行 7 个汉字对应的日文行有 10 拍。
    而且用户的断句和 ASR 的断句不保证一致, 所以不能按行号硬配。

做法:
    1. 把日文音节和空耳汉字各自拉平成一条全局序列。
    2. 用 phonetics.py 的跨语言发音距离建代价矩阵。
    3. 子序列 DTW: 空耳必须被完整匹配, 但在日文序列上起点终点自由
       (因为空耳只覆盖了全曲约 1/3, 且开头可能差一两句)。
    4. 回溯路径 -> 每个汉字继承一段 [start,end]。
    5. 逐行整理成 \\k 需要的 gapless 时长。

为什么是子序列而不是整段 DTW:
    整段 DTW 会强迫最后一个空耳字去匹配全曲最后一个音节, 把中间全部拉伸变形。
    D[0][j]=0 (起点自由) + 末行取 min (终点自由) 才是正确的形式。

非对角步惩罚:
    没有惩罚时 DTW 会退化 —— 让一个日文音节吸收掉十几个汉字, 代价矩阵上确实更省。
    加一个小惩罚, 逼它保持接近单调一一对应。
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phonetics import hanzi_to_phones, parse_romaji, phone_distance  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LYR = ROOT / "02_lyrics"

STEP_PENALTY = 0.18      # 非对角步的额外代价, 抑制退化路径
MIN_CHAR_SEC = 0.06      # 单字最短显示时长, 低于这个值说明对齐塌缩了
START_SKIP_PENALTY = 0.15  # 起点每跳过一个真实音节的代价 (见 subsequence_dtw 注释)
VOCAL_REL_THR = 0.02     # 人声能量门限, 取人声轨峰值 RMS 的比例


# ----------------------------------------------------------------- 读入
def vocal_gate():
    """返回一个函数 has_vocal(t0,t1) -> bool, 用人声轨能量判断某时段是否真的有人在唱。

    为什么需要: Whisper 在纯器乐段会产生幻觉文本 (实测本曲 0-25s 人声 RMS 恒为
    0.00000, 却被转出了内容), 强制对齐只好把这些不存在的音节硬塞进静音区 ——
    实测出现过 "14 个音节挤在 0.46 秒内" 这种物理不可能的结果。
    这些幽灵音节会污染 DTW 的参考序列, 必须先按证据剔除, 而不是硬编码一个偏移量。
    """
    import numpy as np
    import soundfile as sf

    wav = ROOT / "01_stems" / "vocals.wav"
    x, sr = sf.read(str(wav), dtype="float32", always_2d=True)
    x = x.mean(axis=1)
    hop = int(0.05 * sr)                       # 50 ms 粒度
    n = len(x) // hop
    rms = np.sqrt(np.array([np.mean(x[i*hop:(i+1)*hop] ** 2) for i in range(n)]))
    thr = rms.max() * VOCAL_REL_THR

    def has_vocal(t0, t1):
        a = max(int(t0 / 0.05), 0)
        b = min(int(t1 / 0.05) + 1, n)
        return b > a and bool((rms[a:b] > thr).any())

    return has_vocal, float(thr), float(rms.max())


def load_ja():
    p = LYR / "syllables_ja.json"
    if not p.exists():
        raise SystemExit(f"ERROR: 缺 {p}, 先跑 force_align.py")
    data = json.loads(p.read_text(encoding="utf-8"))
    has_vocal, thr, peak = vocal_gate()

    flat, dropped = [], 0
    for line in data:
        for s in line["syllables"]:
            if s is None:
                continue
            if not has_vocal(s["start_s"], s["end_s"]):
                dropped += 1
                continue
            flat.append({
                "line": line["line"], "v": s["v"],
                "start": s["start_s"], "end": s["end_s"],
            })
    print(f"人声门限: peak_rms={peak:.4f} thr={thr:.5f}")
    print(f"剔除落在无人声区的幽灵音节: {dropped} 个 (Whisper 幻觉)")
    return data, flat


def load_soramimi():
    p = LYR / "soramimi_user.txt"
    raw = p.read_text(encoding="utf-8").splitlines()
    lines = []
    inside = False
    for ln in raw:
        if ln.startswith("# ---- BEGIN SORAMIMI"):
            inside = True
            continue
        if ln.startswith("# ---- END SORAMIMI"):
            break
        if inside and ln.strip():
            lines.append(ln.rstrip())
    return lines


# ----------------------------------------------------------------- DTW
def subsequence_dtw(cost):
    """空耳全匹配, 日文序列上起终点自由。返回 [(i,j), ...] 路径。"""
    M, N = len(cost), len(cost[0])
    INF = float("inf")
    D = [[INF] * N for _ in range(M)]
    B = [[None] * N for _ in range(M)]

    # 起点"半自由": 允许从任意位置开始, 但跳过的每一个音节都要付一点代价。
    # 完全免费的自由起点是错的 —— 实测它让整条路径系统性晚了一整句 (跳过 198 个音节
    # 和跳过 0 个一样便宜), 而跨语言音素距离本身较宽松, 一个错位的起点只要总代价
    # 低一丁点就会赢。空耳是从歌曲开头写起的, 所以"跳得越多越可疑"这个先验必须编进代价。
    for j in range(N):
        D[0][j] = cost[0][j] + j * START_SKIP_PENALTY

    for i in range(1, M):
        for j in range(N):
            best, arg = INF, None
            if j > 0 and D[i - 1][j - 1] < best:
                best, arg = D[i - 1][j - 1], (i - 1, j - 1)          # 对角: 1 汉字 <-> 1 音节
            v = D[i - 1][j] + STEP_PENALTY
            if v < best:
                best, arg = v, (i - 1, j)                            # 多个汉字共享一个音节
            if j > 0:
                v = D[i][j - 1] + STEP_PENALTY
                if v < best:
                    best, arg = v, (i, j - 1)                        # 一个汉字吸收多个音节
            if arg is not None:
                D[i][j] = best + cost[i][j]
                B[i][j] = arg

    j_end = min(range(N), key=lambda j: D[M - 1][j])                 # 终点自由
    path, i, j = [], M - 1, j_end
    while True:
        path.append((i, j))
        prev = B[i][j]
        if prev is None or i == 0:
            break
        i, j = prev
    path.reverse()
    return path, D[M - 1][j_end] / M


# ----------------------------------------------------------------- 主流程
def main():
    ja_lines, ja = load_ja()
    sora_lines = load_soramimi()
    print(f"日文音节: {len(ja)} 个 / {len(ja_lines)} 行")
    print(f"空耳     : {len(sora_lines)} 行")

    # 拉平空耳, 记录每个汉字属于哪一行, 以及行内非汉字符号挂在哪个字后面
    chars, owner, trailing = [], [], []
    for li, line in enumerate(sora_lines):
        cs, _ = hanzi_to_phones(line)
        buf = ""
        ci = 0
        for ch in line:
            if "一" <= ch <= "鿿":
                chars.append(ch)
                owner.append(li)
                trailing.append("")
                ci += 1
            elif chars:
                trailing[-1] += ch
        del buf, cs, ci
    print(f"空耳汉字 : {len(chars)} 个\n")

    _, sora_phones = hanzi_to_phones("".join(chars))
    ja_phones = [parse_romaji(s["v"]) for s in ja]

    cost = [[phone_distance(sp, jp, a_pinyin=True, b_pinyin=False)
             for jp in ja_phones] for sp in sora_phones]

    path, mean_cost = subsequence_dtw(cost)
    print(f"DTW 平均每字代价: {mean_cost:.4f}  (0=完美, >0.5=可疑)")

    # 每个汉字收集它对上的日文音节
    per_char = [[] for _ in chars]
    for i, j in path:
        per_char[i].append(j)

    timed = []
    for i, ch in enumerate(chars):
        js = per_char[i]
        st = min(ja[j]["start"] for j in js)
        en = max(ja[j]["end"] for j in js)
        d = sum(cost[i][j] for j in js) / len(js)
        timed.append({
            "i": i, "char": ch, "line": owner[i], "trailing": trailing[i],
            "start": round(st, 4), "end": round(en, 4),
            "ja_syls": [ja[j]["v"] for j in js],
            "cost": round(d, 4),
        })

    # 单调化: 起点不得早于前一个字的起点, 且不得为负长度
    for i in range(1, len(timed)):
        if timed[i]["start"] < timed[i - 1]["start"]:
            timed[i]["start"] = timed[i - 1]["start"]
        if timed[i]["end"] <= timed[i]["start"]:
            timed[i]["end"] = round(timed[i]["start"] + MIN_CHAR_SEC, 4)

    # 按行组装
    out_lines = []
    for li, text in enumerate(sora_lines):
        items = [t for t in timed if t["line"] == li]
        if not items:
            continue
        out_lines.append({
            "line": li,
            "text": text,
            "start": items[0]["start"],
            "end": items[-1]["end"],
            "n_chars": len(items),
            "mean_cost": round(sum(t["cost"] for t in items) / len(items), 4),
            "chars": items,
            "ja_syls": [s for t in items for s in t["ja_syls"]],
        })

    p = LYR / "soramimi_timed.json"
    p.write_text(json.dumps(out_lines, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 报告 ----
    rep = ["# 空耳对齐报告", "",
           f"- 日文音节总数: {len(ja)}",
           f"- 空耳汉字总数: {len(chars)}",
           f"- DTW 平均每字代价: {mean_cost:.4f}",
           f"- 覆盖日文音节区间: {min(j for _, j in path)} .. {max(j for _, j in path)}"
           f" (占全曲 {100*(max(j for _,j in path)-min(j for _,j in path)+1)/len(ja):.0f}%)",
           "", "## 逐行", "",
           "| 行 | 空耳 | 起-止(s) | 字数 | 日文音节数 | 平均代价 | 判定 |",
           "|---|---|---|---|---|---|---|"]
    for o in out_lines:
        flag = "OK" if o["mean_cost"] < 0.35 else ("偏高" if o["mean_cost"] < 0.5 else "**可疑**")
        rep.append(f"| {o['line']+1} | {o['text']} | {o['start']:.2f}-{o['end']:.2f} | "
                   f"{o['n_chars']} | {len(o['ja_syls'])} | {o['mean_cost']:.3f} | {flag} |")

    worst = sorted(timed, key=lambda t: -t["cost"])[:15]
    rep += ["", "## 对得最勉强的 15 个字", "",
            "| 空耳字 | 对上的日文音节 | 代价 | 时间 |", "|---|---|---|---|"]
    for t in worst:
        rep.append(f"| {t['char']} | {' '.join(t['ja_syls'])} | {t['cost']:.3f} | "
                   f"{t['start']:.2f}-{t['end']:.2f} |")

    (LYR / "align_report.md").write_text("\n".join(rep) + "\n", encoding="utf-8")
    print(f"写出 -> {p}")
    print(f"写出 -> {LYR/'align_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
