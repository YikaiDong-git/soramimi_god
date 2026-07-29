#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 站候选 MV 检索 — yt-dlp bilisearch 后端。

用法:
    python search_bilibili.py "打上花火 DAOKO 米津玄師" [N]

输出:
    - 终端: 紧凑候选表
    - 文件: 00_source/bilibili_candidates.json (完整元数据)
为什么用 flat-playlist: 只取元数据不触发下载, 一次请求拿全部候选。
"""
import io
import json
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from yt_dlp import YoutubeDL

QUERY = sys.argv[1] if len(sys.argv) > 1 else "打上花火 DAOKO 米津玄師"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 30
OUT = Path(__file__).resolve().parent.parent / "00_source" / "bilibili_candidates.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def hms(sec):
    if not sec:
        return "?"
    sec = int(sec)
    return f"{sec // 60}:{sec % 60:02d}"


def main():
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"bilisearch{N}:{QUERY}", download=False)

    entries = info.get("entries") or []
    print(f"query   : {QUERY}")
    print(f"returned: {len(entries)} entries\n")

    rows = []
    for i, e in enumerate(entries, 1):
        rows.append(
            {
                "n": i,
                "bv": e.get("id") or "?",
                "title": (e.get("title") or "").strip(),
                "uploader": e.get("uploader") or e.get("channel") or "?",
                "duration": e.get("duration"),
                "views": e.get("view_count"),
                "url": e.get("url") or e.get("webpage_url") or "",
            }
        )

    hdr = f"{'#':>2}  {'BV':<14} {'时长':>6} {'播放':>10}  {'UP主':<18} 标题"
    print(hdr)
    print("-" * 130)
    for r in rows:
        v = f"{r['views']:,}" if isinstance(r["views"], int) else "?"
        up = (r["uploader"] or "?")[:18]
        ti = r["title"][:58]
        print(f"{r['n']:>2}  {r['bv']:<14} {hms(r['duration']):>6} {v:>10}  {up:<18} {ti}")

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
