#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""build_layout_page.py — 把版式候选汇总成一张可对比、可挑选的 HTML。

为什么不是简单贴图:
    23 个候选两两之间的差别往往只有几十像素的行位, 光看缩略图分不出来。
    所以每张卡片除了截图, 还画一张**版位示意图** —— 从候选定义里的 MarginV /
    geom 直接算出来的色条, 一眼看清"谁在上、谁在下、画面被压掉多少"。
    示意图是算出来的不是画出来的, 改了候选定义它自动跟着变。

图片全部内联成 data URI —— Artifact 的 CSP 禁止任何外链资源。

用法: python build_layout_page.py
输出: 05_qc/layout_options/index.html          (本地看, 引用原分辨率 JPG)
      05_qc/layout_options/artifact.html       (发布用, 图片内联)
"""
import base64
import html
import json
import re
import subprocess
import sys
from pathlib import Path

ARGV = sys.argv[1:]
sys.argv = [sys.argv[0]]
import layout_variants as LV                              # noqa: E402

QC = LV.OUTD
FF = LV.FF
EMBED_W = 1180                 # 内联图宽度 —— 够看清行位, 又不撑爆 16MB 上限
EMBED_Q = 5

ROW_COLOR = {"sora": "var(--accent)", "ruby": "var(--accent-soft)",
             "ja": "var(--ink-dim)", "zh": "var(--warm)"}
ROW_LABEL = {"sora": "空耳", "ruby": "注音", "ja": "日文", "zh": "中译"}


# --------------------------------------------------------------------------
def picture_rect(geom):
    """从 ffmpeg 几何串里解出画面在 1920x1080 画布上的位置。"""
    if not geom:
        return (0, 0, 1920, 1080)
    s = re.search(r"scale=(\d+):(\d+)", geom)
    p = re.search(r"pad=\d+:\d+:(\d+):(\d+)", geom)
    w, h = (int(s.group(1)), int(s.group(2))) if s else (1920, 1080)
    x, y = (int(p.group(1)), int(p.group(2))) if p else (0, 0)
    return (x, y, w, h)


def rows_of(v):
    """列出这个候选画了哪些文字行 -> [(kind, y_top, height)]  (1080 坐标系)"""
    out = []
    so = v.get("sora", {})
    fs = so.get("fs", LV.M.FONT_SIZE)
    h = fs * 1.26
    out.append(("sora", 1080 - so.get("mv", LV.BASE_MV) - h, h))
    if v.get("ruby"):
        r = v["ruby"]
        out.append(("ruby", 1080 - r["mv"] - r["size"] * 1.26, r["size"] * 1.26))
    for kind in ("ja", "zh"):
        c = v.get(kind)
        if not c:
            continue
        hh = c["size"] * 1.26
        y = c["mv"] if c["an"] == 8 else 1080 - c["mv"] - hh
        out.append((kind, y, hh))
        if v.get("merge"):
            break
    return out


def schematic(v):
    """一张 16:9 版位示意图 (inline SVG)。"""
    px, py, pw, ph = picture_rect(v.get("geom"))
    k = 240 / 1920                                        # 缩放到 240x135
    parts = [f'<svg class="sch" viewBox="0 0 240 135" role="img" '
             f'aria-label="{v["key"]} 版位示意">',
             '<rect x="0" y="0" width="240" height="135" class="sch-bg"/>',
             f'<rect x="{px*k:.1f}" y="{py*k:.1f}" width="{pw*k:.1f}" '
             f'height="{ph*k:.1f}" class="sch-pic"/>']
    if v.get("band"):
        y, hh, _, _ = v["band"]
        parts.append(f'<rect x="0" y="{y*k:.1f}" width="240" height="{hh*k:.1f}" '
                     f'class="sch-band"/>')
    for kind, y, hh in rows_of(v):
        parts.append(f'<rect x="{(v.get("sora",{}).get("ml",60))*k:.1f}" '
                     f'y="{y*k:.1f}" '
                     f'width="{(1920 - v.get("sora",{}).get("ml",60) - v.get("sora",{}).get("mr",60))*k:.1f}" '
                     f'height="{max(hh*k,2.2):.1f}" rx="1" '
                     f'fill="{ROW_COLOR[kind]}" opacity="{0.95 if kind=="sora" else 0.62}"/>')
    parts.append("</svg>")
    return "".join(parts)


def metrics(v):
    """给每个候选算三个可比的硬指标。"""
    px, py, pw, ph = picture_rect(v.get("geom"))
    area = pw * ph / (1920 * 1080)
    rows = rows_of(v)
    # 遮挡 = 各行**自身高度**落在画面内的部分之和。
    # 不能用"最上一行到最下一行"的包围盒 —— 顶部一行 + 底部一行会算成压住了 88%,
    # 而中间那一大片画面其实完全没被碰到。
    # 左右分栏时文字在画面**旁边**, 不是压在上面, 所以横向不重叠就不算遮挡。
    so = v.get("sora", {})
    rx0, rx1 = so.get("ml", 60), 1920 - so.get("mr", 60)
    if min(rx1, px + pw) - max(rx0, px) <= 0:
        occl = 0.0
    else:
        occl = sum(max(min(y + h, py + ph) - max(y, py), 0.0) for _, y, h in rows) / ph
    return [("画面面积", f"{area*100:.0f}%", area >= 0.99),
            ("遮挡画面", "无" if occl < 0.005 else f"{occl*100:.0f}%", occl < 0.005),
            ("文字行数", str(len(rows)), True)]


def data_uri(path):
    small = QC / ("_emb_" + path.name)
    subprocess.run([FF, "-y", "-loglevel", "error", "-i", str(path),
                    "-vf", f"scale={EMBED_W}:-2", "-q:v", str(EMBED_Q), str(small)],
                   check=True)
    b = small.read_bytes()
    small.unlink()
    return "data:image/jpeg;base64," + base64.b64encode(b).decode(), len(b)


# --------------------------------------------------------------------------
CSS = """
*,*::before,*::after{box-sizing:border-box}
:root{
  --ground:#141619; --surface:#1B1E23; --surface-2:#23272E; --line:#2E333B;
  --ink:#E9EBEE; --ink-dim:#98A0AB; --accent:#7FD4DC; --accent-soft:#4E8E96;
  --warm:#E9A63C; --good:#6FBF8B; --shadow:0 1px 0 rgba(255,255,255,.03);
}
@media (prefers-color-scheme: light){
  :root{
    --ground:#F7F7F5; --surface:#FFF; --surface-2:#EFF0ED; --line:#DFE0DC;
    --ink:#191C20; --ink-dim:#626973; --accent:#12727D; --accent-soft:#7FB6BC;
    --warm:#A2651A; --good:#2F7D50; --shadow:0 1px 2px rgba(0,0,0,.05);
  }
}
:root[data-theme="dark"]{
  --ground:#141619; --surface:#1B1E23; --surface-2:#23272E; --line:#2E333B;
  --ink:#E9EBEE; --ink-dim:#98A0AB; --accent:#7FD4DC; --accent-soft:#4E8E96;
  --warm:#E9A63C; --good:#6FBF8B; --shadow:0 1px 0 rgba(255,255,255,.03);
}
:root[data-theme="light"]{
  --ground:#F7F7F5; --surface:#FFF; --surface-2:#EFF0ED; --line:#DFE0DC;
  --ink:#191C20; --ink-dim:#626973; --accent:#12727D; --accent-soft:#7FB6BC;
  --warm:#A2651A; --good:#2F7D50; --shadow:0 1px 2px rgba(0,0,0,.05);
}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:system-ui,"Segoe UI","Microsoft YaHei",sans-serif;
  font-size:15px; line-height:1.65; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1240px; margin:0 auto; padding:0 24px 96px}
