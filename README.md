# 打上花火 空耳卡拉OK — 流水线

把用户手写的中文空耳，逐字对齐到 B 站 MV 的演唱时间轴上，压成带 KTV 逐字变色的成品视频。

## 结论先行：算力放在本地，成果放服务器

`sinfo` 实测 hgcc 全部节点 `GRES=(null)`，**集群没有 GPU**。本地那块 RTX 2070 SUPER (8 GB, sm_75)
是整套系统唯一的 GPU，所以重 ML 全在本地跑，产物同步到
`/beegfs/labs/weinstocklab/projects/ydon268/funny/konger/dashanghuahuo/`。

## 目录

| 目录 | 内容 |
|---|---|
| `00_source/` | B 站候选元数据、下载的 MV |
| `01_stems/` | 抽出的音轨 + BS-RoFormer 分离的人声/伴奏 |
| `02_lyrics/` | 用户空耳、ASR 转录、罗马音、音节时间轴、对齐报告 |
| `03_subs/` | 生成的 `.ass` 字幕（三种配色） |
| `04_output/` | 压制成品 |
| `05_qc/` | 抽帧自检图 |
| `code/` | 本目录 |

## 环境

一次性装在 `C:/Users/59827/karaoke/`：

- `tools/ffmpeg/` — BtbN 静态构建，带 `h264_nvenc`（压制用）
- `tools/ffmpeg-shared71/` — **FFmpeg 7.1 动态库**，torchcodec 专用
  （torchcodec 只支持 FFmpeg 4–8；BtbN 的 `master` 构建是 avcodec-63 = FFmpeg 9，**太新会加载失败**）
- `venv/` — Python 3.12.2 + torch 2.13.0+**cu126**

> **安装顺序有坑**：先装 cu124 torch、再装 `audio-separator[gpu]`，pip 会从默认 PyPI
> 把 torch 覆盖成 CPU 版，torchaudio 还是 CUDA 版 → ABI 不匹配、`libtorchaudio.pyd` 加载崩。
> 正确顺序是先装 audio-separator，**最后**从 cu126 源装 torch 系。
> 选 cu126 而非 cu130 是因为 `onnxruntime-gpu` 是 CUDA 12 系，混用会炸。

## 脚本

按流水线顺序：

| # | 脚本 | 用途 | 用法 |
|---|---|---|---|
| 1 | `bili_search.py` | B 站关键词检索（**自实现 WBI 签名**） | `python bili_search.py "打上花火" 2` |
| 2 | `probe_candidates.py` | 拉候选元数据（清晰度/时长/码率） | `python probe_candidates.py` |
| 3 | `frame_grab.py` | 候选抽帧，**实测有无硬字幕** | `python frame_grab.py` |
| 4 | `separate_vocals.py` | 抽音轨 + BS-RoFormer 分离人声 | `python separate_vocals.py` |
| 5 | `transcribe_vocals.py` | Whisper 转录人声 → 双路罗马音 | `python transcribe_vocals.py` |
| 6 | `force_align.py` | yohane 音节级强制对齐 → 浮点时间轴 | `python force_align.py` |
| 7 | `phonetics.py` | 跨语言音素特征 + 距离（被 8 调用） | `python phonetics.py`（自检） |
| 8 | `soramimi_align.py` | **子序列 DTW**：日文音节 → 空耳汉字 | `python soramimi_align.py` |
| 9 | `make_ass.py` | 滚动扫光 `\kf` + 逐字配色（6 方案，可分段） | `python make_ass.py 0-8:ice 9-:rainbow` |
| 10 | `burn.py` | libass 渲染 + NVENC 压制 + QC 抽帧 | `python burn.py ice_rainbow --trim=2.85` |

可选支路（逐字动画，默认不启用）：

| 脚本 | 用途 | 用法 |
|---|---|---|
| `effects.py` | 32 种逐字动画的定义（库，不单独跑） | `python effects.py` 列表 |
| `render_effects.py` | 为每种特效渲染一段样片供挑选 | `python render_effects.py` |
| `make_mixed.py` | 按行段给不同特效换挡 | `python make_mixed.py` |

对照版式选型（「原文 + 翻译 + 空耳」同框，2026-08-06 加）：

