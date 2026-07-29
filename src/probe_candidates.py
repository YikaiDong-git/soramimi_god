#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""候选 MV 实测: 拉元数据 + 抽帧, 用于人工判断硬字幕/画面质量。

为什么必须抽帧: B 站 metadata 里没有任何字段能说明视频"是否内嵌硬字幕"。
标题里写"中日歌词"的一定有, 但没写的也可能有 —— 只能看画面。

阳性对照: 候选表里故意放一个标题明写"(中日歌词)"的, 若检测器看不出它有字幕,
说明抽帧时机或分辨率有问题, 整个筛选不可信。

用法: python probe_candidates.py
输出: 05_qc/probe/<BV>_t<pct>.jpg  +  00_source/candidate_meta.json
"""
import io
import json
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from yt_dlp import YoutubeDL

ROOT = Path(__file__).resolve().parent.parent
FF = Path("C:/Users/59827/karaoke/tools/ffmpeg/bin/ffmpeg.exe")
PROBE_DIR = ROOT / "05_qc" / "probe"
TMP = ROOT / "05_qc" / "_tmp"
PROBE_DIR.mkdir(parents=True, exist_ok=True)
TMP.mkdir(parents=True, exist_ok=True)

# 入选理由写在 note 里, 便于复盘
CANDIDATES = [
    ("BV1MtgU6yEyY", "标题为官方 MUSIC VIDEO 命名, 4:53"),
    ("BV1L441167fv", "网页搜索指向的官方动画 MV(未出现在搜索前40, 直接探)"),
    ("BV1F8411G7TJ", "4K HDR 96/24 HiRes 母带重制, 40万播放"),
    ("BV1ZrNV6JEqP", "无损音质 4K, 4:50"),
    ("BV11a3F66Egn", "4K60FPS 动画 OP, 4:49"),
    ("BV1VkdnYcEH1", "Hi-Res 无损, 21万播放"),
    ("BV1au3z6fEnm", "朴素标题, 4:47"),
    ("BV1bhFHewENE", "★阳性对照: 标题明写(中日歌词), 必定有硬字幕"),
]

PCTS = [0.25, 0.50, 0.75]


def meta(bv):
    url = f"https://www.bilibili.com/video/{bv}"
    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        return ydl.extract_info(url, download=False)


def grab(bv, t, tag):
    """下载 t 秒处的 2 秒片段并抽 1 帧。"""
    url = f"https://www.bilibili.com/video/{bv}"
    seg = TMP / f"{bv}_{tag}.mp4"
    jpg = PROBE_DIR / f"{bv}_t{tag}.jpg"
    if jpg.exists():
        return jpg
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bv*[height<=1080]/bv*/b",
        "outtmpl": str(seg),
        "ffmpeg_location": str(FF.parent),
        "download_ranges": lambda info, ydl: [{"start_time": t, "end_time": t + 2}],
        "force_keyframes_at_cuts": False,
        "overwrites": True,
    }
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
    real = seg if seg.exists() else next(TMP.glob(f"{bv}_{tag}.*"), None)
    if real is None:
        return None
    subprocess.run(
        [str(FF), "-y", "-loglevel", "error", "-i", str(real),
         "-frames:v", "1", "-q:v", "3", str(jpg)],
        check=True,
    )
    real.unlink(missing_ok=True)
    return jpg


def main():
    out = []
    for bv, note in CANDIDATES:
        print(f"\n=== {bv}  ({note}) ===")
        try:
            info = meta(bv)
        except Exception as e:
            print(f"  META FAIL: {type(e).__name__}: {e}")
            out.append({"bv": bv, "note": note, "error": str(e)})
            continue

        fmts = info.get("formats") or []
        heights = sorted({f.get("height") for f in fmts if f.get("height")}, reverse=True)
        fpss = sorted({f.get("fps") for f in fmts if f.get("fps")}, reverse=True)
        vcodecs = sorted({(f.get("vcodec") or "")[:8] for f in fmts if f.get("vcodec") not in (None, "none")})
        abrs = sorted({f.get("abr") for f in fmts if f.get("abr")}, reverse=True)
        dur = info.get("duration") or 0

        rec = {
            "bv": bv, "note": note,
            "title": info.get("title"),
            "uploader": info.get("uploader"),
            "duration": dur,
            "duration_hms": f"{int(dur)//60}:{int(dur)%60:02d}",
            "max_height": heights[0] if heights else None,
            "heights": heights,
            "max_fps": fpss[0] if fpss else None,
            "vcodecs": vcodecs,
            "max_abr": abrs[0] if abrs else None,
            "n_formats": len(fmts),
            "frames": [],
        }
        print(f"  title   : {rec['title']}")
        print(f"  up      : {rec['uploader']}   dur={rec['duration_hms']}")
        print(f"  quality : max {rec['max_height']}p @{rec['max_fps']}fps  codecs={vcodecs}  abr={rec['max_abr']}")

        for p in PCTS:
            t = int(dur * p)
            tag = f"{int(p*100)}"
            try:
                jpg = grab(bv, t, tag)
                if jpg and jpg.exists():
                    rec["frames"].append({"pct": tag, "t": t, "path": str(jpg),
                                          "kb": jpg.stat().st_size // 1024})
                    print(f"  frame   : t={t}s -> {jpg.name} ({jpg.stat().st_size//1024} KB)")
            except Exception as e:
                print(f"  frame FAIL t={t}s: {type(e).__name__}: {e}")
        out.append(rec)

    p = ROOT / "00_source" / "candidate_meta.json"
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {p}")


if __name__ == "__main__":
    main()
