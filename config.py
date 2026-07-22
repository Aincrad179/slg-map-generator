# -*- coding: utf-8 -*-
"""
地图生成器 —— 工具级配置（路径 / 默认值）
=====================================
「一张地图的设计」现由外部配方文件描述：recipes/*.json（见 spec.py）。
本文件只保留工具级设置：用哪份配方、输出到哪里、预览缩放。
策划改地图设计请编辑 recipes/<游戏>.json，而不是这里。
"""

# ---------------- 选用的配方 ----------------
# 一款游戏 = 一份配方。换游戏/换布局只需改这里指向另一份 recipes/*.json。
RECIPE_FILE = "recipes/fhlc.json"      # 当前地图配方（阵营数/城池/布局/贴图集）

# 配方未指定 tileset 时的兜底贴图集描述符（正常情况下由配方的 "tileset" 字段决定）。
TILESET_FILE = "tilesets/terrain.json"

# ---------------- 输出路径 ----------------
OUT_TMX        = "output/map.tmx"        # 生成的地图文件（用 Tiled 打开微调）
OUT_TSX        = "tilesets/terrain.tsx"  # 地形贴图集（含转角集，由程序生成）
OUT_MARKER_TSX = "tilesets/markers.tsx"  # 城池标记贴图集
MARKER_DIR     = "markers"               # 城池标记贴图目录（相对 markers.tsx 所在目录）
OUT_CITIES     = "output/cities.json"    # 城池数据（坐标+属性，交付程序员）
OUT_PREVIEW    = "output/preview.png"    # 预览图（无需 Tiled 即可查看效果）
PREVIEW_SCALE  = 0.35                    # 预览图缩放（1=原始大小；地图大时调小以免图过大）

# ---------------- GUI 默认 ----------------
SEED = 20260707        # 图形界面里预填的默认种子（实际生成时以输入框/命令行/配方为准）
