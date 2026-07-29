#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""分段特效: 不同的歌曲段落用不同的逐字特效。

动机:
    整曲一种特效会让情绪是平的。主歌用克制的冷色、副歌换成炸开的彩虹,
    情绪推进就直接体现在字上了。

用法:
    python make_mixed.py                       # 用下面的 DEFAULT_PLAN
    python make_mixed.py 0-8:28_ice 9-:26_rainbow

段落写法:
    "a-b:fx"  行号 a 到 b (含两端, 0 起算) 用特效 fx
    "a-:fx"   从 a 到最后
    行号即 soramimi_timed.json 里的 line 序号。

输出:
    03_subs/fx/fx_mixed_<tag>.ass   —— 直接喂给 burn.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from effects import EFFECTS, DESC, LEAD_IN, LEAD_OUT, Ctx  # noqa: E402
from render_effects import HEADER, ts, BASE                # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
FXDIR = ROOT / "03_subs" / "fx"

# 第 1-9 行 (主歌) 寒冰, 第 10 行起 (从「啪！」那句开始的副歌) 彩虹
DEFAULT_PLAN = [(0, 8, "28_ice"), (9, None, "26_rainbow")]


def parse_plan(argv):
    if not argv:
        return DEFAULT_PLAN
    plan = []
    for a in argv:
        rng, fx = a.split(":")
        lo, _, hi = rng.partition("-")
        plan.append((int(lo), int(hi) if hi else None, fx))
    return plan


def fx_for(line_idx, plan):
    for lo, hi, name in plan:
        if line_idx >= lo and (hi is None or line_idx <= hi):
            return name
    return plan[-1][2]


def main():
    from pyonfx import Ass

    plan = parse_plan(sys.argv[1:])
    for _, _, name in plan:
        if name not in EFFECTS:
            raise SystemExit(f"ERROR: 未知特效 {name}\n可用: {', '.join(sorted(EFFECTS))}")

    FXDIR.mkdir(parents=True, exist_ok=True)
    io_ = Ass(str(BASE), str(ROOT / "03_subs" / "_tmp_mixed.ass"), extended=True)
    _, _, lines = io_.get_data()

    print("分段方案:")
    for lo, hi, name in plan:
        rng = f"L{lo+1}-L{hi+1}" if hi is not None else f"L{lo+1}-末尾"
        print(f"  {rng:12s} {name:14s} {DESC[name]}")
    print()

    ev = []
    used = {}
    for line in lines:
        idx = getattr(line, "i", None)
        if idx is None:
            idx = lines.index(line)
        name = fx_for(idx, plan)
        used.setdefault(name, []).append(idx + 1)
        fn = EFFECTS[name]
        l0, l1 = line.start_time, line.end_time
        n = len(line.syls)
        for i, syl in enumerate(line.syls):
            c = Ctx(d=max(int(syl.duration), 1), i=i, n=n,
                    x=syl.center, y=line.middle)
            pre, hit, post = fn(c)
            s0, s1 = l0 + syl.start_time, l0 + syl.end_time
            for a, b, tags in ((l0 - LEAD_IN, s0, pre), (s0, s1, hit),
                               (s1, l1 + LEAD_OUT, post)):
                if b - a < 5:
                    continue
                ev.append(f"Dialogue: 0,{ts(a)},{ts(b)},Sora,,0,0,0,,{{{tags}}}{syl.text}")

    tag = "_".join(n.split("_", 1)[1] for _, _, n in plan)
    out = FXDIR / f"fx_mixed_{tag}.ass"
    out.write_text(HEADER + "\n".join(ev) + "\n", encoding="utf-8-sig")

    print("实际分配:")
    for name, idxs in used.items():
        print(f"  {name:14s} 行 {idxs}")
    print(f"\n写出 -> {out}")
    print(f"压制: python burn.py mixed_{tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
