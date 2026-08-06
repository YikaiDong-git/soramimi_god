#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""split_ref_lines.py — 把整段粘贴的参考文本自动切成与空耳一一对应的 15 行。

解决的是贴歌词时**唯一真正费事的一步**: 断行。
    歌词本按印刷排版分行, 没有任何理由和这 15 行空耳的断句一致 (本片 ASR 只分出
    14 段, 其中一段横跨 0.54-70.45 秒)。手工对断行要反复试听, 错一行后面全错位,
    而画面上"每行都有字", 不抽帧发现不了。

做法 (日文):
    对齐器已经量出每一行那段音频里有多少个音节。把粘进来的整段日文按形态素切开、
    数出每一小段的拍数, 然后用**动态规划**找一种切法, 使 15 段的拍数与音频实测值
    的总偏差最小 —— 也就是让文字的节奏去贴音频的节奏。
    切点只落在形态素边界上 (不会把一个词劈成两半), 并且原文里本来就有换行的位置
    额外加分 —— 你自己的断行是有信息的, 只是不一定和音频对齐。

做法 (中文):
    译文没有拍数可比, 按**与对应日文行的长度成比例**切, 并优先切在标点处。
    精度不如日文, 所以务必看一眼输出表再用。

用法:
    1. 把整段日文粘进 02_lyrics/ref_ja.raw.txt   (随便怎么分行)
    2. python split_ref_lines.py ja              # 写出 ref_ja.txt 并打表
    3. 同理 ref_zh.raw.txt -> python split_ref_lines.py zh
    4. python check_ref_lines.py                 # 独立复核
    --dry 只打表不写文件。
