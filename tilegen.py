# -*- coding: utf-8 -*-
"""
自制等轴测地形瓦片生成器 (tilegen)
==============================================================================
用程序**从零画出**等轴测(45°)地形瓦片，替代任何第三方美术素材（避免侵权）。
产出三类瓦片，全部是 205×84 的等轴测菱形，菱形外透明：
  · 草地 (grass)      —— ground 角色，纯草
  · 土路 (dirt)       —— road 角色，纯土
  · 过渡 (transition) —— 草↔土「转角集(WangSet)」瓦片，按角落颜色混合

角落约定（对应 Tiled corner-wangset 的 4 个角）：把菱形按中心分成 4 个屏幕象限，
每象限对应一个角，颜色 1=草地、2=土路：
  右上象限 = TR(wangid idx1)  右下 = BR(idx3)  左下 = BL(idx5)  左上 = TL(idx7)

仅依赖 Pillow；用自带的 Random(固定种子)，**不碰全局 random**，故不影响地图生成的确定性。
命令行：`python tilegen.py`  → 重新生成全部瓦片到 assets/terrain/。
"""
import os
from random import Random
from PIL import Image

TILE_W, TILE_H = 205, 84

# 各角色瓦片的 id 区间（连续、无空档 → gid 计算干净）
# 纯地面/纯道路各只 1 种（方便在 Tiled 里用油漆桶整片填），过渡瓦片供转角集刷草↔土
GRASS_IDS = range(1, 2)      # 1     草地（纯）
DIRT_IDS  = range(2, 3)      # 2     土路（纯）
TRANS_IDS = range(3, 9)      # 3..8  过渡（对应下面 6 条 wangid）

# 过渡瓦片的 wangid（顺序 = 文件号 3..8）；与 tilesets/terrain.json 对应
TRANSITION_WANGIDS = [
    "0,2,0,2,0,1,0,2",   # 3  BL 草
    "0,2,0,1,0,2,0,2",   # 4  BR 草
    "0,2,0,2,0,2,0,1",   # 5  TL 草
    "0,1,0,2,0,2,0,1",   # 6  TR+TL 草
    "0,2,0,1,0,1,0,2",   # 7  BR+BL 草
    "0,1,0,2,0,2,0,2",   # 8  TR 草
]


def _corners_of(wangid):
    """wangid 字符串 → (TR, BR, BL, TL) 四个角的颜色（1=草/2=土）。"""
    p = [int(x) for x in wangid.split(",")]
    return (p[1], p[3], p[5], p[7])


def _shade(kind, rnd):
    """给定地形(1草/2土)返回一个带噪点变化的颜色（含少量高光/阴影/杂点）。"""
    r = rnd.random()
    if kind == 1:  # 草地：基色 #5fa832
        if r < 0.06: return (0x7e, 0xc9, 0x4a)   # 亮叶
        if r < 0.12: return (0x45, 0x82, 0x24)   # 暗影
        if r < 0.55: return (0x5f, 0xa8, 0x32)
        return (0x57, 0x9d, 0x2d)
    else:          # 土路：基色 #c8a064
        if r < 0.06: return (0xdd, 0xba, 0x84)   # 亮砂
        if r < 0.13: return (0xa8, 0x80, 0x4a)   # 暗石
        if r < 0.55: return (0xc8, 0xa0, 0x64)
        return (0xbe, 0x96, 0x5c)


def _quadrant_kind(fx, fy, corners):
    """屏幕象限 → 该角的地形。corners=(TR,BR,BL,TL)。"""
    if fx >= 0:
        return corners[0] if fy < 0 else corners[1]   # 右上 / 右下
    return corners[3] if fy < 0 else corners[2]        # 左上 / 左下


def make_tile(corners, seed, w=None, h=None):
    """画一张等轴测菱形瓦片。corners=(TR,BR,BL,TL) 每个 1=草/2=土。w/h 缺省用模块常量。"""
    w = TILE_W if w is None else int(w)
    h = TILE_H if h is None else int(h)
    rnd = Random(seed)
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    px = img.load()
    cx, cy, hw, hh = w / 2, h / 2, w / 2, h / 2
    mixed = len(set(corners)) > 1        # 是否过渡瓦片（需柔化边界）
    for y in range(h):
        for x in range(w):
            fx = (x + 0.5 - cx) / hw
            fy = (y + 0.5 - cy) / hh
            if abs(fx) + abs(fy) > 1.0:
                continue                  # 菱形外 → 透明
            kind = _quadrant_kind(fx, fy, corners)
            if mixed:
                # 靠近中心两条分界线处做锯齿状随机混合，让草↔土接缝自然
                m = min(abs(fx), abs(fy))
                if m < 0.16 and rnd.random() > m / 0.16:
                    if abs(fx) < abs(fy):        # 近竖线 → 换左右象限
                        kind = _quadrant_kind(-fx, fy, corners)
                    else:                         # 近横线 → 换上下象限
                        kind = _quadrant_kind(fx, -fy, corners)
            px[x, y] = _shade(kind, rnd) + (255,)
    return img


def _tile_specs():
    """返回 [(文件号, corners, seed), ...]：1 草 + 1 土 + 过渡。"""
    specs = [(fid, (1, 1, 1, 1), 1000 + fid) for fid in GRASS_IDS]
    specs += [(fid, (2, 2, 2, 2), 2000 + fid) for fid in DIRT_IDS]
    specs += [(TRANS_IDS[i], _corners_of(w), 3000 + TRANS_IDS[i])
              for i, w in enumerate(TRANSITION_WANGIDS)]
    return specs


def build_art(out_dir, force=False, size=None):
    """生成全部地形瓦片到 out_dir。size=(w,h) 覆盖瓦片尺寸(缺省用模块常量)。
    会清掉不属于当前方案的旧编号 PNG；若已存在瓦片尺寸与目标不符则整批重画。"""
    w, h = (int(size[0]), int(size[1])) if size else (TILE_W, TILE_H)
    os.makedirs(out_dir, exist_ok=True)
    specs = _tile_specs()
    want = {f"{fid:03d}.png" for fid, _, _ in specs}
    existing = {f for f in os.listdir(out_dir) if f.lower().endswith(".png")}
    for f in existing - want:                       # 旧编号残留 → 删除
        os.remove(os.path.join(out_dir, f))
    if not force and (want & existing):             # 尺寸变更检测
        sample = os.path.join(out_dir, sorted(want & existing)[0])
        try:
            if Image.open(sample).size != (w, h):
                force = True
        except Exception:
            force = True
    if not force and not (want - existing):
        return out_dir
    for fid, corners, seed in specs:
        p = os.path.join(out_dir, f"{fid:03d}.png")
        if force or not os.path.exists(p):
            make_tile(corners, seed, w, h).save(p)
    return out_dir


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    d = build_art(os.path.join(here, "assets", "terrain"), force=True)
    print("已生成自制地形瓦片 ->", d)
    print(f"  草地 {GRASS_IDS.start} / 土路 {DIRT_IDS.start} / "
          f"过渡 {TRANS_IDS.start}-{TRANS_IDS.stop-1}")