code,.mono{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-variant-numeric:tabular-nums}

/* ---- header ---- */
header{padding:64px 0 28px; border-bottom:1px solid var(--line)}
.eyebrow{font-size:11px; letter-spacing:.19em; text-transform:uppercase;
  color:var(--accent); font-weight:650; margin:0 0 14px}
h1{margin:0 0 12px; font-size:clamp(28px,4vw,42px); line-height:1.12;
  letter-spacing:-.022em; font-weight:750; text-wrap:balance}
.lede{margin:0; max-width:62ch; color:var(--ink-dim); font-size:16px}

.note{margin-top:26px; padding:15px 18px; border-radius:8px;
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--warm); font-size:14px; max-width:74ch}
.note b{color:var(--ink)}

/* ---- sticky controls ---- */
.bar{position:sticky; top:0; z-index:20; background:var(--ground);
  border-bottom:1px solid var(--line); padding:12px 0; margin-bottom:34px}
.bar .wrap{padding-bottom:0; display:flex; gap:20px; align-items:center;
  flex-wrap:wrap}
.seg{display:inline-flex; border:1px solid var(--line); border-radius:7px;
  overflow:hidden; background:var(--surface)}
.seg button{appearance:none; border:0; background:transparent; cursor:pointer;
  color:var(--ink-dim); padding:6px 14px; font:inherit; font-size:13px}