"""
import json
import sys
from pathlib import Path

# 这里**不包** sys.stdout: 替换掉 sys.stdout 会让原对象失去引用被回收, 顺手关掉
# 底层 buffer, 后面所有 print 报 "I/O operation on closed file" (§6.14 又踩一次)。
# 本项目一律用 PYTHONIOENCODING=utf-8 跑, 不需要包。
ARGV = sys.argv[1:]
sys.argv = [sys.argv[0]]
import make_ass as M                                   # noqa: E402
import check_ref_lines as C                            # noqa: E402

LYR = M.LYR
NEWLINE_BONUS = 1.2      # 原文换行处切一刀, 相当于少算 1.2 拍偏差
ZH_PUNCT = "，。、；：！？,;:!?…—"


def segments_ja(raw):
    """把整段日文切成 (原文片段, 拍数, 此处原本是否有换行) 的序列。"""
    import pykakasi
    out = []
    for chunk in raw.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        segs = pykakasi.kakasi().convert(chunk)
        for i, s in enumerate(segs):
            orig = s["orig"]
            if not orig.strip():
                continue
            out.append([orig, C.morae(orig), False])
        if out:
            out[-1][2] = True                          # 这一段末尾原本是换行
    return out


def segments_zh(raw):
    """中文按标点切段; 没有标点就退化成逐字。"""
    out, buf = [], ""
    for chunk in raw.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        for ch in chunk:
            buf += ch
            if ch in ZH_PUNCT:
                out.append([buf, len(buf), False])
                buf = ""
        if buf:
            out.append([buf, len(buf), False])
            buf = ""
        if out:
            out[-1][2] = True
    return out


def best_split(segs, targets):
    """动态规划: 把 segs 切成 len(targets) 段, 使各段权重和与 target 的偏差最小。

    dp[i][k] = 前 i 个片段切成 k 段的最小总代价。
    代价用**相对偏差** |实得-目标| / max(目标,1) —— 短行差 2 拍比长行差 2 拍严重得多,
    用绝对值会让短行被牺牲掉。
    """
    n, K = len(segs), len(targets)
    if n < K:
        raise SystemExit(f"ERROR: 只切出 {n} 个片段, 不够分成 {K} 行 —— 文本太短?")
    w = [s[1] for s in segs]
    pre = [0]
    for x in w:
        pre.append(pre[-1] + x)

    INF = float("inf")
    dp = [[INF] * (K + 1) for _ in range(n + 1)]
    back = [[-1] * (K + 1) for _ in range(n + 1)]
    dp[0][0] = 0.0
    for k in range(1, K + 1):
        tgt = targets[k - 1]
        for i in range(k, n - (K - k) + 1):
            for j in range(k - 1, i):
                if dp[j][k - 1] == INF:
                    continue
                got = pre[i] - pre[j]
                cost = abs(got - tgt) / max(tgt, 1)
                if not segs[i - 1][2]:                 # 没切在原文换行处
                    cost += NEWLINE_BONUS / max(tgt, 1)
                v = dp[j][k - 1] + cost
                if v < dp[i][k]:
                    dp[i][k] = v
                    back[i][k] = j
    if dp[n][K] == INF:
        raise SystemExit("ERROR: 找不到可行切法")

    cuts, i = [], n
    for k in range(K, 0, -1):
        j = back[i][k]
        cuts.append((j, i))
        i = j
    cuts.reverse()
    return ["".join(segs[a][0] for a in range(x, y)) for x, y in cuts]


def main():
    kind = (ARGV[0] if ARGV and not ARGV[0].startswith("--") else "ja")
    if kind not in ("ja", "zh"):
        raise SystemExit("用法: python split_ref_lines.py [ja|zh] [--dry]")
    dry = "--dry" in ARGV

    lines = json.loads((LYR / "soramimi_timed.json").read_text(encoding="utf-8"))
    want = [L.get("n_ja_syls") or len(L.get("ja_syls") or L["chars"]) for L in lines]

    raw_p = LYR / f"ref_{kind}.raw.txt"
    if not raw_p.exists():
        raise SystemExit(f"ERROR: 缺 {raw_p}\n"
                         f"  把整段{'日文原句' if kind=='ja' else '中文译文'}"
                         f"粘进这个文件 (随便怎么分行), 再跑一次。")
    raw = raw_p.read_text(encoding="utf-8")
    raw = "\n".join(r for r in raw.splitlines() if not r.lstrip().startswith("#"))

    if kind == "ja":
        segs = segments_ja(raw)
        targets = want
        unit = "拍"
    else:
        segs = segments_zh(raw)
        ja = M.read_ref("ja")
        if len(ja) == len(want):
            tot = sum(len(x) for x in ja)
            n_ch = sum(s[1] for s in segs)
            targets = [max(round(n_ch * len(x) / tot), 1) for x in ja]
        else:
            tot = sum(want)
            n_ch = sum(s[1] for s in segs)
            targets = [max(round(n_ch * w / tot), 1) for w in want]
        unit = "字"

    print(f"  片段 {len(segs)} 个, 总{unit}数 {sum(s[1] for s in segs)}, "
          f"目标 {sum(targets)}")
    rows = best_split(segs, targets)

    print(f"\n  {'行':>3} {'目标':>5} {'实得':>5} {'差':>5}   文本")
    print("  " + "-" * 62)
    worst = 0
    for i, (r, t) in enumerate(zip(rows, targets)):
        got = C.morae(r) if kind == "ja" else len(r)
        d = got - t
        worst = max(worst, abs(d))
        flag = "  <<" if abs(d) > 2 and abs(d) > 0.3 * t else ""
        print(f"  L{i+1:<2} {t:>5} {got:>5} {d:>+5}   {r}{flag}")
    print("  " + "-" * 62)
    print(f"  最大偏差 {worst} {unit}")

    if dry:
        print("\n  --dry: 未写文件")
        return 0
    out = LYR / f"ref_{kind}.txt"
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n  写出 -> {out.name}")
    print("  务必看一眼上表再往下走 —— 切分是按节奏猜的, 语义对不对只有你知道。")
    print("  下一步: python check_ref_lines.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
