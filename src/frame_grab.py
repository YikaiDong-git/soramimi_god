#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""候选 MV 抽帧 — 直取 CDN 流地址, 由 ffmpeg 自行 seek。

为什么不用 yt-dlp --download-sections:
    实测 (2026-07-29) 即使传了 ffmpeg_location, yt-dlp 仍报
    "You have requested downloading the video partially, but ffmpeg is not installed"。
    绕开它: extract_info 拿 format['url'] + http_headers, 交给 ffmpeg -ss 直接抽。
    更快 (不落盘整段) 且环节更少。

抽帧时机: 选在确定有人声的时间点 (副歌/主歌), 而不是机械的 25/50/75%,
    否则可能抽到间奏 —— 间奏没字幕, 会把有硬字幕的片子误判成干净的。

用法: python frame_grab.py
输出: 05_qc/probe/<BV>_t<sec>.jpg
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
FF = "C:/Users/59827/karaoke/tools/ffmpeg/bin/ffmpeg.exe"
PROBE = ROOT / "05_qc" / "probe"
PROBE.mkdir(parents=True, exist_ok=True)

BVS = [
    "BV1MtgU6yEyY", "BV1L441167fv", "BV1F8411G7TJ", "BV1ZrNV6JEqP",
    "BV11a3F66Egn", "BV1VkdnYcEH1", "BV1au3z6fEnm", "BV1bhFHewENE",
]
# 打上花火 结构: ~20s 前奏, 主歌 25-75s, 副歌约 90-120s, 二段 150-190s
SAMPLE_TS = [35, 100, 165]


def best_video_format(info):
    """挑 H.264 最高分辨率的纯视频流 (av01/hevc 有些 ffmpeg 构建 seek 慢)。"""
    vids = [f for f in info.get("formats", [])
            if f.get("vcodec") and f["vcodec"] != "none" and f.get("url")]
    if not vids:
        return None
    avc = [f for f in vids if (f.get("vcodec") or "").startswith("avc")]
    pool = avc or vids
    return max(pool, key=lambda f: (f.get("height") or 0, f.get("tbr") or 0))


def grab(bv):
    url = f"https://www.bilibili.com/video/{bv}"
    with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
        info = ydl.extract_info(url, download=False)
    f = best_video_format(info)
    if not f:
        print(f"  {bv}: no video format")
        return []

    hdrs = f.get("http_headers") or {}
    hdrs.setdefault("Referer", url)
    header_blob = "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())

    print(f"  stream: {f.get('height')}p {f.get('vcodec','')[:10]} tbr={f.get('tbr')}")
    made = []
    for t in SAMPLE_TS:
        out = PROBE / f"{bv}_t{t}.jpg"
        cmd = [FF, "-y", "-loglevel", "error",
               "-headers", header_blob,
               "-ss", str(t), "-i", f["url"],
               "-frames:v", "1", "-q:v", "3",
               "-vf", "scale=960:-2", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if out.exists() and out.stat().st_size > 2000:
            print(f"    t={t:>3}s -> {out.name} ({out.stat().st_size//1024} KB)")
            made.append(str(out))
        else:
            print(f"    t={t:>3}s FAILED rc={r.returncode} {r.stderr.strip()[:160]}")
    return made


def main():
    meta_path = ROOT / "00_source" / "candidate_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else []
    by_bv = {m["bv"]: m for m in meta}

    for bv in BVS:
        title = by_bv.get(bv, {}).get("title", "?")
        print(f"\n=== {bv}  {title} ===")
        frames = grab(bv)
        if bv in by_bv:
            by_bv[bv]["frames"] = frames

    meta_path.write_text(json.dumps(list(by_bv.values()), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    print(f"\nframes in {PROBE}")


if __name__ == "__main__":
    main()
