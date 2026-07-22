# -*- coding: utf-8 -*-
"""
约束校验器 (constraints)
==============================================================================
把地图的公平/结构约束抽成独立、可开关的校验器对象（见 DESIGN.md §10 步骤2）：
拓扑只负责「生成候选」，公平由校验器判定 → 新拓扑不必各自证明公平。

每个 Constraint：
  · check(state, spec) -> bool       —— 判定(重试循环用候选 state；仅 in_loop=True 参与)
  · report(mp, spec) -> (lines, ok)  —— 对最终 map dict 出人类可读报告 + 通过标记

state / mp 都是「map 形状」的 dict（键：roads_uv, center_uv, center_id, cities, edges,
daxing_uv, target...）。重试循环里由拓扑构造轻量候选(含虚拟关城/出生城节点)，与最终 mp 同形，
故同一套 check/report 既能判候选、又能出报告。

约束键：equidistant(等距) / distinct_spawn(出生城行列互异) / fairness(兵种公平) /
        balance(大城平衡) / route_profile(路线画像：4 个 BFS 度量各方一致)
recipe 的可选字段 `constraints`（键名列表；缺省=全开）。

确定性：默认全开；重试循环用 in_loop 的 {distinct_spawn, equidistant, route_profile}。
对称的 radial 下这三者对每个候选都同时成立 → 与重构前提交同一候选 → 输出字节级不变。
"""
from collections import deque
from engine import bfs_grid


def _spawns(state, spec):
    return [c for c in state["cities"] if c["type"] == spec.role_spawn]


def _target(state):
    return state.get("target", state.get("L"))


def _tier_types(spec):
    """从 rings 推断 (关城, 小城=最外内环/辐条, 大城=最内检查点环) 的类型名，供路线画像用。"""
    inner = [(t, c) for t, c in spec.rings if t != spec.role_gate] or [("小城", spec.factions)]
    return spec.role_gate, inner[-1][0], inner[0][0]      # gate, small(spoke), big(checkpoint)


class Constraint:
    key = "?"; title = "?"; in_loop = False; hard = False
    def check(self, state, spec):
        return True
    def report(self, mp, spec):
        return [], True


class DistinctSpawnRowsCols(Constraint):
    """约束9：各出生城两两不同行、不同列。"""
    key = "distinct_spawn"; title = "出生城行列互异"; in_loop = True; hard = True

    def _ok(self, state, spec):
        sp = _spawns(state, spec)
        us = {c["uv"][0] for c in sp}; vs = {c["uv"][1] for c in sp}
        return len(us) == spec.factions and len(vs) == spec.factions

    def check(self, state, spec):
        return self._ok(state, spec)

    def report(self, mp, spec):
        ok = self._ok(mp, spec)
        return ([] if ok else ["[出生城行列] ⚠️ 存在同行或同列"]), ok


class EquidistantSpawns(Constraint):
    """约束4：各出生城到中心城的 4 连通道路格数完全相等（且=target）。"""
    key = "equidistant"; title = "等距"; in_loop = True; hard = True

    def check(self, state, spec):
        d = bfs_grid(state["roads_uv"], [state["center_uv"]])
        tgt = _target(state)
        return all(d.get(c["uv"]) == tgt for c in _spawns(state, spec))

    def report(self, mp, spec):
        dist = bfs_grid(mp["roads_uv"], [mp["center_uv"]])
        sp = _spawns(mp, spec)
        lines = ["[等距校验] 出生城 → 中心城:"]; ds = []
        for c in sp:
            d = dist.get(c["uv"]); ds.append(d)
            lines.append(f"  {c['name']}: {d} 格")
        valid = [d for d in ds if d is not None]
        ok = len(set(valid)) == 1 and len(valid) == spec.factions
        lines.append(f"  >>> 距离{'完全相等' if ok else '不相等!!'}")
        return lines, ok


def _city_graph(state):
    """返回 (by_id, adj)。"""
    by_id = {c["id"]: c for c in state["cities"]}
    adj = {}
    for a, b in state["edges"]:
        adj.setdefault(a, []).append(b); adj.setdefault(b, []).append(a)
    return by_id, adj


class UnitFairness(Constraint):
    """约束5：各阵营到中心途经各类城池的数量集合一致（兵种公平）。"""
    key = "fairness"; title = "兵种公平"; in_loop = False

    def _tiers(self, state, spec):
        by_id, adj = _city_graph(state)
        cid = state["center_id"]

        def path_tiers(spawn_id):
            prev = {spawn_id: None}; q = deque([spawn_id])
            while q:
                u = q.popleft()
                if u == cid: break
                for v in adj.get(u, []):
                    if v not in prev: prev[v] = u; q.append(v)
            node = cid; tiers = {}
            while node is not None:
                t = by_id[node]["type"]
                if t not in (spec.role_center, spec.role_spawn):
                    tiers[t] = tiers.get(t, 0) + 1
                node = prev.get(node)
            return tiers
        return [(c["name"], path_tiers(c["id"])) for c in _spawns(state, spec)]

    def check(self, state, spec):
        return len({tuple(sorted(t.items())) for _, t in self._tiers(state, spec)}) == 1

    def report(self, mp, spec):
        rows = self._tiers(mp, spec)
        lines = ["[兵种公平] 各阵营途经城池:"]
        for name, tiers in rows:
            lines.append(f"  {name}: " + " ".join(f"{k}×{v}" for k, v in sorted(tiers.items())))
        fair = len({tuple(sorted(t.items())) for _, t in rows}) == 1
        lines.append(f"  >>> 兵种途经{'完全一致' if fair else '大致(见上)'}")
        return lines, fair


