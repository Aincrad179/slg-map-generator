# -*- coding: utf-8 -*-
"""
烽火连城 / 通用 45° SLG 地图生成器 —— 图形界面（全参数调试版）
=============================================================================
双击「打开生成器.bat」或本文件即可使用。
左侧面板暴露**配方(recipe)的全部可改参数**，方便在图形界面里直接调试：
  · 基本   : 名称 / 阵营数 / 种子 / 贴图集
  · 布局   : 环间距 / 出生尾路 / 路宽 / 路画法 / 辐条同心环 / 种子驱动布局 / 出生城离边格数
  · 城环   : 城池金字塔 rings（可增删行）
  · 城池类型: 每类型 尺寸/城门/颜色（可增删、可选色）
  · 角色   : center/gate/spawn 语义角色→类型名
点「▶ 生成地图」用当前面板参数即时生成（不改磁盘配方）；
「加载配方」把选中的 recipes/*.json 读进面板；「另存配方」把当前面板存成 JSON。
"""
import os, sys, json, glob, threading, random

# pythonw 无控制台，兜底 stdout/stderr，防止 print 报错
if sys.stdout is None: sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None: sys.stderr = open(os.devnull, "w", encoding="utf-8")

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, colorchooser, filedialog
from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C
import fhlc_gen
import engine

ROAD_STYLES = ["smooth", "screen"]
TOPOLOGIES = list(engine.TOPOLOGIES)          # radial / mirror / ...
UI_FONT = ("Microsoft YaHei", 9)
MONO = ("Consolas", 10)


