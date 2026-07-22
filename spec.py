# -*- coding: utf-8 -*-
"""
地图配方 (Recipe / MapSpec)
==============================================================================
把「一张地图的设计」从代码与 config.py 里抽出来，用一份外部 JSON 配方描述：
阵营数、城池金字塔(rings)、各城池类型的数据(尺寸/城门/颜色)、布局参数、贴图集。

一款游戏 = 一份 recipes/*.json。换游戏只需换配方文件，不改代码。

引擎语义角色（中心/关卡/出生）默认用中文名，可在 recipe 的 `roles` 里改名：
  roles: { "center": "中心城", "gate": "关城", "spawn": "出生城" }

配方 schema（schema_version=1）:
  name / factions / seed / tileset(相对 mapgen 根) / topology(布局拓扑,默认 radial)
  tile_w / tile_h(可选：覆盖贴图集描述符的瓦片尺寸)
  layout: { ring_gap, spawn_margin, road_width, road_style, cross_links, random_layout, edge_margin, max_bends, mirror }
  rings:  [ {type, count}, ... ]            # 城池金字塔，从内到外
  city_types: { 名称: {size:[w,h], gate_count, color:[r,g,b]}, ... }  # 有序
  roles:  { center, gate, spawn }           # 可选，语义角色→类型名
"""
import json


class CityType:
    def __init__(self, name, d):
        self.name = name
        self.size = tuple(d["size"])
        self.gate_count = d.get("gate_count", 0)
        self.color = tuple(d.get("color", [150, 150, 150]))


class Recipe:
    def __init__(self, d, path=None):
        self.path = path
        self.name = d.get("name", "map")
        self.factions = d["factions"]
        self.tileset = d.get("tileset")               # 相对 mapgen 根的贴图集描述符路径
        self.seed = d.get("seed", 0)
        self.topology = d.get("topology", "radial")   # 布局拓扑(engine.py)：默认 radial=N重径向对称
        self.graph = d.get("graph")                    # topology=graph 用：内联拓扑图 {nodes,edges}
        self.graph_file = d.get("graph_file")          # 或外部设计文件路径(相对 mapgen 根)
        self.constraints = d.get("constraints")        # 启用的约束键列表(constraints.py)；缺省 None=全开
        self.tile_w = d.get("tile_w")                  # 瓦片尺寸覆盖(缺省 None=用贴图集描述符的值)
        self.tile_h = d.get("tile_h")
        lo = d.get("layout", {})
        self.ring_gap = lo.get("ring_gap", 6)
        self.spawn_margin = lo.get("spawn_margin", 4)
        self.road_width = lo.get("road_width", 2)
        self.road_style = lo.get("road_style", "smooth")
        self.cross_links = lo.get("cross_links", True)
        self.random_layout = lo.get("random_layout", True)
        self.edge_margin = lo.get("edge_margin", 6)   # 出生城离地图边缘的格数（四周留白）
        self.max_bends = lo.get("max_bends", 3)       # 每条腿最多拐几个弯（1=旧的单弯L形；越大越曲折）
        self.mirror = lo.get("mirror", True)          # 允许整体镜像变换（增加另一种手性/朝向）
        self.mirror_arc = lo.get("mirror_arc", 150.0) # mirror 拓扑的扇形张角(度)，仅 topology=mirror 用
        self.rings = [(r["type"], r["count"]) for r in d.get("rings", [])]
        # city_types 保留 JSON 插入顺序（决定标记贴图 gid 顺序）
        self.city_types = {name: CityType(name, cd) for name, cd in d.get("city_types", {}).items()}
        roles = d.get("roles", {})
        self.role_center = roles.get("center", "中心城")
        self.role_gate = roles.get("gate", "关城")
        self.role_spawn = roles.get("spawn", "出生城")

    # ---- 城池类型数据查询（未知类型给安全默认）----
    @property
    def marker_types(self):
        return list(self.city_types.keys())

    def _ct(self, t):
        return self.city_types.get(t)

    def size_of(self, t):
        ct = self._ct(t); return ct.size if ct else (1, 1)

    def gate_of(self, t):
        ct = self._ct(t); return ct.gate_count if ct else 0

    def color_of(self, t):
        ct = self._ct(t); return ct.color if ct else (150, 150, 150)

    def max_city_dim(self):
        return max((max(ct.size) for ct in self.city_types.values()), default=1)


def load_recipe(path):
    with open(path, "r", encoding="utf-8") as f:
        d = json.load(f)
    return Recipe(d, path)
