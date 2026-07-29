#!/usr/bin/env bash
# 把本地产物同步到服务器工作目录 —— 单条 SSH 连接。
#
# 为什么必须打包成一条连接:
#   最初的版本对每个文件开 2 条 ssh (推送 + 校验), 三十几个文件 = 六十多条连接,
#   立刻触发 hgcc 的速率限制:
#       kex_exchange_identification: read: Software caused connection abort
#   全部失败。tar 走管道只用一条连接, 顺带保留目录结构。
#
# 为什么不用 scp / 不直接写 Z: 盘:
#   用户环境是 rclone + sftp 挂载, 并发上传会打断 rclone 的同步。
#   单条 ssh + tar 是最轻的方式。
#
# 用法: bash sync_to_server.sh [--with-video]
#   默认只推轻量产物 (脚本/歌词/时间轴/字幕/报告/元数据)。
#   加 --with-video 连成品 mp4 一起推 (每个约 281 MB, 慢)。

set -u
cd "$(dirname "$0")/.." || exit 1
REMOTE="/beegfs/labs/weinstocklab/projects/ydon268/funny/konger/dashanghuahuo"
WITH_VIDEO="${1:-}"

FILES=()
for pat in code/*.py code/*.md code/*.sh \
           02_lyrics/*.json 02_lyrics/*.txt 02_lyrics/*.md \
           03_subs/*.ass 00_source/*.json; do
  for f in $pat; do [ -f "$f" ] && FILES+=("$f"); done
done

if [ "$WITH_VIDEO" = "--with-video" ]; then
  for f in 04_output/*.mp4; do [ -f "$f" ] && FILES+=("$f"); done
fi

echo "打包 ${#FILES[@]} 个文件:"
printf '  %s\n' "${FILES[@]}"
TOTAL=$(du -cb "${FILES[@]}" 2>/dev/null | tail -1 | cut -f1)
echo "总计 $((TOTAL/1024)) KB"
echo

# 单条 ssh: 传输 + 解包 + 列目录一次做完
tar czf - "${FILES[@]}" | ssh hgcc "mkdir -p '$REMOTE' && tar xzf - -C '$REMOTE' && echo '--- 服务器端 ---' && find '$REMOTE' -type f -printf '%10s  %P\n' | sort -k2"