class App:
    def __init__(self, root):
        self.root = root
        root.title("通用 45° SLG 地图生成器 · 全参数调试")

        # 动态行容器
        self.v = {}                 # 标量参数 -> tk 变量
        self.role_v = {}            # 角色 -> tk 变量
        self.ring_rows = []         # [{type,count,frame}]
        self.ct_rows = []           # [{name,w,h,gate,hp,color,frame,swatch}]
        self._photo = None

        # ---------------- 顶部工具条 ----------------
        bar = tk.Frame(root); bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="配方:", font=UI_FONT).pack(side="left")
        self.recipe_var = tk.StringVar(value=C.RECIPE_FILE.replace("\\", "/"))
        self.recipe_cb = ttk.Combobox(bar, textvariable=self.recipe_var, width=22,
                                      values=self._recipe_files())
        self.recipe_cb.pack(side="left", padx=3)
        tk.Button(bar, text="加载配方", command=self.load_selected_recipe).pack(side="left", padx=2)
        tk.Button(bar, text="另存配方…", command=self.save_recipe).pack(side="left", padx=2)
        self.gen_btn = tk.Button(bar, text="▶ 生成地图", command=self.on_generate,
                                 bg="#3a7", fg="white", font=("Microsoft YaHei", 10, "bold"))
        self.gen_btn.pack(side="left", padx=10)
        tk.Button(bar, text="用 Tiled 打开", command=self.open_tiled).pack(side="left", padx=2)
        tk.Button(bar, text="打开输出文件夹", command=self.open_folder).pack(side="left", padx=2)

        # ---------------- 主体：左参数 / 右预览 ----------------
        main = tk.PanedWindow(root, orient="horizontal", sashwidth=6, bg="#ccc")
        main.pack(fill="both", expand=True, padx=6, pady=4)

        left = tk.Frame(main, width=460)
        left.pack_propagate(False)
        main.add(left, minsize=430)
        self._build_params(left)

        right = tk.Frame(main)
        main.add(right, minsize=420)
        self.img_label = tk.Label(right, bg="#222")
        self.img_label.pack(fill="both", expand=True)
        self.txt = scrolledtext.ScrolledText(right, height=12, font=MONO)
        self.txt.pack(fill="x", pady=(4, 0))

        # 初始载入默认配方 + 已有预览
        self.load_recipe_path(os.path.join(HERE, C.RECIPE_FILE), silent=True)
        self.show_existing_preview()

    # ================= 参数面板构建 =================
    def _build_params(self, parent):
        canvas = tk.Canvas(parent, borderwidth=0, highlightthickness=0)
        vsb = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(canvas)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        # 悬停时才接管滚轮，避免抢走预览区
        def _wheel(e): canvas.yview_scroll(int(-e.delta / 120), "units")
        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # ---- 基本 ----
        g = tk.LabelFrame(inner, text="基本", font=UI_FONT, padx=6, pady=4)
        g.pack(fill="x", padx=6, pady=4)
        self._field(g, "名称 name", "name", width=20)
        row = self._field(g, "阵营数 factions", "factions", width=6, spin=(2, 6))
        tk.Label(row, text="(2–6)", font=UI_FONT, fg="#888").pack(side="left")
        row = self._field(g, "种子 seed", "seed", width=12)
        tk.Button(row, text="🎲", command=self.randomize).pack(side="left", padx=2)
        row = self._field(g, "布局拓扑 topology", "topology", width=10, combo=TOPOLOGIES)
        tk.Label(row, text="(mirror=镜像1v1)", font=UI_FONT, fg="#888").pack(side="left")
        self._field(g, "贴图集 tileset", "tileset", width=22)
        row = tk.Frame(g); row.pack(fill="x", pady=1)
        tk.Label(row, text="瓦片尺寸 tile_w×h", width=20, font=UI_FONT, anchor="w").pack(side="left")
        self.v["tile_w"] = tk.StringVar()
        tk.Entry(row, textvariable=self.v["tile_w"], width=6, font=MONO).pack(side="left")
        tk.Label(row, text="×", font=UI_FONT).pack(side="left")
        self.v["tile_h"] = tk.StringVar()
        tk.Entry(row, textvariable=self.v["tile_h"], width=6, font=MONO).pack(side="left")
        tk.Label(row, text="(等轴测,像素)", font=UI_FONT, fg="#888").pack(side="left")

        # ---- 布局 ----
        g = tk.LabelFrame(inner, text="布局 layout", font=UI_FONT, padx=6, pady=4)
        g.pack(fill="x", padx=6, pady=4)
        self._field(g, "环间距 ring_gap", "ring_gap", width=6)
        self._field(g, "出生尾路 spawn_margin", "spawn_margin", width=6)
        self._field(g, "路宽 road_width", "road_width", width=6)
        self._field(g, "路画法 road_style", "road_style", width=10, combo=ROAD_STYLES)
        row = self._field(g, "出生城离边格数 edge_margin", "edge_margin", width=6)
        tk.Label(row, text="(出生城四周留白)", font=UI_FONT, fg="#888").pack(side="left")
        row = self._field(g, "每腿最多弯数 max_bends", "max_bends", width=6)
        tk.Label(row, text="(1=直L; 越大越曲折)", font=UI_FONT, fg="#888").pack(side="left")
        row = self._field(g, "镜像扇角 mirror_arc", "mirror_arc", width=6)
        tk.Label(row, text="(仅 topology=mirror)", font=UI_FONT, fg="#888").pack(side="left")
        self._check(g, "辐条同心环 cross_links", "cross_links")
        self._check(g, "允许镜像 mirror", "mirror")
        self._check(g, "种子驱动布局 random_layout", "random_layout")

        # ---- rings ----
        g = tk.LabelFrame(inner, text="城环 rings（从内到外；最外环=辐条环，count 自动=阵营数）",
                          font=UI_FONT, padx=6, pady=4)
        g.pack(fill="x", padx=6, pady=4)
        hdr = tk.Frame(g); hdr.pack(fill="x")
        tk.Label(hdr, text="类型", width=12, font=UI_FONT, anchor="w").pack(side="left")
        tk.Label(hdr, text="数量", width=6, font=UI_FONT, anchor="w").pack(side="left")
        self.rings_box = tk.Frame(g); self.rings_box.pack(fill="x")
        tk.Button(g, text="＋ 添加环", command=lambda: self.add_ring_row()).pack(anchor="w", pady=2)

        # ---- city_types ----
        g = tk.LabelFrame(inner, text="城池类型 city_types（顺序决定标记 gid）",
                          font=UI_FONT, padx=6, pady=4)
        g.pack(fill="x", padx=6, pady=4)
        hdr = tk.Frame(g); hdr.pack(fill="x")
        for t, w in (("名称", 7), ("宽", 3), ("高", 3), ("门", 3), ("色", 4), ("", 3)):
            tk.Label(hdr, text=t, width=w, font=UI_FONT, anchor="w").pack(side="left")
        self.ct_box = tk.Frame(g); self.ct_box.pack(fill="x")
        tk.Button(g, text="＋ 添加类型", command=lambda: self.add_ct_row()).pack(anchor="w", pady=2)

        # ---- roles ----
        g = tk.LabelFrame(inner, text="语义角色 roles（角色→类型名）", font=UI_FONT, padx=6, pady=4)
        g.pack(fill="x", padx=6, pady=4)
        self._role_combos = []
        for key, label in (("center", "中心 center"), ("gate", "关卡 gate"), ("spawn", "出生 spawn")):
            r = tk.Frame(g); r.pack(fill="x", pady=1)
            tk.Label(r, text=label, width=16, font=UI_FONT, anchor="w").pack(side="left")
            var = tk.StringVar()
            cb = ttk.Combobox(r, textvariable=var, width=12, values=[])
            cb.pack(side="left")
            self.role_v[key] = var
            self._role_combos.append(cb)

    def _field(self, parent, label, key, width=10, spin=None, combo=None):
        r = tk.Frame(parent); r.pack(fill="x", pady=1)
        tk.Label(r, text=label, width=20, font=UI_FONT, anchor="w").pack(side="left")
        var = tk.StringVar()
        if combo is not None:
            ttk.Combobox(r, textvariable=var, width=width, values=combo).pack(side="left")
        elif spin is not None:
            tk.Spinbox(r, from_=spin[0], to=spin[1], textvariable=var, width=width).pack(side="left")
        else:
            tk.Entry(r, textvariable=var, width=width, font=("Consolas", 10)).pack(side="left")
        self.v[key] = var
        return r

    def _check(self, parent, label, key):
        var = tk.BooleanVar()
        tk.Checkbutton(parent, text=label, variable=var, font=UI_FONT,
                       anchor="w").pack(fill="x")
        self.v[key] = var

    # ================= 动态行：rings / city_types =================
    def _ct_names(self):
        return [r["name"].get().strip() for r in self.ct_rows if r["name"].get().strip()]

    def _refresh_type_choices(self):
        names = self._ct_names()
        for r in self.ring_rows:
            r["combo"]["values"] = names
        for cb in getattr(self, "_role_combos", []):
            cb["values"] = names

    def add_ring_row(self, rtype="", count=1):
        fr = tk.Frame(self.rings_box); fr.pack(fill="x", pady=1)
        tvar = tk.StringVar(value=rtype)
        cb = ttk.Combobox(fr, textvariable=tvar, width=11, values=self._ct_names())
        cb.pack(side="left")
        cvar = tk.StringVar(value=str(count))
        tk.Spinbox(fr, from_=1, to=99, textvariable=cvar, width=5).pack(side="left", padx=4)
        row = {"type": tvar, "count": cvar, "frame": fr, "combo": cb}
        tk.Button(fr, text="✕", command=lambda: self._del_row(self.ring_rows, row)).pack(side="left")
        self.ring_rows.append(row)

    def add_ct_row(self, name="", size=(1, 1), gate=0, color=(150, 150, 150)):
        fr = tk.Frame(self.ct_box); fr.pack(fill="x", pady=1)
        nvar = tk.StringVar(value=name)
        e = tk.Entry(fr, textvariable=nvar, width=7, font=MONO); e.pack(side="left")
        nvar.trace_add("write", lambda *_: self._refresh_type_choices())
        wvar = tk.StringVar(value=str(size[0])); hvar = tk.StringVar(value=str(size[1]))
        gvar = tk.StringVar(value=str(gate))
        for var, w in ((wvar, 3), (hvar, 3), (gvar, 3)):
            tk.Entry(fr, textvariable=var, width=w, font=MONO).pack(side="left")
        cvar = tk.StringVar(value="%d,%d,%d" % tuple(color))
        hexc = "#%02x%02x%02x" % tuple(color)
        sw = tk.Button(fr, width=3, bg=hexc, relief="groove")
        sw.config(command=lambda: self._pick_color(cvar, sw))
        sw.pack(side="left", padx=2)
        row = {"name": nvar, "w": wvar, "h": hvar, "gate": gvar,
               "color": cvar, "frame": fr, "swatch": sw}
        tk.Button(fr, text="✕", command=lambda: self._del_row(self.ct_rows, row)).pack(side="left")
        self.ct_rows.append(row)
        self._refresh_type_choices()

    def _del_row(self, rows, row):
        row["frame"].destroy()
        rows.remove(row)
        self._refresh_type_choices()

    def _clear_rows(self, rows):
        for r in list(rows):
            r["frame"].destroy()
        rows.clear()

    def _pick_color(self, var, swatch):
        try:
            cur = "#%02x%02x%02x" % self._parse_rgb(var.get())
        except Exception:
            cur = "#999999"
        rgb, hx = colorchooser.askcolor(color=cur, title="选择颜色")
        if rgb:
            var.set("%d,%d,%d" % (int(rgb[0]), int(rgb[1]), int(rgb[2])))
            swatch.config(bg=hx)

    @staticmethod
    def _parse_rgb(s):
        parts = [int(x) for x in s.replace("，", ",").split(",")]
        return tuple(parts[:3])

    # ================= 配方 <-> 面板 =================
    def _descriptor_size(self, tileset_rel):
        """读贴图集描述符里的 tile_w/tile_h（读不到给 205×84 兜底）。"""
        try:
            with open(os.path.join(HERE, tileset_rel), "r", encoding="utf-8") as f:
                js = json.load(f)
            return js.get("tile_w", 205), js.get("tile_h", 84)
        except Exception:
            return 205, 84

    def _recipe_files(self):
        files = sorted(glob.glob(os.path.join(HERE, "recipes", "*.json")))
        return [os.path.relpath(f, HERE).replace("\\", "/") for f in files]

    def load_selected_recipe(self):
        rel = self.recipe_var.get().strip()
        self.load_recipe_path(os.path.join(HERE, rel))

    def load_recipe_path(self, path, silent=False):
        try:
            with open(path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception as e:
            if not silent:
                messagebox.showerror("读取失败", str(e))
            return
        self.apply_recipe_dict(d)

    def apply_recipe_dict(self, d):
        lo = d.get("layout", {})
        self.v["name"].set(d.get("name", "map"))
        self.v["factions"].set(str(d.get("factions", 3)))
        self.v["seed"].set(str(d.get("seed", 0)))
        self.v["topology"].set(d.get("topology", "radial"))
        self.v["tileset"].set(d.get("tileset", "tilesets/terrain.json"))
        # 瓦片尺寸：配方有覆盖就用；否则读贴图集描述符的实际尺寸，保证界面显示真实值
        dw, dh = self._descriptor_size(d.get("tileset") or C.TILESET_FILE)
        self.v["tile_w"].set(str(d.get("tile_w") or dw))
        self.v["tile_h"].set(str(d.get("tile_h") or dh))
        self.v["ring_gap"].set(str(lo.get("ring_gap", 6)))
        self.v["spawn_margin"].set(str(lo.get("spawn_margin", 4)))
        self.v["road_width"].set(str(lo.get("road_width", 2)))
        self.v["road_style"].set(lo.get("road_style", "smooth"))
        self.v["edge_margin"].set(str(lo.get("edge_margin", 6)))
        self.v["max_bends"].set(str(lo.get("max_bends", 3)))
        self.v["mirror_arc"].set(str(lo.get("mirror_arc", 150.0)))
        self.v["cross_links"].set(bool(lo.get("cross_links", True)))
        self.v["mirror"].set(bool(lo.get("mirror", True)))
        self.v["random_layout"].set(bool(lo.get("random_layout", True)))

        self._clear_rows(self.ct_rows)
        for name, cd in d.get("city_types", {}).items():
            sz = cd.get("size", [1, 1])
            self.add_ct_row(name, tuple(sz), cd.get("gate_count", 0),
                            tuple(cd.get("color", [150, 150, 150])))
        self._clear_rows(self.ring_rows)
        for r in d.get("rings", []):
            self.add_ring_row(r.get("type", ""), r.get("count", 1))

        roles = d.get("roles", {})
        defaults = {"center": "中心城", "gate": "关城", "spawn": "出生城"}
        for key, var in self.role_v.items():
            var.set(roles.get(key, defaults[key]))
        self._refresh_type_choices()

    def collect_recipe(self):
        d = {
            "schema_version": 1,
            "name": self.v["name"].get().strip() or "map",
            "factions": int(self.v["factions"].get()),
            "seed": int(self.v["seed"].get()),
            "topology": self.v["topology"].get().strip() or "radial",
            "tileset": self.v["tileset"].get().strip() or "tilesets/terrain.json",
            "tile_w": int(self.v["tile_w"].get()),
            "tile_h": int(self.v["tile_h"].get()),
            "layout": {
                "ring_gap": int(self.v["ring_gap"].get()),
                "spawn_margin": int(self.v["spawn_margin"].get()),
                "road_width": int(self.v["road_width"].get()),
                "road_style": self.v["road_style"].get().strip() or "smooth",
                "cross_links": bool(self.v["cross_links"].get()),
                "random_layout": bool(self.v["random_layout"].get()),
                "edge_margin": int(self.v["edge_margin"].get()),
                "max_bends": int(self.v["max_bends"].get()),
                "mirror_arc": float(self.v["mirror_arc"].get()),
                "mirror": bool(self.v["mirror"].get()),
            },
            "rings": [{"type": r["type"].get().strip(), "count": int(r["count"].get())}
                      for r in self.ring_rows if r["type"].get().strip()],
            "roles": {k: v.get().strip() for k, v in self.role_v.items()},
            "city_types": {},
        }
        for r in self.ct_rows:
            name = r["name"].get().strip()
            if not name:
                continue
            d["city_types"][name] = {
                "size": [int(r["w"].get()), int(r["h"].get())],
                "gate_count": int(r["gate"].get()),
                "color": list(self._parse_rgb(r["color"].get())),
            }
        return d

    def save_recipe(self):
        try:
            d = self.collect_recipe()
        except Exception as e:
            messagebox.showerror("参数错误", f"请检查数值字段:\n{e}"); return
        path = filedialog.asksaveasfilename(
            title="另存配方", initialdir=os.path.join(HERE, "recipes"),
            defaultextension=".json", filetypes=[("JSON 配方", "*.json")],
            initialfile=(d["name"] or "recipe") + ".json")
        if not path:
            return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        self.recipe_cb["values"] = self._recipe_files()
        try:
            self.recipe_var.set(os.path.relpath(path, HERE).replace("\\", "/"))
        except Exception:
            pass
        messagebox.showinfo("已保存", path)

    # ================= 生成 =================
    def randomize(self):
        self.v["seed"].set(str(random.SystemRandom().randrange(1, 1_000_000)))

    def on_generate(self):
        try:
            recipe = self.collect_recipe()
        except Exception as e:
            messagebox.showerror("参数错误", f"请检查数值字段(阵营数/种子/尺寸/颜色须为整数):\n{e}")
            return
        self.gen_btn.config(state="disabled", text="生成中…")
        self.txt.delete("1.0", "end"); self.txt.insert("end", "生成中，请稍候…\n")
        threading.Thread(target=self._run, args=(recipe,), daemon=True).start()

    def _run(self, recipe):
        try:
            result = fhlc_gen.generate(recipe=recipe)
            self.root.after(0, self._done, result)
        except Exception:
            import traceback
            self.root.after(0, self._error, traceback.format_exc())

    def _done(self, result):
        self.txt.delete("1.0", "end"); self.txt.insert("end", result["report"])
        self.load_preview(result["preview"])
        self.gen_btn.config(state="normal", text="▶ 生成地图")

    def _error(self, err):
        self.txt.delete("1.0", "end"); self.txt.insert("end", "出错了:\n" + err)
        self.gen_btn.config(state="normal", text="▶ 生成地图")

    # ================= 预览 / 打开 =================
    def show_existing_preview(self):
        p = os.path.join(HERE, C.OUT_PREVIEW)
        if os.path.exists(p):
            self.load_preview(p)

    def load_preview(self, path):
        img = Image.open(path)
        img.thumbnail((1000, 620))
        self._photo = ImageTk.PhotoImage(img)
        self.img_label.config(image=self._photo)

    def open_tiled(self):
        tmx = os.path.join(HERE, C.OUT_TMX)
        if os.path.exists(tmx): os.startfile(tmx)
        else: messagebox.showinfo("提示", "请先生成地图")

    def open_folder(self):
        os.startfile(os.path.join(HERE, "output"))


if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("1320x880")
    App(root)
    root.mainloop()
