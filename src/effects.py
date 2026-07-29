#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""逐字卡拉OK特效库 —— 32 种，基于 PyonFX 的字体度量做真逐字动画。

为什么需要 PyonFX:
    单纯的 \\kf 扫光只能改颜色。要做"弹出/跳动/旋转/散开"这类动画, 必须知道每个字
    在屏幕上的精确坐标, 才能给它单独发一条带 \\pos 的 Dialogue。PyonFX 用系统字体
    度量算出每个音节的 x/left/width —— 实测 Windows + 微软雅黑 + 中文正常
    (例: '好' x=624.0 w=61.1)。

三段式:
    每个字拆成三条 Dialogue —— pre(未唱) / hit(正在唱) / post(已唱)。
    动画写在 hit 段的 \\t() 里。这是 KFX 的标准做法, 比在单行内塞内联 \\t 可控得多。

锚点:
    统一 \\an5 (中心对齐), 位置由每个特效自己给 (\\pos 或 \\move),
    这样缩放/旋转都以字心为原点, 不会飘。

每个特效签名: fx(c) -> (pre_tags, hit_tags, post_tags)
    c.d  该字演唱时长(ms)   c.i 行内序号   c.n 行内总字数
    c.x  字心 X            c.y 字心 Y
    返回的 tags 必须自带定位 (用 c.at() 生成 \\pos, 或自己写 \\move)。
