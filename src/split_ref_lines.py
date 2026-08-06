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
    """把整段日文切成 [原文片段, 拍数, 此处原本是否有换行, 源行号] 的序列。

    记源行号是为了给译文用: 译文没有拍数可比, 但如果日/中两份源是**逐行对应**的
    (行数相同), 就可以把日文这边"第 i 行用了源第几行的多少拍"原样搬给译文,
    按语义对应而不是按长度猜。
    """
    import pykakasi
    out, li = [], 0
    for chunk in raw.split("\n"):
        chunk = chunk.strip()
        if not chunk:
            continue
        for s in pykakasi.kakasi().convert(chunk):
            orig = s["orig"]
            if not orig.strip():
                continue
            out.append([orig, C.morae(orig), False, li])
        if out:
            out[-1][2] = True                          # 这一段末尾原本是换行
        li += 1
    return out


def map_zh_by_line(ja_segs, cuts, zh_lines):
    """按**源行对应**把译文分成 15 行, 不靠长度猜。

    前提: 日/中两份源逐行对应 (行数相同)。
    日文那边已经算出"输出第 i 行吃掉了源第 L 行的多少拍", 把这张分配表原样搬到
    译文: 源第 L 行的译文, 按同样的比例、按顺序分给相应的输出行。
    于是译文的断句跟着**语义**走, 而不是跟着字数走。
    """
    n_out = len(cuts)
    # contrib[i][L] = 输出第 i 行从源第 L 行拿走的拍数
    contrib = [{} for _ in range(n_out)]
    for i, (a, b) in enumerate(cuts):
        for k in range(a, b):
            _, m, _, L = ja_segs[k]
            contrib[i][L] = contrib[i].get(L, 0) + m
    total_of = {}
    for c in contrib:
        for L, m in c.items():
            total_of[L] = total_of.get(L, 0) + m

    used = {}                                          # 每个源行已经切走多少字
    rows = []
    for i in range(n_out):
        buf = ""
        for L in sorted(contrib[i]):
            if L >= len(zh_lines):
                continue
            z = zh_lines[L]
            share = contrib[i][L] / max(total_of[L], 1)
            take = int(round(len(z) * share))
            s = used.get(L, 0)
            # 最后一个吃这一行的输出行, 把剩下的全收走, 避免四舍五入丢字
            last = max(j for j in range(n_out) if L in contrib[j])
            buf += z[s:] if i == last else z[s:s + take]
            used[L] = len(z) if i == last else s + take
        rows.append(buf.strip())
    return rows


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
    """动态规划: 在 segs 里找一个**连续窗口**, 切成 len(targets) 段, 偏差最小。

    dp[i][k] = 到第 i 个片段为止、已切出 k 段的最小总代价。
    代价用**相对偏差** |实得-目标| / max(目标,1) —— 短行差 2 拍比长行差 2 拍严重得多,
    用绝对值会让短行被牺牲掉。

    **必须允许跳过前后缀**: 粘进来的往往是整首歌词, 而空耳可能只覆盖其中一段
    (本片 15 行只到 84 秒, 占全曲 27%)。强行把全部文本分成 15 份, 多出来的拍数
    会被硬塞进某几行 —— 实际发生过: 源 531 拍 / 目标 149 拍, 结果某一行吃了 355 拍。
    做法: dp[j][0] 对所有 j 置 0 (前缀可跳过), 终点取所有 dp[i][K] 的最小值
    (后缀可跳过)。于是它会自己去找对得上的那一段。
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
    for j in range(n + 1):
        dp[j][0] = 0.0                             # 前缀可整段跳过
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
    end = min((i for i in range(K, n + 1) if dp[i][K] < INF),
              key=lambda i: dp[i][K], default=None)      # 后缀可整段跳过
    if end is None:
        raise SystemExit("ERROR: 找不到可行切法")

    cuts, i = [], end
    for k in range(K, 0, -1):
        j = back[i][k]
        cuts.append((j, i))
        i = j
    cuts.reverse()
    rows = ["".join(segs[a][0] for a in range(x, y)) for x, y in cuts]
    return rows, cuts


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

    zh_by_line = None
    if kind == "ja":
        segs = segments_ja(raw)
        targets = want
        unit = "拍"
    else:
        segs = segments_zh(raw)
        n_ch = sum(s[1] for s in segs)
        ja = M.read_ref("ja")
        # 首选: 日/中两份源逐行对应时, 按**源行**推, 不按字数猜 (见 map_zh_by_line)
        ja_raw_p = LYR / "ref_ja.raw.txt"
        if ja_raw_p.exists() and len(ja) == len(want):
            src = "\n".join(r for r in ja_raw_p.read_text(encoding="utf-8").splitlines()
                            if not r.lstrip().startswith("#"))
            ja_segs = segments_ja(src)
            n_ja_lines = (max(s[3] for s in ja_segs) + 1) if ja_segs else 0
            zh_lines = [r.strip() for r in raw.splitlines() if r.strip()]
            if n_ja_lines == len(zh_lines) and n_ja_lines > 0:
                _, ja_cuts = best_split(ja_segs, want)
                zh_by_line = map_zh_by_line(ja_segs, ja_cuts, zh_lines)
        # 关键: 译文源同样是整首歌, 但空耳只覆盖其中一段。目标字数必须按**日文那一段
        # 占日文全文的比例**折算, 不能按整份译文算 —— 否则目标合计 = 全文字数,
        # 等于强迫 DP 把全曲译文塞进 15 行, 窗口选择完全失效 (实际踩过: 选了 96%)。
        frac, ja_raw = 1.0, LYR / "ref_ja.raw.txt"
        if ja_raw.exists() and len(ja) == len(want):
            src = ja_raw.read_text(encoding="utf-8")
            src = "\n".join(r for r in src.splitlines()
                            if not r.lstrip().startswith("#"))
            src_m = sum(s[1] for s in segments_ja(src))
            win_m = sum(C.morae(x) for x in ja)
            if src_m > 0:
                frac = min(win_m / src_m, 1.0)
                print(f"  日文只用到源文本的 {100*frac:.0f}%, 译文按同比例折算目标")
        budget = n_ch * frac
        if len(ja) == len(want):
            tot = sum(len(x) for x in ja)
            targets = [max(round(budget * len(x) / tot), 1) for x in ja]
        else:
            tot = sum(want)
            targets = [max(round(budget * w / tot), 1) for w in want]
        unit = "字"

    tot_src = sum(s[1] for s in segs)
    print(f"  源文本 {len(segs)} 个片段 / {tot_src} {unit}, 目标 {sum(targets)} {unit}")
    if tot_src > sum(targets) * 1.3:
        print(f"  源文本比空耳覆盖的范围长 {tot_src/sum(targets):.1f} 倍 —— "
              f"将自动截取对得上的那一段")
    rows, cuts = best_split(segs, targets)
    used = sum(s[1] for s in segs[cuts[0][0]:cuts[-1][1]])
    print(f"  选中窗口: 第 {cuts[0][0]+1}-{cuts[-1][1]} 个片段 ({used} {unit}, "
          f"占源文本 {100*used/tot_src:.0f}%)")

    if kind == "zh" and zh_by_line is not None:
        rows = zh_by_line
        print("  改用**源行对应**切分 (日/中源行数一致), 不按字数猜")

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
