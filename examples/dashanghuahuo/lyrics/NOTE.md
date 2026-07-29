# 关于本目录

这里只保留**作者本人创作的空耳歌词**及其对齐结果。

原曲的日文歌词转录、罗马音、音节级时间轴等中间产物**已刻意排除**，
因为那些等同于转载受版权保护的歌词文本。

它们不是复现所必需的 —— 按 ENGINEERING.md §7 跑一遍流水线，
`transcribe_vocals.py` 和 `force_align.py` 会在本地重新生成。

同理，`soramimi_timed.json` 中每个字对应的日文音节串已被剥离，
只保留音节**数量**（`n_ja_syls`），足够复核对齐的疏密程度。

## subs/ 为什么只剩一个 .ass

早先这里放过 4 个配色（cool_cyan / hanabi_pink / ktv_yellow / ice_rainbow）。
前 3 个是旧版 `make_ass.py` 的产物 —— 那一版的配色命名和相邻行让位逻辑都已被
取代（见 ENGINEERING.md §6.13），留着只会让人照抄到已经废弃的写法。

现在只保留当前生成器产出的 `soramimi_ice_rainbow.ass`。想要别的配色不必翻这里，
直接跑：

```bash
python make_ass.py 0-:fire          # 整首火焰
python make_ass.py 0-8:ice 9-:gold  # 分段换挡
```

可用配色见 `src/make_ass.py` 的 `SCHEMES`：
rainbow / ice / fire / gold / cyan / yellow。
