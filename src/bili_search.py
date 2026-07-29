#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""B 站视频检索 — 自实现 WBI 签名版。

为什么不用 yt-dlp 的 bilisearch:
    yt-dlp 的 BilibiliSearchIE 直接打 /x/web-interface/search/type, 既不带 buvid3
    cookie 也不做 WBI 签名 -> B 站返回 HTTP 412 Precondition Failed。
    (实测 2026-07-29 复现)

本脚本做对了三件事:
    1. 先 GET 主页 + /x/frontend/finger/spi 拿到 buvid3 / buvid4 cookie
    2. 从 /x/web-interface/nav 取 img_key / sub_key, 按固定置换表算 mixin_key
    3. 对 query 做 WBI 签名 (w_rid = md5(sorted_query + mixin_key)), 打 wbi 端点

用法:
    python bili_search.py "打上花火 DAOKO 米津玄師" [页数]
输出:
    00_source/bilibili_candidates.json + 终端候选表
"""
import hashlib
import io
import json
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import requests

# B 站 WBI mixin key 置换表 (前 32 位有效)
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

OUT = Path(__file__).resolve().parent.parent / "00_source" / "bilibili_candidates.json"
OUT.parent.mkdir(parents=True, exist_ok=True)


def get_mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def enc_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    mixin_key = get_mixin_key(img_key + sub_key)
    params = dict(params)
    params["wts"] = int(time.time())
    # B 站要求: 按 key 排序, 且 value 过滤掉 !'()* 这些字符
    params = {k: "".join(c for c in str(v) if c not in "!'()*")
              for k, v in sorted(params.items())}
    query = urllib.parse.urlencode(params)
    params["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return params


def bootstrap_session() -> tuple:
    """拿 buvid cookie + WBI 密钥。返回 (session, img_key, sub_key)。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    # 1) 主页种 cookie
    s.get("https://www.bilibili.com/", timeout=20)
    # 2) 显式补 buvid3/buvid4 (主页有时不下发)
    spi = s.get("https://api.bilibili.com/x/frontend/finger/spi", timeout=20).json()
    if spi.get("code") == 0:
        d = spi["data"]
        s.cookies.set("buvid3", d.get("b_3", ""), domain=".bilibili.com")
        s.cookies.set("buvid4", d.get("b_4", ""), domain=".bilibili.com")
    # 3) WBI 密钥
    nav = s.get("https://api.bilibili.com/x/web-interface/nav", timeout=20).json()
    wbi = nav["data"]["wbi_img"]
    img_key = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub_key = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    print(f"[bootstrap] buvid3={s.cookies.get('buvid3', '')[:16]}...  "
          f"img_key={img_key[:12]}...  sub_key={sub_key[:12]}...")
    return s, img_key, sub_key


def search(keyword: str, pages: int = 2) -> list:
    s, img_key, sub_key = bootstrap_session()
    out = []
    for page in range(1, pages + 1):
        params = enc_wbi(
            {"search_type": "video", "keyword": keyword, "page": page, "order": "totalrank"},
            img_key, sub_key,
        )
        r = s.get("https://api.bilibili.com/x/web-interface/wbi/search/type",
                  params=params, timeout=25)
        j = r.json()
        if j.get("code") != 0:
            print(f"[page {page}] API code={j.get('code')} msg={j.get('message')}")
            break
        out.extend(j["data"].get("result") or [])
        time.sleep(0.8)  # 礼貌限速
    return out


def clean(t: str) -> str:
    return re.sub(r"<[^>]+>", "", t or "").strip()


def dur_to_sec(d: str) -> int:
    if not d:
        return 0
    parts = [int(x) for x in d.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    return parts[0] * 3600 + parts[1] * 60 + parts[2]


def main():
    kw = sys.argv[1] if len(sys.argv) > 1 else "打上花火 DAOKO 米津玄師"
    pages = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    res = search(kw, pages)
    print(f"\nquery   : {kw}\nreturned: {len(res)} entries\n")

    rows = []
    for i, e in enumerate(res, 1):
        rows.append({
            "n": i,
            "bv": e.get("bvid", "?"),
            "aid": e.get("aid"),
            "title": clean(e.get("title")),
            "uploader": e.get("author", "?"),
            "duration": e.get("duration", ""),
            "duration_sec": dur_to_sec(e.get("duration", "")),
            "views": e.get("play", 0),
            "danmaku": e.get("video_review", 0),
            "pubdate": time.strftime("%Y-%m-%d", time.localtime(e.get("pubdate", 0))),
            "desc": clean(e.get("description"))[:120],
            "url": f"https://www.bilibili.com/video/{e.get('bvid','')}",
        })

    print(f"{'#':>2}  {'BV':<14} {'时长':>7} {'播放':>10} {'发布':<11} {'UP主':<16} 标题")
    print("-" * 132)
    for r in rows:
        print(f"{r['n']:>2}  {r['bv']:<14} {r['duration']:>7} {r['views']:>10,} "
              f"{r['pubdate']:<11} {r['uploader'][:16]:<16} {r['title'][:52]}")

    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nsaved -> {OUT}  ({len(rows)} candidates)")


if __name__ == "__main__":
    main()
