#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把 .ass 硬压进 MV (libass 渲染 + NVENC 编码), 并抽帧自检。

路径转义:
    ffmpeg 的 filtergraph 里 Windows 路径是噩梦 —— 反斜杠、盘符冒号都要转义。
    最省事且最可靠的办法是把 cwd 切到 .ass 所在目录, filter 里只写文件名。

编码:
    h264_nvenc, 2070 SUPER (Turing) 硬编。-cq 19 视觉无损, 4:58 的片子约 1-2 分钟。
    音频直接 copy, 不重编 —— 我们没动过音频。

字体:
    fontsdir 指向 C:/Windows/Fonts, 保证 libass 找得到微软雅黑。
    找不到字体时 libass 不会报错, 会静默回退到某个默认字体 -> 中文变方块。
    所以必须靠抽帧肉眼验, 不能只看 ffmpeg 的返回码。
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
# 用 7.1 而不是 master 构建做编码:
#   master (n-125829, 2026-07-28) 的 h264_nvenc 要求 nvenc API 13.1 / 驱动 >=610,
#   本机驱动 591.86 只到 API 13.0 -> "Driver does not support the required nvenc API version"。
#   7.1 的 nvenc 实测可用 (已压出 1.5 MB 测试片段)。
FF = Path("C:/Users/59827/karaoke/tools/ffmpeg-shared71/bin/ffmpeg.exe")
SRC = ROOT / "00_source"
SUBS = ROOT / "03_subs"
OUT = ROOT / "04_output"
QC = ROOT / "05_qc"


def find_mv():
    c = [p for p in SRC.glob("*.mp4") if not p.name.endswith(".part")]
    if not c:
        raise SystemExit(f"ERROR: {SRC} 下没有 MV")
    return c[0]


def shift_ass(src: Path, dst: Path, shift_s: float) -> Path:
    """把 .ass 的所有 Dialogue 时间整体前移 shift_s 秒。

    为什么必须配合 -ss 一起用:
        -ss 放在 -i 之前时 ffmpeg 会把输出时间戳归零, 而 .ass 里是绝对时间。
        只裁视频不移字幕, 字幕就会整体晚 shift_s 秒 (本项目 §6.6 踩过)。
        两边都从 0 开始才对齐。
    """
    def sh(stamp: str) -> str:
        h, mi, s = stamp.strip().split(":")
        t = max(int(h) * 3600 + int(mi) * 60 + float(s) - shift_s, 0.0)
        return f"{int(t//3600)}:{int(t%3600//60):02d}:{t%60:05.2f}"

    out_lines = []
    for ln in src.read_text(encoding="utf-8-sig").splitlines():
        if ln.startswith("Dialogue:"):
            head, _, rest = ln.partition(":")
            # Dialogue 前 9 个字段固定, 第 10 个字段(文本)里可能含逗号, 所以限制切分次数
            f = rest.split(",", 9)
            f[1], f[2] = sh(f[1]), sh(f[2])
            ln = head + ":" + ",".join(f)
        out_lines.append(ln)
    dst.write_text("\n".join(out_lines) + "\n", encoding="utf-8-sig")
    return dst


