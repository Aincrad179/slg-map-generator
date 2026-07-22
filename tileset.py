# -*- coding: utf-8 -*-
"""
贴图集抽象 (Tileset)
==============================================================================
把「美术素材是什么、哪些瓦片是草地/土路/过渡、瓦片多大、如何写成 Tiled .tsx」
从生成器主逻辑里剥离出来，用一个外部 JSON 描述符驱动。

任意等轴测美术集只要写一份描述符（见 tilesets/terrain.json），生成器即可使用，
不再锁死在某一套素材。地形瓦片本身由 tilegen.py 现画（见 assets/terrain）。

设计约束：
  · 仅用标准库（不引入 PIL / 不触碰全局 random）——保证生成的字节级确定性不受影响。
  · write_tsx() 依描述符输出 Collection-of-Images 等轴测 .tsx + 转角集(WangSet)。

描述符 schema（schema_version=1）:
  name / tile_w / tile_h / orientation
  image: { type:"collection", dir, pattern:"{id:03d}.png", id_base }
  wangset: { name, type, colors:[{name,color},...] }
  terrain:
    ground / road: { ids:[...], wangid }         # ids 元素=int 或 [start,end] 闭区间
    transition:    { "文件号": wangid, ... }        # 有序，保留插入顺序
  obstacle / decoration: { ids:[...] }             # 后续阶段用，暂不写入 .tsx
"""
import os, json


def _expand_ids(spec):
    """把 ids 列表（元素=int 或 [start,end] 闭区间）按列出顺序、升序展开成扁平 list。"""
    out = []
    for item in spec or []:
        if isinstance(item, (list, tuple)):
            start, end = item
            out.extend(range(start, end + 1))
        else:
            out.append(int(item))
    return out


class Tileset:
    """加载一份贴图集描述符，向生成器暴露角色查询 / 路径 / .tsx 导出。"""

    def __init__(self, data, descriptor_path, firstgid=1):
        self._d = data
        self._path = descriptor_path
        self.firstgid = firstgid
        img = data["image"]
        base = os.path.dirname(os.path.abspath(descriptor_path))
        self.image_dir = os.path.normpath(os.path.join(base, img["dir"]))
        self.pattern = img.get("pattern", "{id:03d}.png")
        self.id_base = img.get("id_base", 1)

    @classmethod
    def load(cls, descriptor_path, firstgid=1):
        with open(descriptor_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(data, descriptor_path, firstgid)

    # ---- 元数据 ----
    @property
    def name(self):        return self._d["name"]
    @property
    def tile_w(self):      return self._d["tile_w"]
    @property
    def tile_h(self):      return self._d["tile_h"]
    @property
    def orientation(self): return self._d.get("orientation", "isometric")
    @property
    def tilecount(self):   return len(self.all_ids())

    def override_size(self, w, h):
        """覆盖瓦片尺寸（供配方/GUI 调）。write_tsx/write_tmx/预览均据此输出。"""
        self._d["tile_w"] = int(w); self._d["tile_h"] = int(h)

    # ---- 瓦片枚举 ----
    def all_ids(self):
        """扫描 image.dir，返回存在的文件序号（升序）。"""
        ids = []
        for f in os.listdir(self.image_dir):
            if f.lower().endswith(".png"):
                try: ids.append(int(os.path.splitext(f)[0]))
                except ValueError: pass
        return sorted(ids)

    def ground_ids(self):
        return _expand_ids(self._d.get("terrain", {}).get("ground", {}).get("ids"))

    def road_ids(self):
        return _expand_ids(self._d.get("terrain", {}).get("road", {}).get("ids"))

    def transition_map(self):
        """{文件号(int): wangid(str)}，保留描述符插入顺序。"""
        tr = self._d.get("terrain", {}).get("transition", {})
        return {int(k): v for k, v in tr.items()}

    # ---- id / 路径 ----
    def gid_of(self, file_id):
        return self.firstgid + (file_id - self.id_base)

    def image_path(self, file_id):
        return os.path.join(self.image_dir, self.pattern.format(id=file_id))

    def next_firstgid(self):
        """紧随本贴图集之后的 firstgid（供下一个贴图集，如 markers）。"""
        return self.firstgid + self.tilecount

    # ---- 导出 Tiled .tsx（Collection of Images + 转角集/WangSet）----
    def write_tsx(self, out_path):
        ids = self.all_ids()
        rel = os.path.relpath(self.image_dir, os.path.dirname(out_path)).replace("\\", "/")
        terr = self._d.get("terrain", {})
        ground_wid = terr.get("ground", {}).get("wangid", "0,1,0,1,0,1,0,1")
        road_wid   = terr.get("road", {}).get("wangid", "0,2,0,2,0,2,0,2")
        ws = self._d.get("wangset", {})
        tw, th = self.tile_w, self.tile_h

        lines = ['<?xml version="1.0" encoding="UTF-8"?>']
        lines.append(f'<tileset version="1.10" tiledversion="1.11.0" name="{self.name}" '
                     f'tilewidth="{tw}" tileheight="{th}" tilecount="{len(ids)}" columns="0">')
        lines.append(f'  <grid orientation="{self.orientation}" width="1" height="1"/>')
        for fid in ids:
            tid = fid - self.id_base
            src = f"{rel}/{self.pattern.format(id=fid)}"
            lines.append(f'  <tile id="{tid}"><image source="{src}" width="{tw}" height="{th}"/></tile>')
        # 转角集
        lines.append('  <wangsets>')
        lines.append(f'   <wangset name="{ws.get("name", "道路")}" type="{ws.get("type", "corner")}" tile="-1">')
        for col in ws.get("colors", []):
            lines.append(f'    <wangcolor name="{col["name"]}" color="{col["color"]}" tile="-1" probability="1"/>')
        for fid in self.ground_ids():
            lines.append(f'    <wangtile tileid="{fid - self.id_base}" wangid="{ground_wid}"/>')
        for fid in self.road_ids():
            lines.append(f'    <wangtile tileid="{fid - self.id_base}" wangid="{road_wid}"/>')
        for fid, wid in self.transition_map().items():
            lines.append(f'    <wangtile tileid="{fid - self.id_base}" wangid="{wid}"/>')
        lines.append('   </wangset>')
        lines.append('  </wangsets>')
        lines.append('</tileset>')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return out_path