| 脚本 | 用途 | 用法 |
|---|---|---|
| `layout_variants.py` | 渲染 23 个版式候选（各 2 帧）。空耳主行直接复用 `make_ass.build()`，只改 4 个边距字段 | `python layout_variants.py` / `... E3 C1` |
| `measure_metrics.py` | 从 libass 渲染结果**数像素**量排版度量（字形宽 / `\h` / Spacing 位置）；`make_ass` 的常量就是被它证伪的 | `python measure_metrics.py` |
| `check_ruby_align.py` | 注音层逐格对齐的**数值**核对（不是看图），偏差 > 2px 报错 | `python check_ruby_align.py` |
| `build_layout_page.py` | 汇总成可挑选的 HTML：`index.html`（本地原图）+ `artifact.html`（图片内联，可发布） | `python build_layout_page.py` |

参考行（日文原句 / 中文翻译）读 `02_lyrics/ref_ja.txt` 和 `ref_zh.txt`，每行一句、与
空耳 15 行一一对应。**文件缺失时自动落到占位文本**并在画面角上打 `PLACEHOLDER` 标记 ——
占位的每行字数和每格音节数都取自真实数据，所以版面判断不受影响。这两份文本属受版权保护
的原作及其演绎，与其他日文中间产物一样**不进公开仓库**（见 §9 版权边界）。

所有脚本都用 `C:/Users/59827/karaoke/venv/Scripts/python.exe` 跑，且需要
`PYTHONIOENCODING=utf-8`（否则 Windows 控制台 cp1252 会在打印中日文时崩）。

## 各环节的选型依据

| 环节 | 选定 | 为什么不是默认选项 |
|---|---|---|
| B 站搜索 | 自写 WBI 签名检索器 | yt-dlp 的 `bilisearch` 不带 `buvid3` cookie 也不做 WBI 签名 → **HTTP 412**（实测复现） |
| 下载 | yt-dlp | BBDown 已于 2026-05-14 归档停维 |
| 人声分离 | `model_bs_roformer_ep_368_sdr_12.9628` | 包默认是 ep_317。但仓库自己的 `models-scores.json` 在同一批 40 首上实测中位 vocals SDR：**ep_368 = 12.102 > ep_317 = 11.774**。文件名里的 12.9755 是作者训练时自报值 |
| 强制对齐 | yohane + `NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn` | 日文卡拉OK专用微调，缓解默认 MMS_FA "行尾音节被压短"的缺陷 |
| 空耳配对 | 自写子序列 DTW | 无现成工具 |

## 已知坑（都已实测复现，不是道听途说）

1. **yohane 不吃日文。** `normalize_uroman()` 做 `re.sub("([^a-z'\n ])", " ", text)`，
   汉字假名被整个删掉且**不报错**。本地实测：`normalize_uroman('打上花火')` → `''`。
   必须先转罗马音。
2. **yohane 没有 `--output` 参数**，输出路径由输入音频名推导，且 `with_suffix()`
   只剥最后一段 → `x.vocals.wav` 会被当成 stem `x`。所以喂给它的文件名不能带多余的点。
3. **绝不能 `pip install "yohane[cli]"`。** 它的 `pyproject` 用 `[tool.uv.sources]`
   把 `vocal-remover` 指向 Japan7 的 fork，而 pip 不认这个字段，会从 PyPI 装到一个
   同名的无关 stub（v0.0.6，homepage 指向 `pypa/sampleproject`）→ 装完看着正常，运行时 ImportError。
4. **audio-separator OOM 不会大声崩**，只报 "Separation produced no output files"，
   真正的 `torch.OutOfMemoryError` 只在 traceback 里 → 诊断时必须 `--log_level debug`。
5. **`--mdxc_segment_size` 单独给是无效的**，必须同时给 `--mdxc_override_model_segment_size`。
6. **`--model_file_dir` 默认是 POSIX 的 `/tmp/...`**，Windows 上会落到当前盘根目录 → 必须显式传。
7. **transformers 的 ASR pipeline 传文件路径会调裸 `ffmpeg`**，PATH 上没有就 ValueError。
   解法是自己用 soundfile 读成 numpy 数组传进去，整条依赖直接消掉。
8. **libass 找不到字体不会报错**，会静默回退导致中文变方块 → 只看 ffmpeg 返回码不够，**必须抽帧看**。

## 验证过的事实（非估算）

- CUDA：`torch 2.13.0+cu126`，`torch.cuda.is_available()=True`，RTX 2070 SUPER 8.59 GB，sm_75，矩阵乘通过
- 人声分离**真的生效**：前奏 2–15s 和尾奏 285–296s 人声轨 RMS = **0.00000**，主歌/副歌段有能量
- 音素距离自检：真空耳对应（`ha`↔哈、`shi`↔西、`to`↔拖）距离 = 0.000；随机对照 0.41–0.68
- 候选筛选带**阳性对照**（标题明写"中日歌词"的那个），确认检测器能看出硬字幕后，筛选结果才可信