def burn(mv: Path, ass: Path, out: Path, trim: float = 0.0,
         geom: str = "", limit: float = 0.0):
    """默认压全片。

    为什么曾经取消了"只压一小段"的预览模式:
        用 -ss 放在 -i 之前做输入定位时, ffmpeg 会把输出时间戳重置为 0, 而 .ass 里
        写的是绝对时间 -> 字幕整体偏移了裁剪起点。实测: 第 1 行应在 25.72s, 却出现
        在预览的 26.69s 处 (= 绝对 50.4s), 差值正好等于 23.7s 的裁剪起点。
        -copyts / -start_at_zero 能修, 但语义微妙容易再踩; 全片编码在 12x 实时下
        只要 ~25 秒, 直接消掉这一整类 bug。要短片段用 cut_clip() 从成品流拷贝。

    limit > 0 (预览) 为什么是安全的:
        它用的是 **-t (限制输出时长)**, 不是 -ss —— 起点仍然是 0, 时间戳不重置,
        所以上面那类偏移根本不会发生。只有"从中间截取"才危险, "只压前 N 秒"不危险。
        版式选型要一口气压好几个版本, 全片 x5 太浪费。

    geom 是版式的画面几何 (缩放 + 补边), 必须排在 ass 之前 —— 字幕要叠在
    已经摆好位置的画面上, 顺序反了字幕会跟着一起被缩放。

    trim > 0 是唯一的例外 —— 砍掉 UP 主自制片头。这时必须同步把 .ass 前移相同量
    (shift_ass), 两边都从 0 起算才对齐。不能用流拷贝砍片头: 本片关键帧只在
    0 / 5.005 / 10.010 秒 (GOP=5s), 2.85s 处没有关键帧, 流拷贝会吸到 0s (带上整个
    片头) 或 5.005s (切掉官方标题卡)。也不该去砍已压好的成片 —— 那是二次编码,
    从原始 MV 重压一次质量更好。
    """
    cmd = [str(FF), "-y", "-loglevel", "warning", "-stats"]
    if trim > 0:
        cmd += ["-ss", f"{trim:.3f}"]
    # 不传 fontsdir: filtergraph 里 Windows 盘符的冒号需要多层转义, 实测
    # "fontsdir=C\\:/Windows/Fonts" 会被解析成 "No option name near '/Windows/Fonts'"。
    # libass 在 Windows 上本来就走系统字体查找, 能直接找到 Microsoft YaHei。
    # 字体找不到时 libass 不报错、静默回退 -> 中文变方块, 所以必须靠抽帧肉眼验。
    cmd += ["-i", str(mv)]
    if limit > 0:
        cmd += ["-t", f"{limit:.2f}"]
    cmd += [
        "-vf", f"{geom + ',' if geom else ''}ass={ass.name}",
        "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19",
        "-b:v", "0", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
    ]
    r = subprocess.run(cmd, cwd=str(ass.parent), capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("FFMPEG FAILED:")
        print(r.stderr[-2500:])
        return False
    tail = [l for l in (r.stderr or "").splitlines() if l.strip()][-3:]
    for l in tail:
        print("   ", l)
    return True


def grab_qc(video: Path, times: list, tag: str):
    d = QC / tag
    d.mkdir(parents=True, exist_ok=True)
    made = []
    for t in times:
        j = d / f"t{t:07.2f}.jpg"
        subprocess.run([str(FF), "-y", "-loglevel", "error", "-ss", str(t),
                        "-i", str(video), "-frames:v", "1", "-q:v", "2",
                        "-vf", "scale=960:-2", str(j)], check=False)
        if j.exists():
            made.append(j)
    return made


def cut_clip(full: Path, out: Path, start: float, dur: float):
    """从已压好的成品里流拷贝一段短片 —— 不重新渲染字幕, 所以不会有时间轴偏移。"""
    r = subprocess.run([str(FF), "-y", "-loglevel", "error",
                        "-ss", str(start), "-t", str(dur), "-i", str(full),
                        "-c", "copy", str(out)], capture_output=True, text=True)
    return r.returncode == 0 and out.exists()


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    which = args[0] if args else "ice_rainbow"
    trim = 0.0
    layout = None
    preview = 0.0
    for a in sys.argv[1:]:
        if a.startswith("--trim="):
            trim = float(a.split("=", 1)[1])
        elif a.startswith("--layout="):
            layout = a.split("=", 1)[1]
        elif a == "--preview":
            preview = 90.0
        elif a.startswith("--preview="):
            preview = float(a.split("=", 1)[1])

    from make_ass import LAYOUTS           # 版式定义只有一份, 在 make_ass 里
    if layout and layout not in LAYOUTS:
        raise SystemExit(f"ERROR: 未知版式 {layout}\n可用: {', '.join(LAYOUTS)}")
    geom = LAYOUTS[layout].get("geom", "") if layout else ""
    if layout:
        which = f"{which}_{layout}"        # 字幕名和成品名都带上版式, 不会混

    OUT.mkdir(parents=True, exist_ok=True)
    mv = find_mv()
    # 两种字幕来源: 基础配色版 (make_ass.py) 和逐字特效版 (render_effects.py)
    cands = [SUBS / f"soramimi_{which}.ass", SUBS / "fx" / f"fx_{which}.ass"]
    ass = next((p for p in cands if p.exists()), None)
    if ass is None:
        raise SystemExit(f"ERROR: 找不到字幕, 试过:\n  " + "\n  ".join(str(p) for p in cands))

    timed = json.loads((ROOT / "02_lyrics" / "soramimi_timed.json").read_text(encoding="utf-8"))
    lo, hi = timed[0]["start"], timed[-1]["end"]
    print(f"MV      : {mv.name}")
    print(f"字幕    : {ass.name}  ({len(timed)} 行, {lo:.1f}s - {hi:.1f}s)")

    suffix = which
    if trim > 0:
        ass = shift_ass(ass, ass.parent / f"_shifted_{which}.ass", trim)
        suffix = f"{which}_notrailer"
        print(f"片头裁剪: -{trim:.2f}s   字幕已同步前移 -> 第 1 行 {lo-trim:.2f}s")

    # 成品路径**由参数唯一决定**。曾经压到 dashanghuahuo_soramimi_<配色>.mp4, 而交付件
    # 叫 FINAL_*, 两者不同名 —— 结果作者看的是上一版的 FINAL, 反馈的全是已经修好的问题,
    # 白跑一轮。规则不是"只许有一个文件", 而是"同一个东西不许有两个名字":
    # 版式必须进文件名, 否则五个版式互相覆盖, 又会退回同一个坑。
    lay_tag = f"_{layout}" if layout else ""
    if preview > 0:
        out = OUT / f"FINAL_dashanghuahuo{lay_tag}_{int(preview)}s.mp4"
        if not burn(mv, ass, out, trim=trim, geom=geom, limit=preview):
            return 1
        print(f"\n预览 {int(preview)}s: {out.name}  ({out.stat().st_size/1e6:.1f} MB)")
    else:
        out = OUT / f"FINAL_dashanghuahuo{lay_tag}_full.mp4"
        if not burn(mv, ass, out, trim=trim, geom=geom):
            return 1
        print(f"\n成品: {out.name}  ({out.stat().st_size/1e6:.1f} MB)")

        # 顺手切好 90s 交付版, 免得漏 (流拷贝, 不重编码)
        clip = OUT / f"FINAL_dashanghuahuo{lay_tag}_90s.mp4"
        if cut_clip(out, clip, 0, 90):
            print(f"      {clip.name}  ({clip.stat().st_size/1e6:.1f} MB)")

    # QC 抽帧: 每行中点各一张。裁过片头的话时间要减掉裁剪量
    times = [round(l["start"] + (l["end"] - l["start"]) / 2 - trim, 2) for l in timed]
    frames = grab_qc(out, times, f"full_{suffix}")
    print(f"QC 抽帧: {len(frames)} 张 -> {QC / ('full_' + suffix)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