.seg button[aria-pressed="true"]{background:var(--surface-2); color:var(--ink);
  font-weight:620}
.seg button:focus-visible{outline:2px solid var(--accent); outline-offset:-2px}
.jump{display:flex; gap:4px; flex-wrap:wrap; margin-left:auto}
.jump a{font-size:12.5px; color:var(--ink-dim); text-decoration:none;
  padding:5px 9px; border-radius:6px}
.jump a:hover{background:var(--surface-2); color:var(--ink)}
.ctl-label{font-size:11px; letter-spacing:.14em; text-transform:uppercase;
  color:var(--ink-dim); font-weight:600}

/* ---- legend ---- */
.legend{display:flex; gap:18px; flex-wrap:wrap; font-size:12.5px;
  color:var(--ink-dim); margin:0 0 30px}
.legend span{display:inline-flex; align-items:center; gap:7px}
.sw{width:16px; height:8px; border-radius:2px; display:inline-block}

/* ---- groups ---- */
h2{margin:52px 0 6px; font-size:19px; letter-spacing:-.01em; font-weight:700;
  scroll-margin-top:74px}
.gsub{margin:0 0 22px; color:var(--ink-dim); font-size:14px; max-width:70ch}

/* ---- card ---- */
.card{background:var(--surface); border:1px solid var(--line);
  border-radius:11px; overflow:hidden; margin-bottom:22px; box-shadow:var(--shadow)}
.card.pick{border-color:var(--accent)}
.chead{display:flex; gap:14px; align-items:baseline; padding:16px 20px 13px;
  border-bottom:1px solid var(--line); flex-wrap:wrap}
.key{font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-size:12px; font-weight:700; letter-spacing:.06em; color:var(--ground);
  background:var(--accent); padding:3px 8px; border-radius:5px}
.card.pick .key{background:var(--warm)}
.cname{font-size:16.5px; font-weight:650; letter-spacing:-.005em}
.tag{font-size:11px; letter-spacing:.12em; text-transform:uppercase;
  color:var(--warm); font-weight:700; border:1px solid var(--warm);
  padding:2px 7px; border-radius:20px}
.cbody{display:grid; grid-template-columns:264px 1fr; gap:0}
@media (max-width:880px){.cbody{grid-template-columns:1fr}}
.side{padding:18px 20px; border-right:1px solid var(--line);
  display:flex; flex-direction:column; gap:14px}
@media (max-width:880px){.side{border-right:0; border-bottom:1px solid var(--line)}}
.sch{width:100%; height:auto; border-radius:5px; display:block}
.sch-bg{fill:var(--surface-2)}
.sch-pic{fill:var(--accent); opacity:.10}
.sch-band{fill:var(--ink); opacity:.30}
.desc{font-size:13.5px; color:var(--ink-dim); margin:0}
.mx{display:flex; flex-direction:column; gap:5px; margin:0; font-size:12.5px}
.mx div{display:flex; justify-content:space-between; gap:10px}
.mx dt{color:var(--ink-dim)}
.mx dd{margin:0; font-family:ui-monospace,"Cascadia Mono",Consolas,monospace;
  font-variant-numeric:tabular-nums; font-weight:600}