class BigCityBalance(Constraint):
    """约束6：各阵营到各检查点城(大城)的距离组合一致（方案2平衡）。"""
    key = "balance"; title = "大城平衡"; in_loop = False

    def _profiles(self, mp, spec):
        sp = _spawns(mp, spec)
        per = {s["name"]: [] for s in sp}
        for duv in mp["daxing_uv"]:
            dd = bfs_grid(mp["roads_uv"], [duv])
            for s in sp:
                per[s["name"]].append(dd.get(s["uv"]))
        return sp, per

    def check(self, state, spec):
        if not state.get("daxing_uv"):
            return True
        _, per = self._profiles(state, spec)
        return len({tuple(sorted(v)) for v in per.values()}) == 1

    def report(self, mp, spec):
        if not mp["daxing_uv"]:
            return [], True
        sp, per = self._profiles(mp, spec)
        ck = next((c["type"] for c in mp["cities"] if c["uv"] == mp["daxing_uv"][0]), "大城")
        lines = [f"[{ck}平衡] 各出生城 → {len(mp['daxing_uv'])}座{ck} 距离(格):"]
        for i, duv in enumerate(mp["daxing_uv"], 1):
            dd = bfs_grid(mp["roads_uv"], [duv])
            lines.append(f"  {ck}{i}: " + "  ".join(f"{s['name']}={dd.get(s['uv'])}" for s in sp))
        profiles = [tuple(sorted(v)) for v in per.values()]
        sym = len(set(profiles)) == 1
        lines.append(f"  >>> 各阵营距离组合 {profiles[0] if profiles else ()} —— "
                     f"{'✅ 各方一致(方案2最佳平衡)' if sym else '⚠️ 各方不一致'}")
        return lines, sym


class RouteProfile(Constraint):
    """路线画像（城池图上从出生城做 BFS，统计 4 个度量，强制各阵营一致）：
      m1 直达关城数         —— 直接相邻(经过0城)的 关城
      m2 直达小城数         —— 直接相邻的 小城
      m3 经1关城达小城数    —— 最短路中间城恰为 [关城] 的 小城
      m4 经1小城达大城数    —— 最短路中间城恰含 1 座 小城 的 大城
    这些量刻画各阵营出生点周边的「可达结构」，比兵种公平(仅数总数)更细。"""
    key = "route_profile"; title = "路线画像"; in_loop = True

    def _profile(self, state, spec):
        gate, small, big = _tier_types(spec)
        by_id, adj = _city_graph(state)
        out = {}
        for sp in _spawns(state, spec):
            sid = sp["id"]
            prev = {sid: None}; q = deque([sid])
            while q:
                u = q.popleft()
                for v in adj.get(u, []):
                    if v not in prev: prev[v] = u; q.append(v)

            def inter(tid):                          # 中间城类型序列(不含 spawn 与 target)
                seq = []; node = prev.get(tid)
                while node is not None and node != sid:
                    seq.append(by_id[node]["type"]); node = prev.get(node)
                return seq
            m1 = m2 = m3 = m4 = 0
            for c in state["cities"]:
                tid = c["id"]
                if tid == sid or tid not in prev:
                    continue
                seq = inter(tid); t = c["type"]
                if t == gate and not seq: m1 += 1
                elif t == small and not seq: m2 += 1
                elif t == small and seq == [gate]: m3 += 1
                elif t == big and seq.count(small) == 1: m4 += 1
            out[sp["name"]] = (m1, m2, m3, m4)
        return out

    def check(self, state, spec):
        return len(set(self._profile(state, spec).values())) <= 1

    def report(self, mp, spec):
        prof = self._profile(mp, spec)
        lines = ["[路线画像] 每阵营(直达关城/直达小城/经1关城达小城/经1小城达大城):"]
        for name, tup in prof.items():
            lines.append(f"  {name}: {tup}")
        ok = len(set(prof.values())) <= 1
        lines.append(f"  >>> 各阵营路线画像{'完全一致' if ok else '不一致!!'}")
        return lines, ok


# 顺序：循环里 distinct/equidistant 便宜先判，route_profile 需城池图后判；报告顺序同此
ALL = [DistinctSpawnRowsCols, EquidistantSpawns, RouteProfile, UnitFairness, BigCityBalance]


def enabled_constraints(spec):
    """按 recipe 的 constraints 键列表过滤；缺省(None)=全开。"""
    keys = getattr(spec, "constraints", None)
    cons = [c() for c in ALL]
    if keys is None:
        return cons
    kset = set(keys)
    return [c for c in cons if c.key in kset]


def loop_constraints(spec):
    """重试循环里逐个判定候选的约束（enabled 且 in_loop）。"""
    return [c for c in enabled_constraints(spec) if c.in_loop]
