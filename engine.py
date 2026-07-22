# -*- coding: utf-8 -*-
"""
布局引擎 (engine) —— 可插拔拓扑
==============================================================================
把「地图骨架怎么长出来」从导出器里抽出来，做成可插拔的 **Topology** 接口，
为「多样性第三档：换核心拓扑」（见 DESIGN.md §10）铺地基。

Topology.build(spec) 固定跑五个阶段，子类各自实现：
    setup       —— 取种子/随机参数(gap/旋转/镜像)，初始化城池表
    place_nodes —— 放城池节点(中心 + 各环)
    connect     —— 连边 + 内圈道路 + 等距校准量
    routes      —— 每阵营从辐条外延出一条腿(含关城)到出生城(随机→校验→重试)
    embed_grid  —— uv→等轴测网格 + 城池占地 + 返回 map dict

第一个实现 RadialTopology = 现状(N 重径向对称)。**输出与重构前字节级一致**：
阶段划分不改动全局/局部 random 的调用顺序(gap/rot/flip 用 ctx.rng；腿用每次新建的 lrng)。

坐标：uv 屏幕对齐系(u=画面右,v=画面下)，最后转等轴测网格。
"""
import math, random, types, json, os
from collections import deque


# ---- 通用几何 ----
def manhattan_path(a, b):
    """4连通直角路径 a→b：先走列(col)再走行(row)。格数 = |dx|+|dy|+1，长度=曼哈顿距离。
    等轴测地图中格子只与上下左右共边，故道路必须4连通。"""
    (x0, y0), (x1, y1) = a, b
    cells = [(x0, y0)]
    x, y = x0, y0
    sxs = 1 if x1 >= x0 else -1
    while x != x1:
        x += sxs; cells.append((x, y))
    sys_ = 1 if y1 >= y0 else -1
    while y != y1:
        y += sys_; cells.append((x, y))
    return cells


def _rect_detour(pa, pb, L, axis, peak_sign):
    """矩形绕行(倒U)构造一条 4连通、自避、无捷径的定长路 pa→pb（恰 L 步）。
    axis='h': 横轴(x)做「跨度」(需 |dx|≥2 隔开两竖直翼)，纵轴(y)做「峰」；axis='v' 反之。
    peak_sign=+1 峰在更大坐标侧、-1 更小侧。不可行(跨度<2 / slack<0 / slack 为奇)返回 None。
    结构：seg1 从 pa 沿峰轴到峰 → seg2 沿跨度轴横穿 → seg3 沿峰轴落到 pb。
    两竖直翼分居 x=xa / x=xb（相距 |dx|≥2）→ 任意两非相邻路格不相邻 → BFS 复核=L。"""
    if axis == 'v':                       # 纵向跨度：交换 x/y 转为 'h' 再换回
        res = _rect_detour((pa[1], pa[0]), (pb[1], pb[0]), L, 'h', peak_sign)
        return None if res is None else [(y, x) for (x, y) in res]
    xa, ya = pa; xb, yb = pb
    dx = xb - xa; dy = yb - ya
    M = abs(dx) + abs(dy); slack = L - M
    if slack < 0 or slack % 2 != 0: return None
    if abs(dx) < 2: return None           # 跨度轴需 ≥2 格才能隔开两竖直翼
    V = L - abs(dx)                        # 纵向总步数 = |dy| + slack
    peak = (V + ya + yb) // 2 if peak_sign > 0 else (ya + yb - V) // 2
    sy1 = 1 if peak >= ya else -1
    sxd = 1 if xb >= xa else -1
    sy3 = 1 if yb >= peak else -1
    cells = [(xa, ya)]; x, y = xa, ya
    while y != peak:  y += sy1; cells.append((x, y))    # seg1: 竖直到峰
    while x != xb:    x += sxd; cells.append((x, y))    # seg2: 横穿
    while y != yb:    y += sy3; cells.append((x, y))    # seg3: 竖直落到终点
    return cells


def draw_road(pa, pb, L):
    """在 pa、pb 之间画一条**恰好 L 步**的 4连通、自避、无捷径折线路（返回 L+1 个格）。
    L 必须 ≥ 曼哈顿距离且与之同奇偶，否则物理不可行 → 返回 None（调用方据此报告 ⚠️）。
    尝试横/纵两种主轴 × 两种峰向，返回首个可行解（碰撞择优由调用方枚举变体处理）。"""
    dx = abs(pb[0] - pa[0]); dy = abs(pb[1] - pa[1])
    order = ('h', 'v') if dx >= dy else ('v', 'h')
    for axis in order:
        for s in (1, -1):
            r = _rect_detour(pa, pb, L, axis, s)
            if r is not None:
                return r
    return None


def draw_road_variants(pa, pb, L):
    """枚举 pa→pb、长度=L 的所有备选折线路（横/纵主轴 × 两种峰向，去重）。
    供顺序布线时择一「不与已有路/城相邻相交」的变体（见 GraphTopology._route_once）。"""
    out = []; seen = set()
    for axis in ('h', 'v'):
        for s in (1, -1):
            p = _rect_detour(pa, pb, L, axis, s)
            if p is not None:
                key = tuple(p)
                if key not in seen:
                    seen.add(key); out.append(p)
    return out


def bfs_grid(roads, sources):
    """从 sources 多源 BFS，返回 {格子: 到最近源的4连通道路距离}。"""
    dist = {s: 0 for s in sources}
    q = deque(sources)
    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (x + dx, y + dy)
            if n in roads and n not in dist:
                dist[n] = dist[(x, y)] + 1
                q.append(n)
    return dist