.mx dd.ok{color:var(--good)} .mx dd.no{color:var(--warm)}
.shot{background:#000; display:block; position:relative}
.shot img{width:100%; height:auto; display:block}
.shot img[hidden]{display:none}

footer{margin-top:64px; padding-top:26px; border-top:1px solid var(--line);
  color:var(--ink-dim); font-size:13.5px}
footer pre{background:var(--surface); border:1px solid var(--line);
  border-radius:8px; padding:14px 16px; overflow-x:auto; font-size:12.5px;
  line-height:1.6; color:var(--ink)}
footer h3{font-size:14px; margin:26px 0 8px; color:var(--ink); font-weight:650}
@media (prefers-reduced-motion:no-preference){
  .card{transition:border-color .15s ease}
}
"""

JS = """
const btns=[...document.querySelectorAll('.seg button[data-shot]')];
btns.forEach(b=>b.addEventListener('click',()=>{
  const s=b.dataset.shot;
  btns.forEach(x=>x.setAttribute('aria-pressed', x===b));
  document.querySelectorAll('.shot img').forEach(img=>{
    img.hidden = img.dataset.shot !== s;
  });
}));
"""

GROUP_SUB = {
    "A 三行叠压": "画面完全不动, 三行全部压在底部。最省事, 代价是底部约三分之一被文字盖住。",
    "B 左右分栏": "画面缩到左半边, 右边留一整栏放文字。文字空间最充裕, 但画面面积掉得最狠。",
    "C 底部信息带": "画面等比缩小上移, 空出的一条纯色带专门放文字。画面零遮挡, 代价是画幅变小。整体仍是标准 16:9, 不会被播放器加黑边。",
    "D 上下分置": "把参考信息送到画面顶部, 底部只留空耳。遮挡分散到两处, 单块都不厚。",
    "E 逐字注音": "每个空耳字头上直接标出它对应的日文读音。对应关系不用观众自己找 —— 这是唯一能让看不懂日文的人也验证空耳的做法。",
    "F 注音档位": "都基于 E3, 只调注音本身的字号和取色。",
    "Z 诊断": "不是候选。竖线必须落在每个字正中 —— 这张图是用来验证注音层格宽算对了没有, 数值核对结果见页脚。",
}


def build(embed):
    """embed=True -> 图片内联 (发布用); False -> 引用同目录原分辨率 JPG (本地看)。"""
    idx = json.loads((QC / "index.json").read_text(encoding="utf-8"))
    byk = {v["key"]: v for v in LV.VARIANTS}
    total = 0

    groups, order = {}, []
    for e in idx:
        groups.setdefault(e["grp"], []).append(e)
        if e["grp"] not in order:
            order.append(e["grp"])

    nav = "".join(f'<a href="#g{i}">{html.escape(g)}</a>'
                  for i, g in enumerate(order))

    body = []
    for i, g in enumerate(order):
        body.append(f'<h2 id="g{i}">{html.escape(g)}</h2>'
                    f'<p class="gsub">{html.escape(GROUP_SUB.get(g,""))}</p>')
        for e in groups[g]:
            v = byk[e["key"]]
            imgs = []
            for s in e["shots"]:
                tag = s.rsplit("_", 1)[1].split(".")[0]
                if embed:
                    src, n = data_uri(QC / s)
                    total += n
                else:
                    src = s
                imgs.append(f'<img src="{src}" alt="{e["key"]} {tag}" '
                            f'data-shot="{tag}"{"" if tag=="L15" else " hidden"}>')
            mx = "".join(f'<div><dt>{html.escape(k)}</dt>'
                         f'<dd class="{"ok" if ok else "no"}">{html.escape(val)}</dd></div>'
                         for k, val, ok in metrics(v))
            pick = " pick" if "★" in e["name"] else ""
            tag = '<span class="tag">推荐</span>' if pick else ""
            body.append(
                f'<article class="card{pick}">'
                f'<div class="chead"><span class="key">{e["key"]}</span>'
                f'<span class="cname">{html.escape(e["name"].replace("★推荐",""))}</span>{tag}</div>'
                f'<div class="cbody"><div class="side">{schematic(v)}'
                f'<p class="desc">{html.escape(e["desc"])}</p>'
                f'<dl class="mx">{mx}</dl></div>'
                f'<div class="shot">{"".join(imgs)}</div></div></article>')

    legend = "".join(
        f'<span><i class="sw" style="background:{ROW_COLOR[k]}"></i>{ROW_LABEL[k]}</span>'
        for k in ("sora", "ruby", "ja", "zh"))

    page = f"""<title>打上花火 空耳 · 对照版式候选</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>{CSS}</style>
<div class="wrap">
<header>
  <p class="eyebrow">打上花火 · 空耳卡拉OK · 版式选型</p>
  <h1>原文 + 翻译 + 空耳<br>怎么同框摆</h1>
  <p class="lede">23 个候选, 每个都在同一帧真实画面上渲染过 —— 同一句歌词、同一套逐字扫光、
  同一个下划线标注。左边的示意图是从候选定义里的边距值直接算出来的, 不是画的。</p>
  <div class="note"><b>参考行现在是占位文本。</b>
  原曲歌词和译文我没有代你去找 —— 那是受版权保护的文本, 翻译也是它的演绎, 这两样得由你提供
  (或者用一版已发表的译文并署名)。占位不影响挑版式: 每行的<b>字数</b>和每个字的<b>音节数</b>
  都取自真实数据, 所以挤不挤、够不够放, 现在看到的和填真文本之后是同一回事。
  把 <code>ref_ja.txt</code> / <code>ref_zh.txt</code> 放进 <code>02_lyrics/</code> 再跑一遍即可。</div>
</header>
</div>

<div class="bar"><div class="wrap">
  <span class="ctl-label">测试帧</span>
  <div class="seg">
    <button data-shot="L15" aria-pressed="true">L15 · 最长一行 + 下划线</button>
    <button data-shot="L03" aria-pressed="false">L03 · 带着色词</button>
  </div>
  <nav class="jump">{nav}</nav>
</div></div>

<div class="wrap">
<p class="legend">{legend}<span style="color:var(--ink-dim)">
色条 = 该行在画幅里的位置</span></p>
{"".join(body)}

<footer>
<h3>怎么告诉我你的选择</h3>
<p>报候选编号就行, 可以混搭 —— 比如「骨架用 C1, 注音按 F1 那档」。
注音 (E/F 组) 和任何一个骨架都能组合。</p>

<h3>这些图是怎么来的</h3>
<p>空耳主行不是重画的, 是直接调用成品脚本 <code>make_ass.build()</code> 的输出,
只改了图层和边距四个字段 —— 所以你在这里看到的扫光、断点、着色、下划线, 和成片完全一致。</p>
<p>注音层不算绝对坐标: 每一格的前进宽度和主行逐格相等, 两层各自居中, 必然对齐。
对齐做了数值核对 (不是看图) —— L15 / L03 两行共 25 格, <b>最大偏差 0.87px</b>。</p>
<pre>python layout_variants.py            # 全部候选
python layout_variants.py E3 C1      # 只跑指定几个
python check_ruby_align.py           # 注音对齐数值核对
python build_layout_page.py          # 重建本页</pre>
</footer>
</div>
<script>{JS}</script>
"""
    out = QC / ("artifact.html" if embed else "index.html")
    out.write_text(page, encoding="utf-8")
    size = len(page.encode())
    note = f"内联图片 {total/1024/1024:.2f} MB -> " if embed else "引用原图, "
    print(f"  {note}页面 {size/1024/1024:.2f} MB   写出 -> {out.name}")
    if embed and size > 15 * 1024 * 1024:
        print("  !! 超过 Artifact 16MB 上限, 调小 EMBED_W / 提高 EMBED_Q")
        return 1
    return 0


def main():
    return build(embed=False) or build(embed=True)


if __name__ == "__main__":
    sys.exit(main())
