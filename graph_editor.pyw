# -*- coding: utf-8 -*-
"""
拓扑设计编辑器 · 固定格子版 (graph_editor.pyw)
=============================================================================
双击本文件即可使用。**在固定格子上摆城池，摆在哪里，地图上就出现在哪里。**

用法：
  1. 顶部选一份配方(recipe)决定城池类型/尺寸/颜色/贴图，点「加载」。
  2. 选模式 + 城池类型，在格子画布上：
       · 放置：点某个格子落一座城（选中的类型，自动吸附到格子中心）
       · 连线：依次点两座城 → 直接生成一条路，**路长=两城的格子距离，自动显示**
       · 移动：拖动城到别的格子（吸附），相连路的距离自动更新
       · 删除：点城(连同其边)或点边中点删除
  3. 「▶ 生成地图」→ 右侧出预览 + 校验报告(等距/兵种/大城平衡/路线画像，只报告不改设计)。
  4. 「保存设计…」把拓扑存成 design/*.json；「加载设计…」读回继续编辑。
  5. 「＋/－」缩放格子，滚动条平移。

设计理念：一格 = 地图上的一格。城池的格子坐标直接作为**精确落位**(fixed_uv，相对中心城)
传给布局引擎(engine.GraphTopology)——中心城居于地图正中，其余城按你摆的相对位置精确出现；
每条路按两端格子的曼哈顿距离(|Δ列|+|Δ行|)成形，长度即图上显示的数字。公平只校验报告、不改你的设计。
"""
import os, sys, json, glob, threading, types

if sys.stdout is None: sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None: sys.stderr = open(os.devnull, "w", encoding="utf-8")

import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog

from PIL import Image, ImageTk

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import config as C
import spec as spec_mod
import fhlc_gen
import engine

UI_FONT = ("Microsoft YaHei", 9)
MONO = ("Consolas", 10)

GRID_N = 201                 # 逻辑格子数(每边)；足够容纳 spawn 到中心 ~百格的设计
ORIGIN = GRID_N // 2         # 原点格(放中心城处，序列化时平移到 uv=0)
CELL_MIN, CELL_MAX = 5, 28   # 缩放范围(每格像素)


class Node:
    __slots__ = ("id", "type", "faction", "gu", "gv")
    def __init__(self, nid, ntype, gu, gv, faction=None):
        self.id = nid; self.type = ntype; self.gu = gu; self.gv = gv; self.faction = faction


