#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""BS-RoFormer 人声分离 (audio-separator)。

模型选择依据 (调研 audio_separator/models-scores.json, 2026-07-29):
    包默认是 model_bs_roformer_ep_317_sdr_12.9755.ckpt, 但那个 "12.9755" 是作者
    训练时自报的数字。仓库自己在同一批 40 首曲子上的实测中位 vocals SDR 是:
        ep_368_sdr_12.9628  ->  12.102   <-- 实际更好
        ep_317_sdr_12.9755  ->  11.774
    同架构同大小 (639 MB), 所以直接用 ep_368。

显存 (8 GB 2070 SUPER):
    分块推理, chunk = stft_hop(441) * (dim_t 801 - 1) = 352800 samples = 8.000 s,
    所以 VRAM 与歌曲长度无关。估算峰值 4-6 GB。
    若 OOM: 加 --mdxc_override_model_segment_size --mdxc_segment_size 512 (再不行 256)。
    注意单给 --mdxc_segment_size 是无效的, 必须同时给 override 开关。

坑 (均来自源码):
    - OOM 不会大声崩, 只报 "Separation produced no output files" -> 必须 --log_level debug
    - --model_file_dir 默认是 POSIX 的 /tmp/..., 在 Windows 会落到当前盘根目录 -> 必须显式传
    - 代码里调的是裸 "ffmpeg", 所以 ffmpeg 必须在 PATH 上, 光有绝对路径没用
    - 输出文件名会把模型名在第一个点处截断
"""
import io
import os
import subprocess
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
VENV = Path("C:/Users/59827/karaoke/venv")
FFDIR = Path("C:/Users/59827/karaoke/tools/ffmpeg/bin")
MODEL_DIR = Path("C:/Users/59827/karaoke/models")
MODEL = "model_bs_roformer_ep_368_sdr_12.9628.ckpt"

SRC = ROOT / "00_source"
STEMS = ROOT / "01_stems"


def sh(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd[:6]), "...")
    return subprocess.run(cmd, **kw)


def main():
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    STEMS.mkdir(parents=True, exist_ok=True)

    # ffmpeg 必须在 PATH (audio-separator 调裸 "ffmpeg")
    os.environ["PATH"] = str(FFDIR) + os.pathsep + os.environ["PATH"]

    mv = next((p for p in SRC.glob("*.mp4") if not p.name.endswith(".part")), None)
    if mv is None:
        print(f"ERROR: {SRC} 下没有找到完整的 .mp4")
        return 1
    print(f"source : {mv.name}  ({mv.stat().st_size/1e6:.1f} MB)")

    # 1) 抽音轨为 wav (44.1k stereo) —— 点号安全的文件名, 避免 yohane 的 with_suffix 截断坑
    wav = STEMS / "song.wav"
    if not wav.exists():
        sh([str(FFDIR / "ffmpeg.exe"), "-y", "-loglevel", "error",
            "-i", str(mv), "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            str(wav)], check=True)
    print(f"audio  : {wav.name}  ({wav.stat().st_size/1e6:.1f} MB)")

    # 2) 分离
    sep = VENV / "Scripts" / "audio-separator.exe"
    cmd = [str(sep), str(wav),
           "-m", MODEL,
           "--model_file_dir", str(MODEL_DIR),
           "--output_dir", str(STEMS),
           "--output_format", "WAV",
           "--log_level", "info"]
    r = sh(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout[-3000:] if r.stdout else "")
    if r.returncode != 0:
        print("--- STDERR ---")
        print(r.stderr[-3000:] if r.stderr else "")
        return r.returncode

    print("\n=== 产物 ===")
    for p in sorted(STEMS.glob("*.wav")):
        print(f"  {p.name:60s} {p.stat().st_size/1e6:8.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
