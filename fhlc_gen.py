# -*- coding: utf-8 -*-
"""
烽火连城 地图随机生成器  (路线A：Python生成骨架 → Tiled微调 → 导出给程序)
==============================================================================
运行:  python fhlc_gen.py
产物:
  tilesets/terrain.tsx  —— 地形贴图集（含"道路"转角集/WangSet）
  output/map.tmx        —— 地图文件，用 Tiled 打开微调，再导出 JSON 给程序员
  output/preview.png    —— 预览图，不用装 Tiled 也能立刻看到效果

设计要点（对应策划文档 v3.2）:
  · §7.4 等时约束: 每个阵营从出生城到中心城的行军格数完全相等（本工具按构造保证）
  · §7.3 城门数量: 中心城4 / 大城3 / 小城2 / 关城1，写入城池对象属性
  · §7.1 出生城:  N个阵营各1座，永不可攻打
"""
import os, sys, math, random, xml.sax.saxutils as sx
import config as C
import spec as spec_mod
from tileset import Tileset
import tilegen
from engine import build_map
import constraints as cons_mod
from PIL import Image, ImageDraw, ImageFont

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 一、贴图集 —— 由 tilesets/*.json 描述符驱动（见 tileset.py）
# ============================================================
# 草地/土路/过渡瓦片的角色定义、瓦片尺寸、.tsx 导出全部移入 Tileset 类。
# 生成器通过 generate() 里加载的 ts 对象读取，不再引用任何美术专有常量。

# ============================================================
# 二、拓扑与等时布局 —— 已抽到 engine.py（见 DESIGN.md §10）
# ============================================================
# 布局引擎(放城池/连边/生成腿/uv转网格)与几何 helper(manhattan_path/bfs_grid)现由
# engine.py 的可插拔 Topology 提供；build_map/bfs_grid 在本文件顶部从 engine 导入。
# 按 spec.topology 选拓扑(默认 radial = 原 N 重径向对称)。

def validate_equal_time(mp, spec):
    """已弃用：等距/兵种校验移入 constraints.py（EquidistantSpawns/UnitFairness）。保留空壳以防外部引用。"""
    import constraints as _c
    return _c.EquidistantSpawns().report(mp, spec)

# ============================================================
# 三、导出 Tiled 贴图集 (.tsx)
# ============================================================
# 地形贴图集(.tsx) 的导出已移入 Tileset.write_tsx()（见 tileset.py），
# 由 generate() 里加载的 ts 对象调用。

# ============================================================
# 三B、城池标记贴图（替代对象层：城池用标记瓦片表示，元数据存 cities.json）
# ============================================================
# 城池类型/颜色/尺寸均来自 spec(Recipe)；标记类型顺序 = city_types 顺序（决定 gid）。
def gen_markers(spec, ts):
    """按 spec 的城池类型生成彩色菱形标记贴图（+类型字），供 Tiled 城池层使用。"""
    mdir = os.path.normpath(os.path.join(os.path.dirname(os.path.join(HERE, C.OUT_MARKER_TSX)),
                                         C.MARKER_DIR))
    os.makedirs(mdir, exist_ok=True)
    TW, TH = ts.tile_w, ts.tile_h
    try: font = ImageFont.truetype("msyh.ttc", 36)
    except Exception: font = ImageFont.load_default()
    for t in spec.marker_types:
        im = Image.new("RGBA", (TW, TH), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        col = tuple(spec.color_of(t)) + (235,)
        cxp, cyp = TW//2, TH//2
        d.polygon([(cxp, 2), (TW-2, cyp), (cxp, TH-2), (2, cyp)], fill=col,
                  outline=(0, 0, 0, 255))
        tb = d.textbbox((0, 0), t, font=font)
        d.text((cxp-(tb[2]-tb[0])//2, cyp-(tb[3]-tb[1])//2), t, font=font,
               fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(0, 0, 0, 255))
        im.save(os.path.join(mdir, f"{t}.png"))
    return mdir

def write_marker_tsx(spec, ts):
    mdir = gen_markers(spec, ts)
    types = spec.marker_types
    rel = os.path.relpath(mdir, os.path.dirname(os.path.join(HERE, C.OUT_MARKER_TSX))).replace("\\", "/")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(f'<tileset version="1.10" tiledversion="1.11.0" name="markers" '
                 f'tilewidth="{ts.tile_w}" tileheight="{ts.tile_h}" tilecount="{len(types)}" columns="0">')
    lines.append('  <grid orientation="isometric" width="1" height="1"/>')
    for i, t in enumerate(types):
        lines.append(f'  <tile id="{i}"><image source="{rel}/{t}.png" '
                     f'width="{ts.tile_w}" height="{ts.tile_h}"/></tile>')
    lines.append('</tileset>')
    out = os.path.join(HERE, C.OUT_MARKER_TSX)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out

def write_cities_json(mp, spec):
    """城池元数据（坐标+属性）导出为 JSON，交付程序员（替代对象层）。"""
    import json
    data = []
    for c in mp["cities"]:
        x, y = c["cell"]
        w, h = c.get("size") or spec.size_of(c["type"])
        xs = [cx for cx, cy in c["cells"]]; ys = [cy for cx, cy in c["cells"]]
        data.append({
            "name": c["name"], "type": c["type"], "faction": c["faction"],
            "col": x, "row": y,                       # 城池中心格
            "size": [w, h],                            # 占地宽×高(格)
            "origin": [min(xs), min(ys)],              # 占地左上角格
            "gate_count": spec.gate_of(c["type"]),
        })
    out = os.path.join(HERE, C.OUT_CITIES)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"map_width": mp["W"], "map_height": mp["H"],
                   "center": list(mp["center"]),
                   "cities": data}, f, ensure_ascii=False, indent=2)
    return out

# ============================================================
# 四、导出地图 (.tmx)
# ============================================================
def csv_layer(grid, W, H):
    rows = []
    for r in range(H):
        rows.append(",".join(str(grid[r*W + col]) for col in range(W)))
    return ",\n".join(rows)

def write_tmx(mp, ts, spec):
    W, H = mp["W"], mp["H"]
    tsx_rel = os.path.relpath(os.path.join(HERE, C.OUT_TSX),
                              os.path.dirname(os.path.join(HERE, C.OUT_TMX))).replace("\\", "/")
    mtsx_rel = os.path.relpath(os.path.join(HERE, C.OUT_MARKER_TSX),
                               os.path.dirname(os.path.join(HERE, C.OUT_TMX))).replace("\\", "/")
    markers_firstgid = ts.next_firstgid()           # 地形贴图集之后
    # 地面层：随机草地
    ground = [ts.gid_of(random.choice(ts.ground_ids())) for _ in range(W*H)]
    # 道路层：道路格铺纯土路（宽2格），城池占地留空
    road = [0]*(W*H)
    city_cells = set()
    for c in mp["cities"]:
        city_cells.update(c["cells"])
    for (x, y) in mp["roads"]:
        if 0 <= x < W and 0 <= y < H and (x, y) not in city_cells:
            road[y*W + x] = ts.gid_of(random.choice(ts.road_ids()))
    # 城池层：占地块内每格填标记瓦片（替代对象层）
    cityl = [0]*(W*H)
    marker_types = spec.marker_types
    for c in mp["cities"]:
        gid = markers_firstgid + marker_types.index(c["type"])
        for (x, y) in c["cells"]:
            if 0 <= x < W and 0 <= y < H:
                cityl[y*W + x] = gid

    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append(f'<map version="1.10" tiledversion="1.11.0" orientation="isometric" '
                 f'renderorder="right-down" width="{W}" height="{H}" '
                 f'tilewidth="{ts.tile_w}" tileheight="{ts.tile_h}" infinite="0" nextlayerid="10" nextobjectid="1">')
    lines.append(f'  <tileset firstgid="1" source="{tsx_rel}"/>')
    lines.append(f'  <tileset firstgid="{markers_firstgid}" source="{mtsx_rel}"/>')
    lines.append(f'  <layer id="1" name="地面" width="{W}" height="{H}">')
    lines.append(f'    <data encoding="csv">\n{csv_layer(ground, W, H)}\n</data>')
    lines.append('  </layer>')
    lines.append(f'  <layer id="2" name="道路" width="{W}" height="{H}">')
    lines.append(f'    <data encoding="csv">\n{csv_layer(road, W, H)}\n</data>')
    lines.append('  </layer>')
    lines.append(f'  <layer id="3" name="城池" width="{W}" height="{H}">')
    lines.append(f'    <data encoding="csv">\n{csv_layer(cityl, W, H)}\n</data>')
    lines.append('  </layer>')
    lines.append('</map>')
    out = os.path.join(HERE, C.OUT_TMX)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out

# ============================================================
# 五、预览渲染（Pillow，直接用真实贴图）
# ============================================================
FACTION_COLORS = [(220,60,60),(60,110,220),(60,180,90),(210,170,50),(160,80,200),(50,190,200)]
def render_preview(mp, ts, spec):
    W, H = mp["W"], mp["H"]
    sc = C.PREVIEW_SCALE
    TW, TH = int(ts.tile_w*sc), int(ts.tile_h*sc)
    tw2, th2 = TW//2, TH//2
    off_x = (H-1)*tw2
    cw = (W+H)*tw2 + TW
    ch = (W+H)*th2 + TH*2
    canvas = Image.new("RGBA", (cw, ch), (0,0,0,255))

    cache = {}
    def tile(fid):
        if fid not in cache:
            im = Image.open(ts.image_path(fid)).convert("RGBA")
            cache[fid] = im.resize((TW, TH))
        return cache[fid]

    def screen(x, y):
        return (x - y)*tw2 + off_x, (x + y)*th2

    random.seed(spec.seed)
    ground = {(col,row): random.choice(ts.ground_ids()) for row in range(H) for col in range(W)}
    city_cells = set()
    for c in mp["cities"]: city_cells.update(c["cells"])

    # 地面
    for row in range(H):
        for col in range(W):
            sxp, syp = screen(col, row)
            canvas.alpha_composite(tile(ground[(col,row)]), (int(sxp), int(syp)))
    # 道路
    random.seed(spec.seed+1)
    for (x, y) in sorted(mp["roads"], key=lambda c:(c[1],c[0])):
        if 0<=x<W and 0<=y<H and (x,y) not in city_cells:
            sxp, syp = screen(x, y)
            canvas.alpha_composite(tile(random.choice(ts.road_ids())), (int(sxp), int(syp)))

    # 城池标记（色块菱形+文字，聚焦布局验证）—— 颜色来自 spec；出生城按阵营上色
    draw = ImageDraw.Draw(canvas, "RGBA")
    try: font = ImageFont.truetype("msyh.ttc", max(12, int(30*sc)))
    except Exception: font = ImageFont.load_default()
    def diamond(cx, cy, col):
        draw.polygon([(cx, cy-th2),(cx+tw2, cy),(cx, cy+th2),(cx-tw2, cy)], fill=col)
    for c in sorted(mp["cities"], key=lambda c:(c["cell"][0]+c["cell"][1])):
        if c["type"]==spec.role_spawn:
            fi=int(c["faction"].replace("faction",""))-1; r,g,b=FACTION_COLORS[fi%len(FACTION_COLORS)]; col=(r,g,b,235)
        else:
            r,g,b = spec.color_of(c["type"]); col=(r,g,b,230)
        # 占地块内每格画菱形
        for (x, y) in c["cells"]:
            sxp, syp = screen(x, y)
            ccx, ccy = int(sxp)+tw2, int(syp)+th2
            diamond(ccx, ccy, col)
            draw.polygon([(ccx,ccy-th2),(ccx+tw2,ccy),(ccx,ccy+th2),(ccx-tw2,ccy)], outline=(0,0,0,180), width=1)
        # 占地中心画一次标签
        xs=[cx for cx,cy in c["cells"]]; ys=[cy for cx,cy in c["cells"]]
        mx, my = sum(xs)/len(xs), sum(ys)/len(ys)
        lsx, lsy = screen(mx, my); lcx, lcy = int(lsx)+tw2, int(lsy)+th2
        label=c["name"]; tb=draw.textbbox((0,0),label,font=font)
        draw.text((lcx-(tb[2]-tb[0])//2, lcy-(tb[3]-tb[1])//2), label, fill=(255,255,255,255),
                  font=font, stroke_width=2, stroke_fill=(0,0,0,255))

    bbox = canvas.getbbox()
    if bbox: canvas = canvas.crop(bbox)
    out = os.path.join(HERE, C.OUT_PREVIEW)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    canvas.convert("RGB").save(out)
    return out

# ============================================================
def generate(seed=None, recipe_file=None, recipe=None):
    """生成地图。返回 {seed, report, preview, tmx}。
    recipe : 可选，dict 或 spec.Recipe。给了就直接用它（GUI 参数调试用），不读文件。
    recipe_file : 未给 recipe 时，从该配方文件加载（默认 config.RECIPE_FILE）。
    seed : 非 None 时覆盖 recipe.seed。"""
    if recipe is not None:
        spec = recipe if isinstance(recipe, spec_mod.Recipe) else spec_mod.Recipe(recipe)
    else:
        spec = spec_mod.load_recipe(os.path.join(HERE, recipe_file or C.RECIPE_FILE))
    if seed is not None:
        spec.seed = int(seed)
    lines = []
    def log(s=""):
        lines.append(s); print(s)

    log(f"== {spec.name} 地图生成器 ==")
    log(f"随机种子 SEED = {spec.seed}")
    mp = build_map(spec)
    log(f"网格: {mp['W']}x{mp['H']}  阵营数: {spec.factions}  城池数: {len(mp['cities'])}")
    if mp.get("warnings"):
        log("")
        for w in mp["warnings"]:
            log(f"⚠️ {w}")
    # 逐个启用的约束出报告（等距/兵种/大城平衡…；见 constraints.py）
    for con in cons_mod.enabled_constraints(spec):
        clines, _ok = con.report(mp, spec)
        if clines:
            log("")
            for line in clines:
                log(line)

    ts = Tileset.load(os.path.join(HERE, spec.tileset or C.TILESET_FILE))
    if spec.tile_w and spec.tile_h:
        ts.override_size(spec.tile_w, spec.tile_h)   # 配方/GUI 覆盖瓦片尺寸
    tilegen.build_art(ts.image_dir, size=(ts.tile_w, ts.tile_h))  # 自制瓦片按最终尺寸(缺失/尺寸变了就重画)
    ts.write_tsx(os.path.join(HERE, C.OUT_TSX)); write_marker_tsx(spec, ts)
    tmx = write_tmx(mp, ts, spec); write_cities_json(mp, spec); pv = render_preview(mp, ts, spec)
    log(f"\n[生成完成] 地图:{tmx}")
    log("用 Tiled 打开 map.tmx 微调，或直接看 preview.png。")
    return dict(seed=spec.seed, report="\n".join(lines), preview=pv, tmx=tmx)


def main():
    import sys, random as _r
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg in ("r", "random", "-r", "--random"):
        seed = _r.SystemRandom().randrange(1, 1_000_000)   # 随机种子
    elif arg is not None:
        seed = int(arg)                                     # 指定种子
    else:
        seed = None                                         # 用 recipe 的 seed
    generate(seed)


if __name__ == "__main__":
    main()