class Topology:
    """拓扑基类：固定五阶段管线；子类实现各阶段。ctx 为跨阶段共享的可变上下文。"""
    name = "base"

    def build(self, spec):
        ctx = types.SimpleNamespace(spec=spec)
        self.setup(ctx)
        self.place_nodes(ctx)
        self.connect(ctx)
        self.routes(ctx)
        return self.embed_grid(ctx)

    def setup(self, ctx):        raise NotImplementedError
    def place_nodes(self, ctx):  raise NotImplementedError
    def connect(self, ctx):      raise NotImplementedError
    def routes(self, ctx):       raise NotImplementedError
    def embed_grid(self, ctx):   raise NotImplementedError


class RadialTopology(Topology):
    """N 重径向对称：中心城 + 若干检查点环(如大城) + 最外辐条环(小城,每阵营一座)，
    每阵营从辐条外延一条腿(含关城)到出生城；腿长校准使各方到中心等距。
    检查点环统一位于半径 gap → 各方到任一检查点城距离恒为 {target−dc, target+dc}(方案2平衡)。"""
    name = "radial"

    # ---- 城池表 helper（跨阶段，操作 ctx）----
    def _add_city(self, ctx, ctype, fac, uv, spoke, size=None):
        ctx.spoke_count[ctype] = ctx.spoke_count.get(ctype, 0) + 1
        c = dict(id=ctx.cid, name=f"{ctype}{ctx.spoke_count[ctype]}", type=ctype,
                 faction=fac, uv=uv, spoke=spoke, size=size)
        ctx.cities.append(c); ctx.cid += 1
        return c

    # ---- 阶段1：随机参数 + 初始化 ----
    def setup(self, ctx):
        spec = ctx.spec
        ctx.F = spec.factions
        ctx.rnd = spec.random_layout
        ctx.rng = random.Random(spec.seed)
        random.seed(spec.seed)                                # 供纹理随机使用
        ctx.gap = ctx.rng.randint(5, 8) if ctx.rnd else spec.ring_gap
        ctx.base_rot = ctx.rng.choice([0, 90, 180, 270]) if ctx.rnd else 0   # 仅90°倍数(保内圈对称→平衡不变)
        ctx.flip = (ctx.rng.random() < 0.5) if (ctx.rnd and spec.mirror) else False  # 镜像(v→-v,保曼哈顿距离)
        ctx.gate_t = spec.role_gate
        ctx.guan_per = max(1, sum(c for t, c in spec.rings if t == ctx.gate_t) // ctx.F)   # 每阵营关卡城数
        ctx.cities = []; ctx.cid = 0; ctx.spoke_count = {}
        ctx.edges = []; ctx.ring_edges = []
        ctx.cross_links = spec.cross_links                   # 子类可覆盖(如 mirror 关闭→树结构)

    # 各环城池的角度序列(度)；子类可覆盖以换对称群。radial=均匀 360/N。
    def _ring_angles(self, ctx, count, is_spoke):
        return [270 + i * (360 / count) for i in range(count)]

    # ---- 候选地图（重试循环里给约束校验器用；不写入 ctx）----
    def _leg_nodes(self, ctx, legs):
        """把 radial 的腿转成通用「阵营链」结构：每阵营 1 条车道(spoke→关城…→spawn)。"""
        facs = []
        for s, cells, gidx, gsize in legs:
            facs.append({"spoke_id": ctx.xiao_by_spoke[s]["id"], "spawn_uv": cells[-1],
                         "sidx": s, "lanes": [[cells[i] for i in gidx]]})
        return facs

    def _trial_map(self, ctx, facs, roads_uv, target):
        """由已放好的内圈(ctx.cities/edges) + 各阵营链(facs) 拼出「map 形状」候选，供 constraints 判定。
        facs: [{spoke_id, spawn_uv, sidx, lanes:[[关城 uv,...], ...]}]（lanes 可多条=多路线）。"""
        cities = [dict(c) for c in ctx.cities]           # 复制内圈城(中心/各环/辐条)
        edges = list(ctx.edges)
        nid = ctx.cid
        for f in facs:
            spn = {"id": nid, "type": ctx.spec.role_spawn, "uv": f["spawn_uv"],
                   "faction": f"faction{f['sidx']+1}", "name": f"faction{f['sidx']+1}"}
            nid += 1; cities.append(spn)
            for lane in f["lanes"]:
                prev_id = f["spoke_id"]
                for guv in lane:
                    gc = {"id": nid, "type": ctx.gate_t, "uv": guv, "faction": "npc", "name": f"g{nid}"}
                    nid += 1; cities.append(gc)
                    edges.append((prev_id, gc["id"])); prev_id = gc["id"]
                edges.append((prev_id, spn["id"]))
        return {"roads_uv": roads_uv, "center_uv": (0, 0), "center_id": ctx.center_c["id"],
                "cities": cities, "edges": edges,
                "daxing_uv": [d["uv"] for d in ctx.daxing], "target": target}

    # ---- 阶段2：放城池节点（中心 + 各环，N 重径向 + 整体旋转/镜像）----
    def place_nodes(self, ctx):
        spec, F, gap = ctx.spec, ctx.F, ctx.gap
        center_c = dict(id=ctx.cid, name=spec.role_center, type=spec.role_center,
                        faction="npc", uv=(0, 0), spoke=-1, size=None)
        ctx.cities.append(center_c); ctx.cid += 1
        ctx.center_c = center_c
        base_rot, flip = ctx.base_rot, ctx.flip

        def puv(radius, deg):
            a = math.radians(deg + base_rot)
            u, v = radius * math.cos(a), radius * math.sin(a)
            if flip: v = -v                                  # 轴向镜像(整数网格上保曼哈顿距离)
            return (round(u), round(v))

        # rings 中非「关卡城」条目从内到外定义各环；最外层=辐条环(count=F,腿由此延伸)，其余为检查点环
        inner_tiers = [(t, c) for t, c in spec.rings if t != ctx.gate_t] or [("小城", F)]
        tier_rings = []
        for r, (ttype, tcount) in enumerate(inner_tiers):
            is_spoke = (r == len(inner_tiers) - 1)
            count = F if is_spoke else max(1, tcount)
            radius = (r + 1) * gap
            angles = self._ring_angles(ctx, count, is_spoke)
            ring = [self._add_city(ctx, ttype, "npc", puv(radius, angles[i]),
                                   i if is_spoke else -1) for i in range(count)]
            tier_rings.append((ttype, ring, is_spoke))
        ctx.tier_rings = tier_rings
        ctx.daxing = tier_rings[0][1]                        # 最内检查点环(平衡报告用；单环时=辐条环)
        ctx.spoke_ring = tier_rings[-1][1]
        ctx.xiao_by_spoke = {c["spoke"]: c for c in ctx.spoke_ring}

    # ---- 阶段3：连边 + 内圈道路 + 等距校准量 ----
    def connect(self, ctx):
        spec, F, gap = ctx.spec, ctx.F, ctx.gap
        tier_rings, edges, ring_edges = ctx.tier_rings, ctx.edges, ctx.ring_edges
        # 最内环 → 中心；其余每环 → 就近更内环
        for c in tier_rings[0][1]:
            edges.append((ctx.center_c["id"], c["id"]))
        for r in range(1, len(tier_rings)):
            prev = tier_rings[r - 1][1]
            for c in tier_rings[r][1]:
                near = min(prev, key=lambda k: (k["uv"][0]-c["uv"][0])**2 + (k["uv"][1]-c["uv"][1])**2)
                edges.append((c["id"], near["id"]))
        if ctx.cross_links and F >= 3:
            ordered = sorted(ctx.spoke_ring, key=lambda c: math.atan2(c["uv"][1], c["uv"][0]))
            for i in range(F):
                ring_edges.append((ordered[i]["id"], ordered[(i+1) % F]["id"]))

        by_id = {c["id"]: c for c in ctx.cities}

        def ring_path(a, b):
            (au, av), (bu, bv) = a, b
            c1, c2 = (au, bv), (bu, av)
            corner = c1 if (abs(c1[0])+abs(c1[1])) >= (abs(c2[0])+abs(c2[1])) else c2
            return manhattan_path(a, corner) + manhattan_path(corner, b)[1:]

        inner_roads = set()
        for a, b in edges:
            for cell in manhattan_path(by_id[a]["uv"], by_id[b]["uv"]): inner_roads.add(cell)
        for a, b in ring_edges:
            for cell in ring_path(by_id[a]["uv"], by_id[b]["uv"]): inner_roads.add(cell)
        for c in ctx.cities: inner_roads.add(c["uv"])
        ctx.edges = edges + ring_edges
        ctx.inner_roads = inner_roads

        dist0 = bfs_grid(inner_roads, [(0, 0)])
        ctx.d_xiao = {s: dist0.get(ctx.xiao_by_spoke[s]["uv"], 2*gap) for s in range(F)}
        ctx.base_target = max(ctx.d_xiao.values()) + (ctx.guan_per + 1) * gap + spec.spawn_margin
        ctx.guan_base = spec.size_of(ctx.gate_t)

    # ---- 阶段4：生成 F 条腿（随机→校验→重试）→ 道路 + 关城/出生城 ----
    def routes(self, ctx):
        spec, F, gap, rnd = ctx.spec, ctx.F, ctx.gap, ctx.rnd
        guan_per, guan_base, gate_t = ctx.guan_per, ctx.guan_base, ctx.gate_t
        xiao_by_spoke, d_xiao, base_target = ctx.xiao_by_spoke, ctx.d_xiao, ctx.base_target
        AX = [(0, -1), (0, 1), (-1, 0), (1, 0)]

        def spoke_axis(uv):
            """辐条外向最接近的 4 连通轴方向（供固定/兜底模式，N 阵营通用）。"""
            su, sv = uv
            return max(AX, key=lambda d: d[0]*su + d[1]*sv)

        def gen_leg(lrng, start, outer_len):
            """从 start 生成一条腿的道路格(不含 start)：直线段(含全部关城) + 阶梯段(0~K 个直角弯)，末端出生城。
            关键不变量(保公平)：总格数恒=outer_len(等距)；关城全在直线段(横堵直线,不在拐角)；
            阶梯段用「外向两轴单调折线」→ 自避且无捷径(任意两非相邻格曼哈顿距>1)，BFS 复核仍=target。"""
            su, sv = start
            guan_at = sorted({max(1, (k+1)*gap + (lrng.randint(-1, 1) if rnd else 0)) for k in range(guan_per)})
            last_gate = guan_at[-1] if guan_at else 0
            if outer_len < last_gate + 2: return None        # 直线段放不下关城(且末格留给拐角/出生城)
            if rnd:
                d1 = lrng.choice([d for d in AX if d[0]*su + d[1]*sv >= 0] or AX)
            else:
                d1 = spoke_axis(start)
            perp = [(0, 1), (0, -1)] if d1[0] != 0 else [(1, 0), (-1, 0)]
            if rnd:
                dp = lrng.choice([d for d in perp if d[0]*su + d[1]*sv >= 0] or perp)
            else:
                dp = perp[0]
            seg1 = min(outer_len, lrng.randint(last_gate + 2, last_gate + 2 + gap)) if rnd else outer_len
            rem = outer_len - seg1
            cells = []; u, v = su, sv; guan_idx = []
            for step in range(1, seg1 + 1):
                u += d1[0]; v += d1[1]; cells.append((u, v))
                if step in guan_at: guan_idx.append(len(cells) - 1)
            if rem > 0:
                if rnd:
                    nseg = lrng.randint(1, max(1, min(rem, spec.max_bends + 1)))
                    cuts = sorted(lrng.sample(range(1, rem), nseg - 1)) if nseg > 1 else []
                else:
                    cuts = []
                parts = []; prev = 0
                for c in cuts: parts.append(c - prev); prev = c
                parts.append(rem - prev)
                cur = dp
                for length in parts:
                    for _ in range(length):
                        u += cur[0]; v += cur[1]; cells.append((u, v))
                    cur = d1 if cur == dp else dp            # 每段换轴 → 一个直角弯
            gsize = guan_base if d1[0] != 0 else (guan_base[1], guan_base[0])   # 关城横堵朝向
            return cells, guan_idx, gsize

        committed = None; best = None; best_target = base_target
        target = base_target
        import constraints as _cons               # 延迟导入避免与本模块循环
        loop_checks = _cons.loop_constraints(spec)          # in_loop 约束
        hard_checks = [c for c in loop_checks if c.hard]    # 硬约束(等距/行列)：不满足则地图无效
        for attempt in range(800):
            lrng = random.Random(spec.seed * 1009 + attempt)
            extra = lrng.randint(0, 2*gap) if (rnd and attempt < 700) else 0
            target = base_target + extra
            legs = []; trial = set(ctx.inner_roads); ok = True
            for s in range(F):
                leg = gen_leg(lrng, xiao_by_spoke[s]["uv"], target - d_xiao[s])
                if leg is None: ok = False; break
                cells, gidx, gsize = leg
                legs.append((s, cells, gidx, gsize))
                trial.update(cells)
            if not ok: continue
            cand = self._trial_map(ctx, self._leg_nodes(ctx, legs), trial, target)
            if not all(chk.check(cand, spec) for chk in hard_checks):
                continue                                     # 硬约束不过 → 弃
            if best is None: best, best_target = legs, target # 记住首个硬约束合格者(软约束兜底)
            if all(chk.check(cand, spec) for chk in loop_checks):
                committed = legs; break                       # 全部(含路线画像等软约束)满足 → 采用
        if committed is None and best is not None:
            committed, target = best, best_target            # 软约束无法全满足 → 退回硬约束合格者(报告会标⚠️)
        if committed is None:                                # 兜底：沿辐条外向的直线腿
            committed = []
            for s in range(F):
                du, dv = spoke_axis(xiao_by_spoke[s]["uv"])
                outer_len = base_target - d_xiao[s]
                cells = []; u, v = xiao_by_spoke[s]["uv"]; gidx = []
                guan_at = {(k+1)*gap for k in range(guan_per)}
                for step in range(1, outer_len + 1):
                    u += du; v += dv; cells.append((u, v))
                    if step in guan_at: gidx.append(len(cells)-1)
                gsize = guan_base if du != 0 else (guan_base[1], guan_base[0])
                committed.append((s, cells, gidx, gsize))

        roads_uv = set(ctx.inner_roads)
        for s, cells, gidx, gsize in committed:
            prev = xiao_by_spoke[s]
            for i, cell in enumerate(cells):
                roads_uv.add(cell)
                if i in gidx:
                    gc = self._add_city(ctx, gate_t, "npc", cell, s, size=gsize)
                    ctx.edges.append((prev["id"], gc["id"])); prev = gc
            spn = self._add_city(ctx, spec.role_spawn, f"faction{s+1}", cells[-1], s)
            ctx.edges.append((prev["id"], spn["id"]))
        ctx.roads_uv = roads_uv
        ctx.target = target

    # ---- 阶段5：uv → 等轴测网格 + 城池占地 + 返回 map dict ----
    def embed_grid(self, ctx):
        spec = ctx.spec
        cities, roads_uv = ctx.cities, ctx.roads_uv
        # smooth: 恒等(col=u,row=v,平滑斜带) / screen: 旋转(col=u+v,row=v-u,画面横竖但串珠)
        if spec.road_style == "screen":
            conv = lambda u, v: (u + v, v - u)
        else:
            conv = lambda u, v: (u, v)

        # 道路加宽到 road_width 格（在 uv 里向 +u/+v 方向增厚）
        w = max(1, spec.road_width)
        roads_uv_thick = set()
        for (u, v) in roads_uv:
            for du in range(w):
                for dv in range(w):
                    roads_uv_thick.add((u + du, v + dv))

        # 网格尺寸：中心城居中 + 出生城离地图边缘全 edge_margin 格
        conv_cells = [conv(u, v) for (u, v) in roads_uv_thick]

        def _fp_off(ccx, ccy, w, h):
            x0 = ccx - w // 2 + (1 if w % 2 == 0 else 0)
            y0 = ccy - h // 2 + (1 if h % 2 == 0 else 0)
            return [(x0 + dx, y0 + dy) for dx in range(w) for dy in range(h)]

        all_off = list(conv_cells)
        spawn_off = []
        for c in cities:
            cxo, cyo = conv(*c["uv"])
            cw, ch = c.get("size") or spec.size_of(c["type"])
            fo = _fp_off(cxo, cyo, cw, ch)
            all_off += fo
            if c["type"] == spec.role_spawn:
                spawn_off += fo
        ext = lambda pts: max(max(abs(x), abs(y)) for x, y in pts)
        edge_n = max(0, spec.edge_margin)
        half = max(ext(all_off), (ext(spawn_off) + edge_n) if spawn_off else 0)

        def to_grid(uv):
            u, v = uv; c, r = conv(u, v); return (c + half, r + half)
        W = H = 2 * half + 1
        roads = set(to_grid(c) for c in roads_uv_thick)
        for c in cities: c["cell"] = to_grid(c["uv"])
        center_cell = (half, half)

        # 城池占地：以道路中心线为中心的 w×h 块（偶数尺寸把 2 格路夹正中 → 路从边中心穿出）
        def footprint(city):
            cw, ch = city.get("size") or spec.size_of(city["type"])
            cx0, cy0 = city["cell"]
            x0 = cx0 - cw//2 + (1 if cw % 2 == 0 else 0)
            y0 = cy0 - ch//2 + (1 if ch % 2 == 0 else 0)
            return [(x0+dx, y0+dy) for dx in range(cw) for dy in range(ch)]
        for c in cities:
            c["cells"] = footprint(c)

        return dict(W=W, H=H, center=center_cell, cities=cities, roads=roads,
                    roads_uv=roads_uv, edges=ctx.edges, center_id=ctx.center_c["id"],
                    center_uv=(0, 0), daxing_uv=[d["uv"] for d in ctx.daxing],
                    target=ctx.target, L=ctx.target)


# ---- 拓扑注册表 + 工厂 ----
class MirrorTopology(RadialTopology):
    """镜像对称(非旋转)：城池沿主对角线(u↔v)双侧对称的扇形排布，而非 radial 的均匀 360°。
    以「树」结构(关闭辐条同心环)保证公平由构造成立：
      · 等距：腿长校准 + 重试 BFS 复核（同 radial）
      · 兵种：每阵营 spawn→腿(guan_per 关城)→小城(自身辐条)→就近大城→中心，各类计数一致
      · 大城平衡：树上「远端大城必经中心」→ 各方距离组合恒为 {target−dc, target+dc}（dc 同=半径 gap）
    只覆盖角度序列 + 关闭 cross_links，其余五阶段沿用 radial → 验证接口可承载第二种对称群。"""
    name = "mirror"

    def setup(self, ctx):
        super().setup(ctx)
        ctx.cross_links = False                              # 树结构：远端检查点必经中心 → 平衡精确

    def _ring_angles(self, ctx, count, is_spoke):
        if count <= 1:
            return [45.0]
        arc = getattr(ctx.spec, "mirror_arc", 150.0)        # 扇形张角(度)，可在配方调
        step = arc / (count + 1)
        mid = (count - 1) / 2.0
        # 以主对角线(45°)为对称轴：θ 与 90−θ 成对 → 镜像对，且行列天然互异(a,b)/(b,a)
        return [45 + (i - mid) * step for i in range(count)]


class MultiRouteTopology(RadialTopology):
    """多路线：每阵营从出生城到中心有**两条等长并行路**(战术分流)。
    构造：出生城与其辐条小城分居一个矩形的对角，两条 L 形路各走矩形两边 → 长度均= |Δu|+|Δv|(相等)，
    仅在小城/出生城两端相交，中间隔空 → BFS 最短路 = 两条任一 = target。两条路各带 guan_per 关城
    (无论走哪条都同样多关卡 → 兵种公平对最短路成立)。大城平衡沿用 radial 核(检查点对称)。
    公平不「自证」：等距/无捷径由重试循环里的 in_loop 校验器判定(呼应 §4.5)，几何不达标就换随机态重试。"""
    name = "multi_route"

    def setup(self, ctx):
        super().setup(ctx)
        ctx.cross_links = False                              # 树核 + 双车道 → 平衡/无捷径更稳

    def routes(self, ctx):
        spec, F, gap, rnd = ctx.spec, ctx.F, ctx.gap, ctx.rnd
        guan_per, guan_base, gate_t = ctx.guan_per, ctx.guan_base, ctx.gate_t
        xiao_by_spoke, d_xiao = ctx.xiao_by_spoke, ctx.d_xiao
        AX = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        import constraints as _cons
        loop_checks = _cons.loop_constraints(spec)

        need = guan_per * gap + 2                            # 每条边至少容纳全部关城 + 缓冲
        # 双车道 outer_len = a + b，a,b 各 ≥ need → 比 radial 单腿长约一倍，故 base_target 更大
        base_target = max(d_xiao.values()) + (2 * guan_per + 2) * gap + spec.spawn_margin

        def spoke_axis(uv):
            su, sv = uv
            return max(AX, key=lambda d: d[0]*su + d[1]*sv)

        def gsize_for(d):
            return guan_base if d[0] != 0 else (guan_base[1], guan_base[0])

        def gen_lanes(lrng, start, outer_len):
            """两条等长 L 形路(start→spawn)，各在首段直线放 guan_per 关城。返回 dict 或 None。"""
            su, sv = start
            if outer_len < 2 * need:
                return None
            if rnd:
                d1 = lrng.choice([d for d in AX if d[0]*su + d[1]*sv >= 0] or AX)
                perp = [(0, 1), (0, -1)] if d1[0] != 0 else [(1, 0), (-1, 0)]
                dp = lrng.choice([d for d in perp if d[0]*su + d[1]*sv >= 0] or perp)
                a = lrng.randint(need, outer_len - need)
            else:
                d1 = spoke_axis(start)
                perp = [(0, 1), (0, -1)] if d1[0] != 0 else [(1, 0), (-1, 0)]
                dp = perp[0]
                a = outer_len // 2
            b = outer_len - a
            spawn = (su + d1[0]*a + dp[0]*b, sv + d1[1]*a + dp[1]*b)

            def lane(first_dir, first_len, second_dir, second_len):
                cells = []; u, v = su, sv; gidx = []
                guan_at = {(k+1)*gap for k in range(guan_per)}    # 首段直线上，间隔 gap
                for step in range(1, first_len + 1):
                    u += first_dir[0]; v += first_dir[1]; cells.append((u, v))
                    if step in guan_at: gidx.append(len(cells) - 1)
                for _ in range(second_len):
                    u += second_dir[0]; v += second_dir[1]; cells.append((u, v))
                return cells, gidx
            lane1, g1 = lane(d1, a, dp, b)                   # 关城在 d1 段
            lane2, g2 = lane(dp, b, d1, a)                   # 关城在 dp 段
            return dict(lane1=lane1, g1=g1, gs1=gsize_for(d1),
                        lane2=lane2, g2=g2, gs2=gsize_for(dp), spawn=spawn)

        committed = None; best = None; best_target = base_target
        target = base_target
        hard_checks = [c for c in loop_checks if c.hard]
        for attempt in range(1500):
            lrng = random.Random(spec.seed * 2003 + attempt)
            extra = lrng.randint(0, 2*gap) if (rnd and attempt < 1300) else 0
            target = base_target + extra
            per = []; trial = set(ctx.inner_roads); ok = True
            for s in range(F):
                r = gen_lanes(lrng, xiao_by_spoke[s]["uv"], target - d_xiao[s])
                if r is None: ok = False; break
                per.append((s, r)); trial.update(r["lane1"]); trial.update(r["lane2"])
            if not ok: continue
            facs = [{"spoke_id": xiao_by_spoke[s]["id"], "spawn_uv": r["spawn"], "sidx": s,
                     "lanes": [[r["lane1"][i] for i in r["g1"]],
                               [r["lane2"][i] for i in r["g2"]]]} for s, r in per]
            cand = self._trial_map(ctx, facs, trial, target)
            if not all(chk.check(cand, spec) for chk in hard_checks):
                continue
            if best is None: best, best_target = per, target
            if all(chk.check(cand, spec) for chk in loop_checks):
                committed = per; break
        if committed is None and best is not None:
            committed, target = best, best_target
        if committed is None:                                # 兜底：固定方向双车道
            committed = []
            for s in range(F):
                su, sv = xiao_by_spoke[s]["uv"]
                d1 = spoke_axis((su, sv))
                perp = [(0, 1), (0, -1)] if d1[0] != 0 else [(1, 0), (-1, 0)]
                dp = perp[0]; outer = base_target - d_xiao[s]; a = outer // 2; b = outer - a
                def lane(fd, fl, sd, sl):
                    cells = []; u, v = su, sv; gidx = []
                    ga = {(k+1)*gap for k in range(guan_per)}
                    for step in range(1, fl + 1):
                        u += fd[0]; v += fd[1]; cells.append((u, v))
                        if step in ga: gidx.append(len(cells)-1)
                    for _ in range(sl):
                        u += sd[0]; v += sd[1]; cells.append((u, v))
                    return cells, gidx
                l1, gi1 = lane(d1, a, dp, b); l2, gi2 = lane(dp, b, d1, a)
                committed.append((s, dict(lane1=l1, g1=gi1, gs1=gsize_for(d1),
                                          lane2=l2, g2=gi2, gs2=gsize_for(dp),
                                          spawn=(su+d1[0]*a+dp[0]*b, sv+d1[1]*a+dp[1]*b))))

        roads_uv = set(ctx.inner_roads)
        for s, r in committed:
            spoke = xiao_by_spoke[s]
            spn = self._add_city(ctx, spec.role_spawn, f"faction{s+1}", r["spawn"], s)
            for lane_cells, gidx, gs in ((r["lane1"], r["g1"], r["gs1"]),
                                          (r["lane2"], r["g2"], r["gs2"])):
                prev = spoke
                for i, cell in enumerate(lane_cells):
                    roads_uv.add(cell)
                    if i in gidx:
                        gc = self._add_city(ctx, gate_t, "npc", cell, s, size=gs)
                        ctx.edges.append((prev["id"], gc["id"])); prev = gc
                ctx.edges.append((prev["id"], spn["id"]))
        ctx.roads_uv = roads_uv
        ctx.target = target


class GraphTopology(RadialTopology):
    """用户设计拓扑(抽象带权图)→ 渲染。节点=城池(含类型)，边=连接(含指定格数长度)。
    与 radial 相反：不自动摆城/校验重试，而是**忠实按用户的图布局并画路**，公平只校验报告。
    · 布局：以 root(中心城)为原点做楔形细分树布局，子节点距父曼哈顿=该边长度、方位=分配角度。
    · 画路：逐边 draw_road 画恰好=length 的 4连通折线路(树边天然 slack=0=L形；不可行则报告⚠️)。
    · 关城/出生城均为一等节点(edges 里)，故兵种/路线画像/大城平衡报告直接在城池图上成立。
    复用 embed_grid(占地/道路加宽/居中/W-H)，只覆盖 setup/place_nodes/connect/routes。"""
    name = "graph"

    def _load_graph(self, spec):
        if spec.graph: return spec.graph
        if spec.graph_file:
            p = spec.graph_file
            if not os.path.isabs(p):
                p = os.path.join(os.path.dirname(os.path.abspath(__file__)), p)
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        raise ValueError("GraphTopology 需要 spec.graph 或 spec.graph_file")

    def _big_type(self, spec):
        """大城类型 = rings 里最内层的非关卡城(供大城平衡报告)；无 rings 则 None。"""
        inner = [t for t, c in spec.rings if t != spec.role_gate]
        return inner[0] if inner else None

    def _angle_offset(self, angle_deg, m, node):
        """方位角(度) + 曼哈顿模 m → 整数 uv 偏移(|du|+|dv|==m)。node 可给 hint_dir 覆盖方位。"""
        a = math.radians(angle_deg)
        cx, cy = math.cos(a), math.sin(a)
        if "hint_dir" in node:
            cx, cy = float(node["hint_dir"][0]), float(node["hint_dir"][1])
        ax, ay = abs(cx), abs(cy)
        if ax + ay == 0: ax = 1.0
        du = min(m, int(round(m * ax / (ax + ay))))
        dv = m - du
        sx = 1 if cx >= 0 else -1
        sy = 1 if cy >= 0 else -1
        return (sx * du, sy * dv)

    # ---- 阶段1：读图 + 初始化 ----
    def setup(self, ctx):
        spec = ctx.spec
        ctx.graph = self._load_graph(spec)
        ctx.rng = random.Random(spec.seed)
        random.seed(spec.seed)                       # 供纹理随机
        ctx.gate_t = spec.role_gate
        ctx.cities = []; ctx.cid = 0; ctx.spoke_count = {}
        ctx.edges = []; ctx.ring_edges = []
        ctx.cross_links = False
        ctx.warnings = []
        spawns = [n for n in ctx.graph["nodes"] if n["type"] == spec.role_spawn]
        ctx.F = spec.factions = len(spawns)          # 阵营数 = 出生城节点数(覆盖供报告)

    # ---- 阶段2：楔形细分树布局（存布局输入，uv 在 routes 里可重算/抖动）----
    def place_nodes(self, ctx):
        spec = ctx.spec; g = ctx.graph
        nodes, edges = g["nodes"], g["edges"]
        by_key = {n["id"]: n for n in nodes}
        adj = {n["id"]: [] for n in nodes}; elen = {}
        for e in edges:
            adj[e["a"]].append(e["b"]); adj[e["b"]].append(e["a"])
            elen[frozenset((e["a"], e["b"]))] = e["length"]
        root = (next((n["id"] for n in nodes if n.get("root")), None)
                or next((n["id"] for n in nodes if n["type"] == spec.role_center), None)
                or nodes[0]["id"])
        # 生成树(BFS) + 非树边(cross-link)
        parent = {root: None}; tree_children = {n["id"]: [] for n in nodes}
        order = [root]; q = deque([root]); tree_es = set()
        while q:
            u = q.popleft()
            for v in adj[u]:
                if v not in parent:
                    parent[v] = u; tree_children[u].append(v)
                    tree_es.add(frozenset((u, v))); order.append(v); q.append(v)
        ctx.parent = parent; ctx.tree_children = tree_children
        ctx.cross = [(e["a"], e["b"]) for e in edges
                     if frozenset((e["a"], e["b"])) not in tree_es]
        # 叶子数(角度权重)
        leaf = {}
        def count(u):
            ch = tree_children[u]
            leaf[u] = 1 if not ch else sum(count(c) for c in ch)
            return leaf[u]
        count(root)
        # 基准角度(楔形细分)：显式 angle 优先，否则子节点按叶子数分父楔形
        base_ang = {}
        def assign(u, lo, hi):
            base_ang[u] = float(by_key[u].get("angle", (lo + hi) / 2.0))
            ch = tree_children[u]
            if not ch: return
            tot = sum(leaf[c] for c in ch); cur = lo
            for c in ch:
                w = (hi - lo) * leaf[c] / tot
                assign(c, cur, cur + w); cur += w
        # 中心城四条边(右/下/左/上)的方位角；从边中心正向穿出
        CENTER_SIDES = (0.0, 90.0, 180.0, 270.0)
        def assign_root():
            """根(中心城)的每条通路优先落在「还没有路」的边上；一条边上有多条路时在其 ±45° 内均分。"""
            base_ang[root] = float(by_key[root].get("angle", 0.0))
            ch = tree_children[root]
            if not ch: return
            use = [0, 0, 0, 0]                              # 每条边(0右1下2左3上)已分配的路数
            side = {}
            for c in ch:                                   # 显式 angle 的子节点先认领其最近的边
                if "angle" in by_key[c]:
                    s = int(round((float(by_key[c]["angle"]) % 360.0) / 90.0)) % 4
                    side[c] = s; use[s] += 1
            for c in ch:                                   # 其余按顺序选「当前路最少」的边(空边优先)
                if c not in side:
                    s = min(range(4), key=lambda k: (use[k], k)); side[c] = s; use[s] += 1
            grp = {}
            for c in ch: grp.setdefault(side[c], []).append(c)
            for s, group in grp.items():                   # 同一条边上的多条路在该边 ±45° 楔形里均分
                c0 = CENTER_SIDES[s]; n = len(group); half = 45.0 / n
                for j, c in enumerate(group):
                    a = (float(by_key[c]["angle"]) if "angle" in by_key[c]
                         else c0 - 45.0 + 90.0 * (j + 0.5) / n)
                    assign(c, a - half, a + half)          # 子树在以该路方位为中心的楔形里细分
        assign_root()
        ctx.root_key = root; ctx.base_ang = base_ang; ctx.by_key = by_key
        ctx.order = order; ctx.elen = elen; ctx.jit = 22.0     # 抖动幅度(度)

        # 建 city dict(int id)；uv 先用无抖动布局占位，routes 里择优后回填
        uv0 = self._place_uv(ctx, None)
        base_gate = spec.size_of(ctx.gate_t)
        def gate_size(k):
            p = parent.get(k)
            if p is None: return base_gate
            du = uv0[k][0] - uv0[p][0]; dv = uv0[k][1] - uv0[p][1]
            return base_gate if abs(du) >= abs(dv) else (base_gate[1], base_gate[0])
        key2id = {}; id2key = {}; fac_seen = 0
        for n in nodes:
            k = n["id"]; cid = ctx.cid; ctx.cid += 1; key2id[k] = cid; id2key[cid] = k
            if n["type"] == spec.role_spawn:
                fac_seen += 1; fac = f"faction{n.get('faction', fac_seen)}"
            else:
                fac = "npc"
            size = gate_size(k) if n["type"] == ctx.gate_t else None
            ctx.cities.append(dict(id=cid, name=str(k), type=n["type"],
                                   faction=fac, uv=uv0[k], spoke=-1, size=size))
        ctx.key2id = key2id; ctx.id2key = id2key
        ctx.center_c = next(c for c in ctx.cities if c["id"] == key2id[root])
        big = self._big_type(spec)
        ctx.daxing = [c for c in ctx.cities if big and c["type"] == big]

    def _place_uv(self, ctx, rng):
        """按(可抖动的)角度把节点放到 uv：子距父曼哈顿=边长、方位=角度。root 在原点。
        rng=None 用基准角度(不抖动)；否则对非根、非 fixed_uv 节点加 ±jit 抖动(长度不变)。"""
        ang = dict(ctx.base_ang)
        if rng is not None:
            for k in ang:
                if k != ctx.root_key and "fixed_uv" not in ctx.by_key[k]:
                    ang[k] += rng.uniform(-ctx.jit, ctx.jit)
        uv = {ctx.root_key: (0, 0)}
        for u in ctx.order:
            for c in ctx.tree_children[u]:
                du, dv = self._angle_offset(ang[c], ctx.elen[frozenset((u, c))], ctx.by_key[c])
                uv[c] = (uv[u][0] + du, uv[u][1] + dv)
        for n in ctx.graph["nodes"]:
            if "fixed_uv" in n: uv[n["id"]] = tuple(n["fixed_uv"])
        return uv

    def _uv_footprint(self, uv_pt, size):
        """uv 空间占地(与 embed_grid.footprint 同规则；smooth 下 uv≡grid 相对偏移)。"""
        cw, ch = size; cx0, cy0 = uv_pt
        x0 = cx0 - cw // 2 + (1 if cw % 2 == 0 else 0)
        y0 = cy0 - ch // 2 + (1 if ch % 2 == 0 else 0)
        return [(x0 + dx, y0 + dy) for dx in range(cw) for dy in range(ch)]

    def _route_once(self, ctx, uv):
        """顺序布线：逐边择一「不与已布线路(含1格光环)、无关城池占地相邻/相交」的变体。
        返回 (roads_uv, edge_cells, conflicts)。conflicts=无法隔开的边列表。"""
        spec = ctx.spec
        foot = {c["id"]: set(self._uv_footprint(uv[ctx.id2key[c["id"]]],
                                                c.get("size") or spec.size_of(c["type"])))
                for c in ctx.cities}
        all_foot = set()
        for s in foot.values(): all_foot |= s
        edges = ctx.graph["edges"]
        order = sorted(range(len(edges)), key=lambda i: -edges[i]["length"])  # 长边(主干)先占

        def halo(cells):
            h = set()
            for (x, y) in cells:
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        h.add((x + dx, y + dy))
            return h

        road_block = set(); edge_cells = {}; conflicts = []
        for i in order:
            e = edges[i]; a, b = e["a"], e["b"]
            pa, pb = uv[a], uv[b]
            endpt = foot[ctx.key2id[a]] | foot[ctx.key2id[b]]   # 本边两端城占地(允许触碰)
            obstacles = road_block | (all_foot - endpt)         # 已布线路+光环 & 无关城池
            variants = draw_road_variants(pa, pb, e["length"]) or [manhattan_path(pa, pb)]
            chosen = None
            for v in variants:
                body = [c for c in v if c not in endpt]
                if not any(c in obstacles for c in body):
                    chosen = v; break
            if chosen is None:
                chosen = variants[0]; conflicts.append((a, b))
            edge_cells[i] = chosen
            body = [c for c in chosen if c not in endpt]
            road_block |= set(body) | (halo(body) - all_foot)  # 占本路+光环(不覆盖城=路口可入)
        roads_uv = set()
        for v in edge_cells.values(): roads_uv |= set(v)
        for c in ctx.cities: roads_uv.add(uv[ctx.id2key[c["id"]]])
        return roads_uv, edge_cells, conflicts

    # ---- 阶段3：边(城池图，供报告)----
    def connect(self, ctx):
        k2i = ctx.key2id
        ctx.edges = [(k2i[e["a"]], k2i[e["b"]]) for e in ctx.graph["edges"]]

    # ---- 阶段4：择优布线(隔离约束) + 抖动重试 ----
    def routes(self, ctx):
        spec = ctx.spec
        best_uv = None; best = None; best_conf = None
        for att in range(200):
            rng = None if att == 0 else random.Random(spec.seed * 7919 + att)
            uv = self._place_uv(ctx, rng)
            roads_uv, edge_cells, conflicts = self._route_once(ctx, uv)
            if best is None or len(conflicts) < len(best_conf):
                best_uv, best, best_conf = uv, roads_uv, conflicts
                if not conflicts: break
        # 回填最优布局的 uv
        for c in ctx.cities:
            c["uv"] = best_uv[ctx.id2key[c["id"]]]
        ctx.roads_uv = best
        if best_conf:
            pairs = "，".join(f"{a}-{b}" for a, b in best_conf[:6])
            more = "…" if len(best_conf) > 6 else ""
            ctx.warnings.append(
                f"{len(best_conf)} 条路无法与其它路/城完全隔开(可能相邻或相交): {pairs}{more}"
                f"；建议在编辑器里把相关城拉开或改边长")
        d = bfs_grid(best, [ctx.center_c["uv"]])
        vals = [d.get(c["uv"]) for c in ctx.cities if c["type"] == spec.role_spawn]
        vals = [v for v in vals if v is not None]
        ctx.target = max(vals) if vals else 0

    # ---- 阶段5：复用 embed_grid，附带不可行警告 ----
    def embed_grid(self, ctx):
        mp = super().embed_grid(ctx)
        mp["warnings"] = ctx.warnings
        return mp


TOPOLOGIES = {RadialTopology.name: RadialTopology,
              MirrorTopology.name: MirrorTopology,
              MultiRouteTopology.name: MultiRouteTopology,
              GraphTopology.name: GraphTopology}

def get_topology(name):
    """按名取拓扑实例；未知/空名回退 radial。"""
    return TOPOLOGIES.get(name or "radial", RadialTopology)()


def build_map(spec):
    """入口：按 spec.topology 选拓扑并构建。默认 radial（现状）。"""
    return get_topology(getattr(spec, "topology", "radial")).build(spec)