class App:
    def __init__(self, root):
        self.root = root
        root.title("拓扑设计编辑器 · 固定格子 → 生成 Tiled 地图")
        self.nodes = []            # [Node]
        self.edges = []            # [{"a":id,"b":id}]  (长度=格子距离,实时算)
        self.recipe = None         # spec.Recipe
        self.recipe_rel = C.RECIPE_FILE.replace("\\", "/")
        self._photo = None
        self._counter = {}         # 类型 -> 计数(生成唯一 id)
        self._drag = None          # 移动模式拖动中的节点
        self._connect_first = None # 连线模式已选的第一个节点
        self.cell = 12             # 每格像素(可缩放)

        self.mode = tk.StringVar(value="place")
        self.cur_type = tk.StringVar(value="")

        self._build_toolbar()
        self._build_body()
        self.load_recipe(os.path.join(HERE, self.recipe_rel), silent=True)
        self._draw_grid(); self.redraw(); self._center_view()

    # ================= 顶部工具条 =================
    def _build_toolbar(self):
        bar = tk.Frame(self.root); bar.pack(fill="x", padx=8, pady=(6, 2))
        tk.Label(bar, text="配方:", font=UI_FONT).pack(side="left")
        self.recipe_var = tk.StringVar(value=self.recipe_rel)
        self.recipe_cb = ttk.Combobox(bar, textvariable=self.recipe_var, width=20,
                                      values=self._recipe_files())
        self.recipe_cb.pack(side="left", padx=3)
        tk.Button(bar, text="加载", command=self.load_selected_recipe).pack(side="left", padx=2)
        self.gen_btn = tk.Button(bar, text="▶ 生成地图", command=self.on_generate,
                                 bg="#3a7", fg="white", font=("Microsoft YaHei", 10, "bold"))
        self.gen_btn.pack(side="left", padx=10)
        tk.Button(bar, text="保存设计…", command=self.save_design).pack(side="left", padx=2)
        tk.Button(bar, text="加载设计…", command=self.load_design).pack(side="left", padx=2)
        tk.Button(bar, text="清空", command=self.clear_all).pack(side="left", padx=2)
        tk.Button(bar, text="＋", width=2, command=lambda: self.zoom(1)).pack(side="left", padx=(10, 0))
        tk.Button(bar, text="－", width=2, command=lambda: self.zoom(-1)).pack(side="left", padx=1)
        tk.Button(bar, text="回中心", command=self._center_view).pack(side="left", padx=4)
        tk.Button(bar, text="用 Tiled 打开", command=self.open_tiled).pack(side="left", padx=2)
        tk.Button(bar, text="打开输出", command=self.open_folder).pack(side="left", padx=2)

    def _build_body(self):
        main = tk.PanedWindow(self.root, orient="horizontal", sashwidth=6, bg="#ccc")
        main.pack(fill="both", expand=True, padx=6, pady=4)

        # 左：模式 + 城池类型选择板
        left = tk.Frame(main, width=180); left.pack_propagate(False)
        main.add(left, minsize=170)
        mg = tk.LabelFrame(left, text="模式", font=UI_FONT, padx=6, pady=4)
        mg.pack(fill="x", padx=6, pady=4)
        for val, label in (("place", "放置城池"), ("connect", "连线(自动算路长)"),
                           ("move", "移动"), ("delete", "删除")):
            tk.Radiobutton(mg, text=label, variable=self.mode, value=val,
                           font=UI_FONT, anchor="w", command=self._reset_transient).pack(fill="x")
        self.type_box = tk.LabelFrame(left, text="城池类型(放置用)", font=UI_FONT, padx=6, pady=4)
        self.type_box.pack(fill="x", padx=6, pady=4)
        self.hint = tk.Label(left, text="", font=UI_FONT, fg="#666", justify="left", wraplength=160)
        self.hint.pack(fill="x", padx=8, pady=6)

        # 中：带滚动条的格子画布
        mid = tk.Frame(main); main.add(mid, minsize=360)
        self.canvas = tk.Canvas(mid, bg="#eef3ec", highlightthickness=0)
        hbar = tk.Scrollbar(mid, orient="horizontal", command=self.canvas.xview)
        vbar = tk.Scrollbar(mid, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hbar.set, yscrollcommand=vbar.set)
        vbar.pack(side="right", fill="y"); hbar.pack(side="bottom", fill="x")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        # 右：预览 + 报告
        right = tk.Frame(main, width=460); right.pack_propagate(False)
        main.add(right, minsize=380)
        self.img_label = tk.Label(right, bg="#222")
        self.img_label.pack(fill="both", expand=True)
        self.txt = scrolledtext.ScrolledText(right, height=14, font=MONO)
        self.txt.pack(fill="x", pady=(4, 0))

    # ================= 配方 =================
    def _recipe_files(self):
        files = sorted(glob.glob(os.path.join(HERE, "recipes", "*.json")))
        return [os.path.relpath(f, HERE).replace("\\", "/") for f in files]

    def load_selected_recipe(self):
        self.recipe_rel = self.recipe_var.get().strip()
        self.load_recipe(os.path.join(HERE, self.recipe_rel))

    def load_recipe(self, path, silent=False):
        try:
            self.recipe = spec_mod.load_recipe(path)
        except Exception as e:
            if not silent: messagebox.showerror("读取配方失败", str(e))
            return
        self.recipe_rel = os.path.relpath(path, HERE).replace("\\", "/")
        self._build_type_buttons()
        self._set_hint()

    def _build_type_buttons(self):
        for w in self.type_box.winfo_children(): w.destroy()
        types_ = self.recipe.marker_types if self.recipe else []
        if types_ and not self.cur_type.get():
            self.cur_type.set(types_[0])
        for t in types_:
            col = "#%02x%02x%02x" % tuple(self.recipe.color_of(t))
            w, h = self.recipe.size_of(t)
            r = tk.Frame(self.type_box); r.pack(fill="x", pady=1)
            tk.Radiobutton(r, variable=self.cur_type, value=t, font=UI_FONT).pack(side="left")
            tk.Label(r, width=2, bg=col, relief="groove").pack(side="left", padx=2)
            tk.Label(r, text=f"{t} {w}×{h}", font=UI_FONT, anchor="w").pack(side="left")

    def _color_of(self, ntype):
        if self.recipe:
            return "#%02x%02x%02x" % tuple(self.recipe.color_of(ntype))
        return "#999999"

    def _size_of(self, ntype):
        return self.recipe.size_of(ntype) if self.recipe else (1, 1)

    def _role(self, which):
        return getattr(self.recipe, f"role_{which}", {"center": "中心城", "gate": "关城",
                                                       "spawn": "出生城"}[which])

    # ================= 坐标换算(格子 <-> 画布像素) =================
    def gx(self, gu):  return gu * self.cell            # 格子左上角像素
    def gy(self, gv):  return gv * self.cell
    def cx(self, gu):  return (gu + 0.5) * self.cell     # 格子中心像素
    def cy(self, gv):  return (gv + 0.5) * self.cell

    def cell_at(self, ev):
        """画布事件 → 格子坐标(考虑滚动)。"""
        u = int(self.canvas.canvasx(ev.x) // self.cell)
        v = int(self.canvas.canvasy(ev.y) // self.cell)
        return max(0, min(GRID_N - 1, u)), max(0, min(GRID_N - 1, v))

    def _center_view(self):
        """把视图滚到原点格(中心城应放处)。"""
        frac = (ORIGIN * self.cell) / (GRID_N * self.cell)
        try:
            self.canvas.xview_moveto(max(0, frac - 0.15))
            self.canvas.yview_moveto(max(0, frac - 0.15))
        except Exception:
            pass

    def zoom(self, direction):
        self.cell = max(CELL_MIN, min(CELL_MAX, self.cell + direction * 2))
        self._draw_grid(); self.redraw()

    # ================= 画布交互 =================
    def _set_hint(self, extra=""):
        base = {"place": "点格子放置选中类型的城",
                "connect": "依次点两座城，自动连成路(路长=格子距离)",
                "move": "拖动城到别的格子",
                "delete": "点城/边中点删除"}[self.mode.get()]
        tip = "提示：先放一座「%s」作根，它会落在地图正中。" % self._role("center")
        self.hint.config(text=base + "\n\n" + tip + ("\n\n" + extra if extra else ""))

    def _reset_transient(self):
        self._connect_first = None
        self.redraw(); self._set_hint()

    def _hit_node(self, px, py):
        """画布像素命中某座城(在其占地矩形内)。"""
        for n in reversed(self.nodes):
            w, h = self._size_of(n.type)
            hw, hh = w * self.cell / 2, h * self.cell / 2
            if abs(px - self.cx(n.gu)) <= max(hw, self.cell/2) and \
               abs(py - self.cy(n.gv)) <= max(hh, self.cell/2):
                return n
        return None

    def _hit_edge(self, px, py):
        for e in self.edges:
            a = self._node(e["a"]); b = self._node(e["b"])
            if not a or not b: continue
            mx, my = (self.cx(a.gu) + self.cx(b.gu)) / 2, (self.cy(a.gv) + self.cy(b.gv)) / 2
            if (mx - px) ** 2 + (my - py) ** 2 <= (self.cell) ** 2:
                return e
        return None

    def _node(self, nid):
        return next((n for n in self.nodes if n.id == nid), None)

    def _cell_occupied(self, gu, gv, ignore=None):
        return any(n is not ignore and n.gu == gu and n.gv == gv for n in self.nodes)

    def on_click(self, ev):
        px, py = self.canvas.canvasx(ev.x), self.canvas.canvasy(ev.y)
        mode = self.mode.get()
        if mode == "place":
            gu, gv = self.cell_at(ev)
            if self._cell_occupied(gu, gv):
                self._set_hint("这个格子已经有城了"); return
            self._add_node(self.cur_type.get(), gu, gv)
        elif mode == "connect":
            n = self._hit_node(px, py)
            if not n: return
            if self._connect_first is None:
                self._connect_first = n; self.redraw()
                self._set_hint(f"起点: {n.id}\n再点终点")
            else:
                if n.id != self._connect_first.id:
                    self._make_edge(self._connect_first, n)
                self._connect_first = None; self.redraw(); self._set_hint()
        elif mode == "move":
            self._drag = self._hit_node(px, py)
        elif mode == "delete":
            n = self._hit_node(px, py)
            if n:
                self._del_node(n)
            else:
                e = self._hit_edge(px, py)
                if e: self.edges.remove(e)
            self.redraw()

    def on_drag(self, ev):
        if self.mode.get() == "move" and self._drag:
            gu, gv = self.cell_at(ev)
            if not self._cell_occupied(gu, gv, ignore=self._drag):
                self._drag.gu, self._drag.gv = gu, gv
                self.redraw()

    def on_release(self, ev):
        self._drag = None

    # ================= 节点/边模型 =================
    def _add_node(self, ntype, gu, gv):
        if not ntype:
            messagebox.showinfo("提示", "先在左侧选一个城池类型"); return
        self._counter[ntype] = self._counter.get(ntype, 0) + 1
        nid = f"{ntype}{self._counter[ntype]}"
        faction = None
        if ntype == self._role("spawn"):
            faction = sum(1 for n in self.nodes if n.type == ntype) + 1
        self.nodes.append(Node(nid, ntype, gu, gv, faction))
        self.redraw()

    def _make_edge(self, a, b):
        for e in self.edges:
            if {e["a"], e["b"]} == {a.id, b.id}:
                return                       # 已存在则不重复
        self.edges.append({"a": a.id, "b": b.id})

    def _edge_len(self, e):
        a = self._node(e["a"]); b = self._node(e["b"])
        if not a or not b: return 0
        return abs(a.gu - b.gu) + abs(a.gv - b.gv)

    def _del_node(self, n):
        self.nodes.remove(n)
        self.edges = [e for e in self.edges if n.id not in (e["a"], e["b"])]

    def clear_all(self):
        if self.nodes and not messagebox.askyesno("清空", "确定清空当前设计？"): return
        self.nodes = []; self.edges = []; self._counter = {}
        self._connect_first = None; self.redraw()

    # ================= 绘制 =================
    def _draw_grid(self):
        c = self.canvas; c.delete("grid")
        span = GRID_N * self.cell
        c.configure(scrollregion=(0, 0, span, span))
        step = self.cell
        # 每 5 格加粗一条，便于数格子
        for i in range(GRID_N + 1):
            x = i * step
            col = "#c7d3c2" if i % 5 else "#aab8a4"
            c.create_line(x, 0, x, span, fill=col, tags="grid")
            c.create_line(0, x, span, x, fill=col, tags="grid")
        # 原点(中心城应放处)十字高亮
        ox, oy = self.gx(ORIGIN), self.gy(ORIGIN)
        c.create_line(ox, 0, ox, span, fill="#e0a0a0", tags="grid")
        c.create_line(0, oy, span, oy, fill="#e0a0a0", tags="grid")

    def redraw(self):
        c = self.canvas; c.delete("obj")
        # 边
        for e in self.edges:
            a = self._node(e["a"]); b = self._node(e["b"])
            if not a or not b: continue
            ax, ay, bx, by = self.cx(a.gu), self.cy(a.gv), self.cx(b.gu), self.cy(b.gv)
            c.create_line(ax, ay, bx, by, fill="#b08050", width=max(2, self.cell // 4), tags="obj")
            mx, my = (ax + bx) / 2, (ay + by) / 2
            L = abs(a.gu - b.gu) + abs(a.gv - b.gv)
            c.create_rectangle(mx - 13, my - 9, mx + 13, my + 9,
                               fill="white", outline="#b08050", tags="obj")
            c.create_text(mx, my, text=str(L), font=("Consolas", 9), fill="#333", tags="obj")
        # 节点(按占地尺寸画方块)
        for n in self.nodes:
            w, h = self._size_of(n.type)
            hw, hh = w * self.cell / 2, h * self.cell / 2
            ccx, ccy = self.cx(n.gu), self.cy(n.gv)
            col = self._color_of(n.type)
            outline = "#ff2020" if (self._connect_first and n.id == self._connect_first.id) else "#000"
            wid = 3 if outline == "#ff2020" else 1
            c.create_rectangle(ccx - hw, ccy - hh, ccx + hw, ccy + hh,
                               fill=col, outline=outline, width=wid, tags="obj")
            if self.cell >= 9:
                c.create_text(ccx, ccy, text=n.id, font=("Microsoft YaHei", 7),
                              fill="white", tags="obj")

    # ================= 序列化 =================
    def to_design_dict(self):
        """每座城 → fixed_uv(相对中心城)；每条路 length=格子曼哈顿距离(自动)。"""
        root_type = self._role("center")
        root = next((n for n in self.nodes if n.type == root_type), None)
        cu, cv = (root.gu, root.gv) if root else (ORIGIN, ORIGIN)
        nodes_out = []
        for n in self.nodes:
            d = {"id": n.id, "type": n.type, "fixed_uv": [n.gu - cu, n.gv - cv]}
            if n.faction is not None: d["faction"] = n.faction
            if n is root: d["root"] = True
            nodes_out.append(d)
        edges_out = []
        for e in self.edges:
            a = self._node(e["a"]); b = self._node(e["b"])
            if not a or not b: continue
            edges_out.append({"a": e["a"], "b": e["b"],
                              "length": abs(a.gu - b.gu) + abs(a.gv - b.gv)})
        return {"schema_version": 1, "recipe": self.recipe_rel,
                "nodes": nodes_out, "edges": edges_out}

    def save_design(self):
        if not self.nodes:
            messagebox.showinfo("提示", "画布是空的"); return
        os.makedirs(os.path.join(HERE, "design"), exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="保存设计", initialdir=os.path.join(HERE, "design"),
            defaultextension=".json", filetypes=[("拓扑设计 JSON", "*.json")],
            initialfile="design.json")
        if not path: return
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_design_dict(), f, ensure_ascii=False, indent=2)
        messagebox.showinfo("已保存", path)

    def _grid_positions(self, d):
        """从设计得到 {id:(gu,gv)}。优先 fixed_uv；否则用引擎的图布局算 uv 再贴格。"""
        nodes = d.get("nodes", [])
        if nodes and all("fixed_uv" in n for n in nodes):
            uv = {n["id"]: tuple(n["fixed_uv"]) for n in nodes}
        else:
            uv = self._engine_layout(d)
        return {nid: (int(round(u)) + ORIGIN, int(round(v)) + ORIGIN)
                for nid, (u, v) in uv.items()}

    def _engine_layout(self, d):
        """无 fixed_uv 的老/抽象设计：借引擎的楔形树布局算出各节点 uv(相对中心城)。"""
        rrel = d.get("recipe", self.recipe_rel)
        rpath = os.path.join(HERE, rrel)
        sp = spec_mod.load_recipe(rpath if os.path.exists(rpath)
                                  else os.path.join(HERE, self.recipe_rel))
        sp.topology = "graph"
        sp.graph = {"nodes": d.get("nodes", []), "edges": d.get("edges", [])}
        top = engine.get_topology("graph")
        ctx = types.SimpleNamespace(spec=sp)
        top.setup(ctx); top.place_nodes(ctx)
        return {ctx.id2key[c["id"]]: tuple(c["uv"]) for c in ctx.cities}

    def load_design(self):
        path = filedialog.askopenfilename(
            title="加载设计", initialdir=os.path.join(HERE, "design"),
            filetypes=[("拓扑设计 JSON", "*.json")])
        if not path: return
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        # 切到设计引用的配方
        rrel = d.get("recipe")
        if rrel and os.path.exists(os.path.join(HERE, rrel)):
            self.recipe_var.set(rrel); self.load_recipe(os.path.join(HERE, rrel), silent=True)
        try:
            pos = self._grid_positions(d)
        except Exception as e:
            messagebox.showerror("加载失败", f"无法为该设计计算格子坐标：\n{e}"); return
        self.nodes = []; self.edges = []; self._counter = {}
        for nd in d.get("nodes", []):
            gu, gv = pos.get(nd["id"], (ORIGIN, ORIGIN))
            self.nodes.append(Node(nd["id"], nd["type"], gu, gv, nd.get("faction")))
            self._counter[nd["type"]] = self._counter.get(nd["type"], 0) + 1
        self.edges = [{"a": e["a"], "b": e["b"]} for e in d.get("edges", [])]
        self._connect_first = None
        self._draw_grid(); self.redraw(); self._center_view()

    # ================= 生成 =================
    def on_generate(self):
        if not self.recipe:
            messagebox.showinfo("提示", "先加载一份配方"); return
        if not any(n.type == self._role("center") for n in self.nodes):
            messagebox.showwarning("缺中心城", f"设计里需要一座「{self._role('center')}」作为根"); return
        design = self.to_design_dict()
        try:
            with open(os.path.join(HERE, self.recipe_rel), "r", encoding="utf-8") as f:
                recipe = json.load(f)
        except Exception as e:
            messagebox.showerror("读取配方失败", str(e)); return
        recipe["topology"] = "graph"
        recipe["graph"] = {"nodes": design["nodes"], "edges": design["edges"]}
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

    def load_preview(self, path):
        img = Image.open(path); img.thumbnail((900, 560))
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
    root.geometry("1360x860")
    App(root)
    root.mainloop()
