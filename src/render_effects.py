#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 32 种特效各渲染一份样片, 供人工挑选。

流程:
    1. 用 PyonFX 读入基准 .ass (带 \\kf 的那份), 拿到每个字的坐标和时序
    2. 对每种特效, 逐字发三条 Dialogue (pre / hit / post)
    3. 生成 .ass, 再压一小段样片 + 抽帧

为什么样片要把时间轴整体前移:
    ffmpeg 用 -ss 在 -i 之前定位时会把输出时间戳归零, 而 .ass 是绝对时间,
    直接裁会让字幕整体偏移 (本项目已实测踩过: 差值正好等于裁剪起点)。
    这里的做法是生成样片专用 .ass 时就把所有时间减掉窗口起点, 两边都从 0 开始, 对齐。

样片选段:
    默认取第 11 行所在窗口 —— 画面是烟花炸开, 亮暗对比强, 最能看出特效差异。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# 本文件既是脚本也被 make_mixed.py 当模块 import, 所以绝不碰 sys.stdout。
# 两层 io.TextIOWrapper 套同一个 buffer, 先被 GC 的那层会把 buffer 关掉,
# 结果一 print 就 ValueError: I/O operation on closed file。
# 中文输出统一靠环境变量 PYTHONIOENCODING=utf-8。

sys.path.insert(0, str(Path(__file__).resolve().parent))
from effects import EFFECTS, DESC, LEAD_IN, LEAD_OUT, Ctx  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SUBS = ROOT / "03_subs"
FXDIR = SUBS / "fx"
OUT = ROOT / "04_output" / "fx_samples"
QC = ROOT / "05_qc" / "fx"
FF = "C:/Users/59827/karaoke/tools/ffmpeg-shared71/bin/ffmpeg.exe"
BASE = SUBS / "soramimi_cool_cyan.ass"

# 样片窗口 (秒) —— 覆盖第 11 行 (68.23-70.45s), 画面正好是烟花
WIN_START, WIN_END = 66.5, 72.5

HEADER = """[Script Info]
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sora,Microsoft YaHei,78,&H00F0C000&,&H00FFFFFF&,&H00301808&,&H80000000&,-1,0,0,0,100,100,2,0,1,4,2,2,60,60,96,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def ts(ms: float) -> str:
    if ms < 0:
        ms = 0
    s, cs = divmod(int(round(ms / 10)), 100)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}.{cs:02d}"


def build(fx_name, lines, shift_ms=0.0, only_window=False):
    """生成某种特效的 .ass 事件列表。shift_ms 为负则整体前移。"""
    fn = EFFECTS[fx_name]
    ev = []
    for line in lines:
        l0, l1 = line.start_time, line.end_time
        if only_window and (l1 < WIN_START * 1000 or l0 > WIN_END * 1000):
            continue
        n = len(line.syls)
        for i, syl in enumerate(line.syls):
            c = Ctx(d=max(int(syl.duration), 1), i=i, n=n,
                    x=syl.center, y=line.middle)
            pre, hit, post = fn(c)
            s0 = l0 + syl.start_time
            s1 = l0 + syl.end_time
            segs = [
                (l0 - LEAD_IN, s0, pre),
                (s0, s1, hit),
                (s1, l1 + LEAD_OUT, post),
            ]
            for a, b, tags in segs:
                if b - a < 5:
                    continue
                ev.append(f"Dialogue: 0,{ts(a+shift_ms)},{ts(b+shift_ms)},Sora,,0,0,0,,"
                          f"{{{tags}}}{syl.text}")
    return ev


def main():
    from pyonfx import Ass

    FXDIR.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    QC.mkdir(parents=True, exist_ok=True)

    io_ = Ass(str(BASE), str(SUBS / "_tmp.ass"), extended=True)
    meta, styles, lines = io_.get_data()
    print(f"基准字幕: {len(lines)} 行, {sum(len(l.syls) for l in lines)} 字")

    mv = next(p for p in (ROOT / "00_source").glob("*.mp4") if not p.name.endswith(".part"))
    names = sorted(EFFECTS)
    print(f"特效: {len(names)} 种\n")

    for k in names:
        # 1) 全片版 .ass (以后选定了直接用)
        full = FXDIR / f"fx_{k}.ass"
        full.write_text(HEADER + "\n".join(build(k, lines)) + "\n", encoding="utf-8-sig")

        # 2) 样片版: 只保留窗口内的行, 时间整体前移到 0
        samp = FXDIR / f"_sample_{k}.ass"
        ev = build(k, lines, shift_ms=-WIN_START * 1000, only_window=True)
        samp.write_text(HEADER + "\n".join(ev) + "\n", encoding="utf-8-sig")

        # 3) 压样片
        out = OUT / f"fx_{k}.mp4"
        r = subprocess.run(
            [FF, "-y", "-loglevel", "error",
             "-ss", str(WIN_START), "-t", str(WIN_END - WIN_START), "-i", str(mv),
             "-vf", f"ass={samp.name}",
             "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23",
             "-b:v", "0", "-pix_fmt", "yuv420p", "-an", str(out)],
            cwd=str(FXDIR), capture_output=True, text=True, encoding="utf-8", errors="replace")
        ok = out.exists() and out.stat().st_size > 10000
        if not ok:
            print(f"  FAIL {k}: {r.stderr.strip()[:160]}")
            continue

        # 4) 抽 1 帧 (取第 11 行唱到一半时)
        j = QC / f"{k}.jpg"
        subprocess.run([FF, "-y", "-loglevel", "error", "-ss", "2.6", "-i", str(out),
                        "-frames:v", "1", "-q:v", "3", "-vf", "scale=960:-2", str(j)],
                       capture_output=True)
        print(f"  OK  {k:16s} {out.stat().st_size/1e6:5.1f} MB   {DESC[k][:44]}")

    print(f"\n样片 -> {OUT}")
    print(f"抽帧 -> {QC}")
    print(f"全片字幕 -> {FXDIR}/fx_*.ass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
