# -*- coding: utf-8 -*-
"""draw_road 单元测试：定长定端点画路的四条不变量。
运行：python test_draw_road.py
断言：
  (a) 4连通：相邻格恰好差 1 曼哈顿
  (b) 自避：无重复格
  (c) 定长且无捷径：len==L+1 且 bfs_grid(cells,[pa])[pb]==L
  (d) 不可行(slack<0 或 slack 为奇)返回 None
"""
import sys, itertools
from engine import draw_road, bfs_grid

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


def check_path(cells, pa, pb, L):
    assert cells[0] == pa, f"起点错 {cells[0]}!={pa}"
    assert cells[-1] == pb, f"终点错 {cells[-1]}!={pb}"
    assert len(cells) == L + 1, f"格数错 {len(cells)}!={L+1}"
    # (a) 4连通
    for (x0, y0), (x1, y1) in zip(cells, cells[1:]):
        assert abs(x0 - x1) + abs(y0 - y1) == 1, f"非4连通 {(x0,y0)}->{(x1,y1)}"
    # (b) 自避
    assert len(set(cells)) == len(cells), "有重复格(非自避)"
    # (c) 无捷径：路格集合上 BFS 距离 == L
    dist = bfs_grid(set(cells), [pa])
    assert dist.get(pb) == L, f"BFS距离 {dist.get(pb)}!=L={L} (有捷径)"


def main():
    ok = 0; total = 0
    # 遍历一批端点 + 合法长度
    pts = [(0, 0), (10, 3), (3, 10), (7, 7), (15, 2), (0, 12), (20, 20), (-8, 5)]
    for pa, pb in itertools.permutations(pts, 2):
        M = abs(pa[0] - pb[0]) + abs(pa[1] - pb[1])
        for extra in range(0, 40, 2):          # slack 取偶数
            L = M + extra
            total += 1
            r = draw_road(pa, pb, L)
            if r is None:
                # 允许极小跨度(dx<2 且 dy<2)且需绕行时无解；否则不该 None
                dx = abs(pa[0]-pb[0]); dy = abs(pa[1]-pb[1])
                assert (dx < 2 and dy < 2 and extra > 0), \
                    f"意外 None: pa={pa} pb={pb} L={L} (dx={dx},dy={dy})"
                continue
            check_path(r, pa, pb, L)
            ok += 1
    # (d) 不可行：奇数 slack 或 slack<0
    assert draw_road((0, 0), (10, 0), 9) is None, "slack 为奇应 None"
    assert draw_road((0, 0), (10, 0), 5) is None, "L<M 应 None"
    assert draw_road((0, 0), (10, 0), 10) is not None, "slack=0 应可行"
    print(f"[draw_road] 通过 {ok}/{total} 个可行用例 + 不可行用例 ✅")


if __name__ == "__main__":
    main()
