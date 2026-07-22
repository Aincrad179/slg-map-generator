# -*- coding: utf-8 -*-
"""拓扑设计 → 地图 CLI 入口。
用法：python gen_graph.py [design/xxx.json]
读设计文件(nodes/edges + 引用的 recipe) → 组内存配方(topology=graph) → 调 fhlc_gen.generate。
产物同现有流程：output/map.tmx / cities.json / preview.png，并打印等距/兵种等报告。
"""
import os, sys, json
import fhlc_gen

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass

HERE = os.path.dirname(os.path.abspath(__file__))


def build_recipe_from_design(design_path):
    """读设计文件 + 其引用的 recipe，返回可传给 generate 的内存配方 dict。"""
    if not os.path.isabs(design_path):
        design_path = os.path.join(HERE, design_path)
    with open(design_path, "r", encoding="utf-8") as f:
        design = json.load(f)
    recipe_rel = design.get("recipe", "recipes/fhlc.json")
    with open(os.path.join(HERE, recipe_rel), "r", encoding="utf-8") as f:
        recipe = json.load(f)
    recipe["topology"] = "graph"
    recipe["graph"] = {"nodes": design["nodes"], "edges": design["edges"]}
    return recipe


def main():
    design_path = sys.argv[1] if len(sys.argv) > 1 else "design/linear3.json"
    recipe = build_recipe_from_design(design_path)
    fhlc_gen.generate(recipe=recipe)


if __name__ == "__main__":
    main()