"""
from __future__ import annotations

from dataclasses import dataclass

# 注意: 本模块是库, 绝不碰 sys.stdout。
# 曾经在这里包过 io.TextIOWrapper(sys.stdout.buffer), 而调用方也包了一层 ——
# 两层 wrapper 套同一个 buffer, 先被 GC 的那层会把 buffer 关掉,
# 结果调用方一 print 就 ValueError: I/O operation on closed file。
# 中文输出统一靠环境变量 PYTHONIOENCODING=utf-8 解决。

# 未唱 / 已唱 / 描边 —— 与 make_ass.py 的 "cyan" 配色一致
C_PRE = r"&H00FFFFFF&"
C_HIT = r"&H00F0C000&"
C_OUT = r"&H00301808&"

LEAD_IN = 400     # ms 整行提前出现
LEAD_OUT = 400    # ms 整行延后消失

EFFECTS = {}
DESC = {}


@dataclass
class Ctx:
    d: int          # 该字演唱时长 ms
    i: int          # 行内序号
    n: int          # 行内字数
    x: float        # 字心 X
    y: float        # 字心 Y

    def at(self, dx=0.0, dy=0.0):
        return rf"\an5\pos({self.x + dx:.1f},{self.y + dy:.1f})"

    def move(self, dx0, dy0, dx1, dy1, t0, t1):
        return (rf"\an5\move({self.x + dx0:.1f},{self.y + dy0:.1f},"
                rf"{self.x + dx1:.1f},{self.y + dy1:.1f},{int(t0)},{int(t1)})")


def fx(name, desc):
    def deco(fn):
        EFFECTS[name] = fn
        DESC[name] = desc
        return fn
    return deco


# ============================== A. 填充 / 基础 ==============================

@fx("01_wipe", "经典扫光：白→青蓝从左到右平滑扫过。最稳，任何背景都不会出错")
def _(c):
    return (c.at() + rf"\1c{C_PRE}", c.at() + rf"\1c{C_HIT}", c.at() + rf"\1c{C_HIT}")


@fx("02_fade", "淡变色：唱到时颜色渐变而非突变，柔和")
def _(c):
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_PRE}\t(0,{c.d},\1c{C_HIT})",
            c.at() + rf"\1c{C_HIT}")


@fx("03_alpha_reveal", "半透明显现：未唱的字半透明，唱到才完全实体化")
def _(c):
    return (c.at() + rf"\1c{C_PRE}\alpha&H90&",
            c.at() + rf"\1c{C_HIT}\alpha&H90&\t(0,{c.d},\alpha&H00&)",
            c.at() + rf"\1c{C_HIT}")


@fx("04_outline_pop", "描边闪：字色不变，只有描边在唱到时爆一下")
def _(c):
    h = max(c.d // 3, 60)
    return (c.at() + rf"\1c{C_PRE}\3c{C_OUT}",
            c.at() + rf"\1c{C_HIT}\3c&H00FFFFFF&\bord9\t(0,{h},\bord4\3c{C_OUT})",
            c.at() + rf"\1c{C_HIT}\3c{C_OUT}")


# ============================== B. 缩放 ==============================

@fx("05_pop", "弹出：放大到 135% 再弹回。最常见的“有精神”效果")
def _(c):
    h = max(c.d // 3, 60)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fscx135\fscy135\t(0,{h},\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


@fx("06_pop_big", "大弹出：放大到 185%，冲击力强，适合副歌高潮")
def _(c):
    h = max(c.d // 2, 90)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fscx185\fscy185\t(0,{h},\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


@fx("07_grow", "越唱越大：唱过的字保持 118%，整行像逐渐鼓起来")
def _(c):
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\t(0,{c.d},\fscx118\fscy118)",
            c.at() + rf"\1c{C_HIT}\fscx118\fscy118")


@fx("08_slam", "砸落：从 210% 缩到 100%，像字砸在屏幕上")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fscx210\fscy210\alpha&H70&"
                     rf"\t(0,{h},\fscx100\fscy100\alpha&H00&)",
            c.at() + rf"\1c{C_HIT}")


@fx("09_squash", "Q弹：先横宽纵扁，再反向拉长，最后回正。橡皮糖手感")
def _(c):
    a, b = max(c.d // 4, 50), max(c.d // 2, 100)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fscx145\fscy68"
                     rf"\t(0,{a},\fscx84\fscy126)\t({a},{b},\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


@fx("10_heartbeat", "心跳：唱到时连着跳两下")
def _(c):
    q = max(c.d // 5, 45)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fscx128\fscy128\t(0,{q},\fscx100\fscy100)"
                     rf"\t({q*2},{q*3},\fscx120\fscy120)\t({q*3},{q*4},\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


# ============================== C. 位移 ==============================

@fx("11_jump", "上跳：唱到时整个字向上弹起再落回")
def _(c):
    h = max(c.d // 2, 70)
    return (c.at() + rf"\1c{C_PRE}",
            c.move(0, 0, 0, -26, 0, h) + rf"\1c{C_HIT}",
            c.at() + rf"\1c{C_HIT}")


@fx("12_drop", "天降：字从上方 70px 落下就位")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}",
            c.move(0, -70, 0, 0, 0, h) + rf"\1c{C_HIT}\alpha&H60&\t(0,{h},\alpha&H00&)",
            c.at() + rf"\1c{C_HIT}")


@fx("13_rise", "升起：字从下方浮上来，像泡泡")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}",
            c.move(0, 55, 0, 0, 0, h) + rf"\1c{C_HIT}\alpha&H70&\t(0,{h},\alpha&H00&)",
            c.at() + rf"\1c{C_HIT}")


@fx("14_slide_l", "左滑入：字从左侧滑进来")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}",
            c.move(-90, 0, 0, 0, 0, h) + rf"\1c{C_HIT}\alpha&H70&\t(0,{h},\alpha&H00&)",
            c.at() + rf"\1c{C_HIT}")


@fx("15_wave", "波浪：唱到的字上下摆一次，整行看起来像水波推过")
def _(c):
    a = max(c.d // 3, 50)
    return (c.at() + rf"\1c{C_PRE}",
            c.move(0, -18, 0, 14, 0, a) + rf"\1c{C_HIT}",
            c.at() + rf"\1c{C_HIT}")


@fx("16_shake", "抖动：唱到时左右快速晃两下")
def _(c):
    q = max(c.d // 6, 30)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\frz3\t(0,{q},\frz-3)\t({q},{q*2},\frz2)"
                     rf"\t({q*2},{q*3},\frz0)",
            c.at() + rf"\1c{C_HIT}")


# ============================== D. 旋转 ==============================

@fx("17_spin", "转一圈：唱到时绕字心旋转 360 度")
def _(c):
    h = max(c.d, 220)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\frz0\t(0,{h},\frz360)",
            c.at() + rf"\1c{C_HIT}")


@fx("18_tilt", "歪头：倾斜 16 度再回正，俏皮")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\frz16\t(0,{h},\frz0)",
            c.at() + rf"\1c{C_HIT}")


@fx("19_flip_x", "上下翻牌：绕横轴 3D 翻转")
def _(c):
    h = max(c.d, 200)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\frx90\t(0,{h},\frx0)",
            c.at() + rf"\1c{C_HIT}")


@fx("20_flip_y", "左右翻牌：绕纵轴 3D 翻转，像翻卡片")
def _(c):
    h = max(c.d, 200)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\fry90\t(0,{h},\fry0)",
            c.at() + rf"\1c{C_HIT}")


@fx("21_spin_pop", "旋转弹出：半圈旋转 + 放大回弹，最花哨的基础组合")
def _(c):
    h = max(c.d, 200)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c{C_HIT}\frz-180\fscx165\fscy165"
                     rf"\t(0,{h},\frz0\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


# ============================== E. 模糊 / 发光 ==============================

@fx("22_glow", "发光：唱到时描边亮起并扩散再收回")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}\3c{C_OUT}",
            c.at() + rf"\1c{C_HIT}\3c&H00FFE060&\blur7\t(0,{h},\blur1\3c{C_OUT})",
            c.at() + rf"\1c{C_HIT}\3c{C_OUT}")


@fx("23_blur_in", "虚→实：从模糊逐渐对焦清晰")
def _(c):
    return (c.at() + rf"\1c{C_PRE}\blur5",
            c.at() + rf"\1c{C_HIT}\blur9\t(0,{c.d},\blur0)",
            c.at() + rf"\1c{C_HIT}\blur0")


@fx("24_neon", "霓虹灯：常驻外发光，唱到时更亮。夜景段很搭")
def _(c):
    h = max(c.d // 2, 80)
    return (c.at() + rf"\1c{C_PRE}\3c&H00402000&\blur3",
            c.at() + rf"\1c{C_HIT}\3c&H00FFC000&\blur11\t(0,{h},\blur4)",
            c.at() + rf"\1c{C_HIT}\3c&H00805000&\blur4")


@fx("25_flash", "闪白：唱到瞬间白光一闪再回到目标色")
def _(c):
    f = max(c.d // 5, 40)
    return (c.at() + rf"\1c{C_PRE}",
            c.at() + rf"\1c&H00FFFFFF&\blur5\t(0,{f},\1c{C_HIT}\blur0)",
            c.at() + rf"\1c{C_HIT}")


# ============================== F. 颜色 ==============================

@fx("26_rainbow", "彩虹：每个字一个色相，整行虹彩渐变")
def _(c):
    t = c.i / max(c.n - 1, 1)
    r, g, b = int(255 * (1 - t)), int(180 + 60 * t), int(120 + 135 * t)
    col = f"&H00{b:02X}{g:02X}{r:02X}&"
    return (c.at() + rf"\1c{C_PRE}", c.at() + rf"\1c{col}", c.at() + rf"\1c{col}")


@fx("27_fire", "火焰：黄→橙→红沿行渐变，配暖描边")
def _(c):
    t = c.i / max(c.n - 1, 1)
    g = int(225 - 170 * t)
    col = f"&H0000{g:02X}FF&"
    return (c.at() + rf"\1c{C_PRE}\3c&H00202020&",
            c.at() + rf"\1c{col}\3c&H00002850&",
            c.at() + rf"\1c{col}\3c&H00002850&")


@fx("28_ice", "寒冰：白→青→蓝沿行渐变，清冷")
def _(c):
    t = c.i / max(c.n - 1, 1)
    r = int(255 - 110 * t)
    g = int(235 - 40 * t)
    col = f"&H00FF{g:02X}{r:02X}&"
    return (c.at() + rf"\1c{C_PRE}", c.at() + rf"\1c{col}", c.at() + rf"\1c{col}")


@fx("29_gold", "鎏金：金色字 + 暖色描边 + 轻微发光，最“正式”")
def _(c):
    h = max(c.d // 2, 70)
    return (c.at() + rf"\1c{C_PRE}\3c&H00202020&",
            c.at() + rf"\1c&H0000D7FF&\3c&H00003A6A&\blur5\t(0,{h},\blur1)",
            c.at() + rf"\1c&H0000D7FF&\3c&H00003A6A&")


# ============================== G. 组合 / 主题 ==============================

@fx("30_pop_glow", "弹出+发光：放大回弹同时描边亮起。综合观感最好")
def _(c):
    h = max(c.d // 2, 70)
    return (c.at() + rf"\1c{C_PRE}\3c{C_OUT}",
            c.at() + rf"\1c{C_HIT}\fscx145\fscy145\3c&H00FFE080&\blur8"
                     rf"\t(0,{h},\fscx100\fscy100\blur1\3c{C_OUT})",
            c.at() + rf"\1c{C_HIT}\3c{C_OUT}")


@fx("31_typewriter", "打字机：未唱的字完全不显示，唱到才蹦出来")
def _(c):
    return (c.at() + r"\alpha&HFF&",
            c.at() + rf"\1c{C_HIT}\alpha&HFF&\fscx60\fscy60"
                     rf"\t(0,70,\alpha&H00&\fscx100\fscy100)",
            c.at() + rf"\1c{C_HIT}")


@fx("32_firework", "烟花炸开：小→炸大发光→收拢。本曲主题定制款")
def _(c):
    a = max(c.d // 4, 50)
    b = max(c.d // 2, 100)
    return (c.at() + rf"\1c{C_PRE}\3c{C_OUT}",
            c.at() + rf"\1c&H00FFFFFF&\fscx55\fscy55\blur0"
                     rf"\t(0,{a},\fscx175\fscy175\blur13\3c&H0060C0FF&)"
                     rf"\t({a},{b},\fscx100\fscy100\blur1\1c{C_HIT}\3c{C_OUT})",
            c.at() + rf"\1c{C_HIT}\3c{C_OUT}")


if __name__ == "__main__":
    print(f"共 {len(EFFECTS)} 种特效\n")
    for k in sorted(EFFECTS):
        print(f"  {k:16s} {DESC[k]}")
