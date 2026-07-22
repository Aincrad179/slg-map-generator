# 烽火连城 地图随机生成器 · 设计与决策文档 (DESIGN.md)

> 给"接手/继续微调"用。新对话第一句建议：
> **「读 mapgen/DESIGN.md 和 fhlc_gen.py，我要继续微调地图算法」**
> 代码是实现的唯一真相；本文件记录**为什么这么做**、**哪些方案已被否决**、以及**全部硬约束**，避免重蹈覆辙。

---

## 0. 一句话概述
为 SLG 玩法「烽火连城」生成**等轴测(45°) Tiled 地图**的工具：3 阵营从各自出生城出发，沿道路攻占城池至中心城；地图需满足一系列严格的公平/结构约束，并支持按随机种子生成不同布局。产物是 Tiled 的 `.tmx` + 给程序的 `cities.json` + 预览图。

---

## 1. 硬约束清单（改算法时必须全部满足）
1. **中心城**位于地图**正中心**，占地 **4×4**。
2. **3 个阵营**，每阵营 1 座**出生城**（可攻打起点，安全区）。
3. **只有 2 座大城**；城池数量金字塔：**关城6 > 小城3 > 大城2 > 中心城1**（越大越少越靠内）。
4. **等距**：三座出生城到中心城的**最短行军格数完全相等**（按构造保证）。
5. **兵种公平**：每个阵营到中心途经的城池数量一致 = **关城×2 + 小城×1 + 大城×1**。
6. **大城必经 + 平衡（方案2）**：大城是通往中心的**必经关卡**；每个阵营到两座大城的**距离组合完全一致**（每方一近一远、数值相同，如 (32,44)）。
7. **道路**：宽 **2 格**；**平滑斜向色带**（`smooth`）；从**城池某条边的中心**穿出/延伸（不贴边不贴角）。
8. **关城**只能**横堵在直线路段中间**（关卡），**不得位于任何拐角/路口**；关城长边**垂直于道路**（横向路→1×2，纵向路→2×1，自动旋转）。
9. **两座出生城不得同行或同列**（三者行、列两两不同）。
10. **城池占地尺寸**：中心城 4×4 / 大城 3×3 / 小城 2×2 / 关城 1×2 / 出生城 2×2。
11. **不用对象层**：城池用「城池」瓦片标记层表示 + `cities.json` 存元数据（坐标/尺寸/城门数等）。
12. **种子驱动布局**：改 `SEED` 会产生**不同的整体布局**（不是仅换纹理），且上述约束在每个种子下都成立（靠"生成后校验+重试"保证）。
13. **出生城离边留白**：每座出生城占地离地图边缘至少 `layout.edge_margin` 格（出生城为最外城池时恰好 N 格）；地图尺寸据此自动确定，可在 GUI 调 N。
14. **路线画像一致**（`route_profile`）：城池图上从各出生城做 BFS，4 个度量必须各方相同——① 直达(经0城)关城数 ② 直达小城数 ③ 经恰好1关城达小城数 ④ 经恰好1小城达大城数。刻画各阵营出生点周边「可达结构」，比兵种公平更细。对称拓扑(radial F=3 / mirror N=2 / multi_route)天然成立；不可满足的配置(如 2 大城 vs 4 阵营)则**保硬约束、软退化**并在报告标 ⚠️（见 §4.5）。

---

## 2. 关键设计决策 + 原因

### 2.1 坐标系：uv 屏幕坐标 → 等轴测网格
- 布局全部在 **uv 屏幕对齐坐标系**（u=画面右, v=画面下）里当普通俯视图来做，最后转换成等轴测网格：
  - `smooth`（默认）：`col=u, row=v`（恒等）→ 道路沿网格轴，**平滑实心斜向色带**（瓦片边对边，与参考图 test.png 一致）。
  - `screen`：`col=u+v, row=v-u` → 道路在画面上水平/垂直，但瓦片**角对角相接呈串珠断续**（等轴测菱形瓦片的物理限制，观感差）。
- **结论**：等轴测里想要"平滑的路"就只能是斜向色带。`smooth` 为默认，`screen` 仅作开关保留。

### 2.2 4 连通道路
等轴测瓦片只与**上下左右**共边（斜向格仅共顶点）。所以道路必须 4 连通，否则视觉断裂/不可行走。`manhattan_path` 生成"整段横 + 整段竖 + 一个直角"的 L 形，天然满足。

### 2.3 内圈核心（保证约束4/5/6）· N 阵营径向对称
- 结构：中心城(0,0) + 检查点环(如 **大城**，count 取 RINGS，半径 gap，按角度均匀分布) + **最外辐条环**(如 **小城**，count=F，半径 2·gap，每阵营一辐条) + 辐条环同心环(CROSS_LINKS)。
- 由 `RINGS` 中非「关城」条目从内到外定义各环；**最外环 = 辐条环**(腿由此延伸，count 强制=F)，其余为检查点环(count 取 RINGS 值)。角度 = `270 + i·360/count`（F=3 时退化为旧的 120°/(270,90)，**输出字节级不变**）。
- 连边：`辐条城 → 就近检查点城 → … → 中心城`（检查点=必经关卡）。
- 这是**刚性核心**：等距、兵种、平衡都由它保证，随机化时对它只做 **90° 倍数刚性旋转**（见 2.6）。
- **N 通用性**：因所有检查点城同半径 gap，任一阵营到任一检查点城的距离恒为 `{target−dc, target+dc}`（在其路线上=近=target−dc，经中心到达=远=target+dc）→ 平衡对任意 N/检查点数成立（已验证 F=2..6 等距/兵种/平衡全部通过）。

### 2.4 等距校准（保证约束4）
- `target = max(各小城到中心距离) + (关城数+1)·gap + SPAWN_MARGIN (+随机额外)`
- 每条腿长度 `outer_len = target - d_小城[s]`；出生城在腿末端 → `出生城到中心 = target`（三方相等）。
- 最后用 BFS 实测复核，不达标则重试。

### 2.5 大城平衡（保证约束6，方案2）
- 每方到中心=`target`（相等），必经其"就近大城"（到中心距离=`dc`）→ **近大城=target−dc**；另一座经中心到达 → **远大城=target+dc**。
- `dc` 对两座大城相同（180°对称）→ **距离组合 {target−dc, target+dc} 三方一致**。
- ⚠️ 该结论**依赖内圈对称**：小城环不能产生"绕到别家大城更近"的捷径。

### 2.6 关城=直线关卡（保证约束7/8）
- 关城放在"小城→出生城"的腿上，位于腿的**首段直线**（`gen_leg` 保证：直线段长度 ≥ 最后一个关城位置 + 2，末格留给拐角/出生城）。
- 关城之后才允许拐弯（阶梯段），拐角落在**空地**，不落在关城 → 关城始终横堵直线。
- 关城尺寸随所在路方向旋转：横向路 (1,2)、纵向路 (2,1) → 长边横堵整条 2 格宽的路。

### 2.7 占地居中 → 路从边中心穿出（保证约束7）
- 城池占地块以**道路中心线**为中心对齐：偶数尺寸的块正好把 2 格宽的路夹在正中 → 路从该边**正中**穿出（不贴边/贴角）。
- 见 `footprint()`：偶数维度 `x0 = c - w//2 + 1`。

### 2.8 种子随机化（保证约束12）+ 生成后校验重试
- 随机项：`gap`(5–8)、整体旋转(0/90/180/270)、**镜像**(v→-v，`layout.mirror`)、每条腿方向/长度/关城位置、**阶梯段弯数**(1~`max_bends`+1 段，`layout.max_bends`)。
- **腿形多样性(第一档,不破坏公平)**：腿 = 首段直线(含关城) + 阶梯段(多弯折线)。阶梯段用「外向两轴单调折线」→ 每步的度量 `m=±u±v` 严格 +1，任意两非相邻格曼哈顿距 >1 → **自避、无捷径**，故总格数恒 = `outer_len`(等距不变)，BFS 复核仍 = target。镜像为轴向反射，整数网格上保曼哈顿距离 → 公平不变；但因内圈本已反射对称、各腿本已独立随机，镜像主要贡献「另一种手性」(镜像孪生)，多样性主要来自阶梯段。
- **重试循环**：随机生成 F 条腿 → 校验「出生城行列互异」+ 「BFS 各方到中心=target」→ 不合格换随机态重试（最多 800 次）→ 兜底固定直线腿。
- 校验通过才提交，保证随机不破坏硬约束。

---

## 3. 已否决方案（不要重试）
| 方案 | 为何否决 |
|------|----------|
| 放射辐条 + 斜向(楼梯)路 | 楼梯状难看 |
| 画面水平/垂直的 L 形路 | 等轴测下瓦片角对角→**串珠断续**，不平滑 |
| 方案1：大城作"中心两侧等距侧翼"（三方全等 44） | 完全对称但大城**不在必经路上**，用户否决，改用方案2 |
| **连续任意角度**整体旋转 | 打乱内圈对称→小城环不对称捷径→**破坏大城平衡**（只能用 90° 倍数） |
| 内圈关城连成环 | 用户要求退回，关城保持独立关卡 |
| 关城位于环路/辐条交汇处（拐角） | 违反"关城只横堵直线" |
| 城池用对象层 | 用户否决，改用标记瓦片层 + cities.json |

---

## 4. 代码架构（fhlc_gen.py + engine.py）
```
generate(seed, recipe_file, recipe) # 入口：load_recipe(spec)→seed覆盖→build_map→validate→写文件→返回报告(供GUI)
 └ engine.build_map(spec)    # = get_topology(spec.topology).build(spec)；默认 radial
     RadialTopology 五阶段(见 §4.4)：setup(rng/gap/rot/flip) → place_nodes(中心+各环)
       → connect(连边+内圈路+base_target) → routes(重试循环:gen_leg 阶梯腿→校验行列互异+BFS等距)
       → embed_grid(uv→网格,加宽,中心居中+出生城离边,footprint) → mp{cities,roads,edges,...}
 ├ validate_equal_time(mp,spec)  # BFS 等距 + 各阵营途经兵种统计（fhlc_gen）
 ├ Tileset.write_tsx()       # 地形贴图集(见 §4.1，tileset.py)
 ├ write_marker_tsx(spec,ts)/gen_markers(spec,ts)  # 城池标记贴图集(按 spec.city_types)
 ├ write_tmx(mp,ts,spec)     # 3个瓦片层: 地面/道路/城池(标记)。无对象层
 ├ write_cities_json(mp,spec)   # 城池元数据(name/type/faction/col/row/size/origin/gate_count)
 └ render_preview(mp,ts,spec)   # Pillow 直接用真实贴图渲染预览(城池用色块菱形+标签，色取自 spec)
关键辅助: engine.manhattan_path(L形)/bfs_grid(4连通多源BFS)/ring_path(外拐角环路)
数据/配置: spec.py(Recipe,§4.2) + recipes/*.json；tileset.py(Tileset,§4.1) + tilesets/*.json；engine.py(Topology,§4.4)
```

### 4.1 贴图集抽象（tileset.py + tilesets/*.json）+ 自制美术（tilegen.py）
把「美术素材是什么、哪些瓦片是草地/土路/过渡、瓦片多大、如何写 .tsx」从 `fhlc_gen.py` 剥离到
外部 JSON 描述符 + `Tileset` 类，目标是让任意等轴测美术集都能插拔（通往「通用 45° SLG 工具」的第一步）。
- **描述符** `tilesets/terrain.json`：`name/tile_w/tile_h/orientation`、`image`（collection 目录+文件名 pattern+id_base）、
  `wangset`（转角集颜色）、`terrain.ground/road`（id 区间 + wangid）、`terrain.transition`（有序：文件号→wangid）；
  `obstacle/decoration` 为后续阶段预留的空 seam。`config.TILESET_FILE` 指定用哪份。
- **自制美术** `tilegen.py`：地形瓦片**由程序现画**（纯草地/纯土路各 1 种 + 6 张草↔土过渡），写到 `assets/terrain/*.png`（205×84 等轴测菱形，
  文件号连续 1-8：草 1 / 土 2 / 过渡 3-8；纯地面·纯道路各只 1 种，方便在 Tiled 里用油漆桶整片填），**不使用任何第三方素材**（避免侵权）。仅依赖 Pillow、用自带 `Random(固定种子)`，
  **不碰全局 random**，故不影响地图生成确定性；`generate()` 在写 .tsx/预览前调 `tilegen.build_art(ts.image_dir)`（缺失才画）。
  过渡瓦片按 terrain.json 的 wangid 逐条渲染（角落象限对应 TR/BR/BL/TL），与转角集语义一致。
- **Tileset 类**（仅标准库，**不碰全局 random**）：`ground_ids()/road_ids()/transition_map()/image_path()/gid_of()/
  next_firstgid()/write_tsx()`。`write_tmx`/`render_preview` 全部通过 ts 对象读取，不再有美术专有全局常量。
- **id 连续无空档**：文件号 1-8 连续 → `tilecount=8`、`next_firstgid=9`（marker 集起点），gid 计算无碰撞。

### 4.2 配方数据驱动（spec.py + recipes/*.json）
把「一张地图的设计」从代码/config 抽到外部 JSON 配方，一款游戏 = 一份 `recipes/*.json`。
- **Recipe 类**（spec.py）：`factions/seed/tileset` + `layout.*`（gap/margin/road_width/style/cross_links/random_layout/edge_margin）
  + `rings`（金字塔）+ `city_types`（每类型 size/gate/hp/color，**有序**）+ `roles`（center/gate/spawn 语义角色→类型名）。
- **全链路吃 spec**：`build_map(spec)`、`validate_equal_time(mp,spec)`、`write_tmx/write_cities_json/render_preview/gen_markers`
  全部从 spec 读参数与城池数据；`fhlc_gen.py` 不再有 `MARKER_TYPES/MARKER_COLORS` 常量，也不读 `C.FACTIONS/RINGS/...`。
- **引擎语义角色**：中心/关卡/出生用 `roles` 配置的类型名识别（默认中文名），检查点环=非 gate 的内圈条目，
  最外非 gate 环=辐条环(count 强制=F)。城池类型可任意增删，标记贴图/预览色随 `city_types` 数据生成。
- **确定性**：`recipes/fhlc.json` 的值与旧 config 完全一致 → 交付四文件 `map.tmx/terrain.tsx/cities.json/markers.tsx`
  多种子**字节级一致**；`preview.png` 因预览色改为取自配方而变化（预览非交付物，可接受）。

### 4.3 全参数 GUI（gui.pyw）
把配方的**全部可改字段**做成图形控件，方便策划/调试时不改 JSON 直接试参数。
- **面板分组**（对应 Recipe 字段）：基本(name/factions/seed/topology/tileset/tile_w×tile_h) · 布局(ring_gap/spawn_margin/
  road_width/road_style/cross_links/random_layout/edge_margin/max_bends/mirror) · rings(可增删行) · city_types(每类型 size/gate/color，色块选色，可增删) · roles(center/gate/spawn，下拉选类型名)。
- **数据流**：`load_recipe_path→apply_recipe_dict` 把 JSON 灌进控件；`collect_recipe` 从控件回收成 dict；
  生成走新增的 `generate(recipe=dict)` 分支（见 §4，dict/Recipe 均可，不读磁盘配方）→ **界面调参不改 `recipes/*.json`**。
- **持久化**：顶部「加载配方」下拉切换 `recipes/*.json`；「另存配方…」把当前控件存成新 JSON。
- **确定性**：`apply→collect` 保持 city_types 插入顺序 → 面板回收的 fhlc 配方生成的四交付文件与直接读文件**字节级一致**（已回归验证）。

### 4.4 布局引擎抽象（engine.py，多样性第三档地基·§10 步骤1）
把「地图骨架怎么长出来」从 `fhlc_gen` 抽到 `engine.py` 的可插拔 **Topology**，为「换核心拓扑」铺路。
- **五阶段管线** `Topology.build(spec)`：`setup`(种子/gap/旋转/镜像) → `place_nodes`(中心+各环) →
  `connect`(连边+内圈路+等距校准量) → `routes`(每阵营腿:随机→校验→重试) → `embed_grid`(uv→网格+占地+返回 mp)。
  跨阶段状态放 `ctx`(SimpleNamespace)。子类可只覆盖需要变的阶段。
- **RadialTopology** = 现状(N 重径向对称)，为首个实现。几何 helper `manhattan_path/bfs_grid` 也移入 engine。
- **MirrorTopology**(`topology:mirror`) = 第二种对称群(镜像/非旋转)：城池沿主对角线双侧对称扇形排布 + 关闭辐条环(树结构)。
  只覆盖 `_ring_angles` + `setup`(cross_links=False)，其余四阶段沿用 radial → **验证接口可承载不同对称群**。
  反射群的轨道大小 ≤2 → **仅 N=2 完全公平**(等距/兵种/平衡全 ✅，且平衡为对称的 {d,d})；N>2 单反射无法等价所有阵营
  的大城平衡(实测加宽扇形也不解决,需 dihedral/multi_route,见 §10)。示例配方 `recipes/mirror2.json`。
- **MultiRouteTopology**(`topology:multi_route`) = 每阵营到中心**两条等长并行路**(战术分流)：出生城与其辐条小城分居
  一个矩形对角，两条 L 形路各走矩形两边(长度均=|Δu|+|Δv|)，只在两端相交、中间隔空 → BFS 最短=两条任一=target；
  两条路各带 guan_per 关城 → 兵种公平对最短路成立；大城平衡沿用 radial 核。只覆盖 `routes` 阶段。
  **公平不自证**：等距/无捷径由重试循环的 in_loop 校验器判定(§4.5)，不达标就重试 → 这是「拓扑只管生成候选、
  校验器兜底公平」的范例。N=2/3 完全公平(实测)；N=4 与 radial 同样受 2 大城 vs 4 阵营固有不对称限制。
  腿约 2× 长 → 地图较大。示例 `recipes/multiroute3.json`。
- **GraphTopology**(`topology:graph`) = **用户设计拓扑**(抽象带权图→忠实渲染，不自动摆城/重试)：读设计文件
  `design/*.json`(nodes=城池含 类型/`root`/`faction`；edges=连接含 `length` 格数)，以 root(中心城)为原点做**楔形细分树布局**
  ——子节点距父曼哈顿=边长、方位=分配角度；逐边 `draw_road` 画恰好=length 的 4 连通折线，`routes` 对非根节点抖动 ±22°、
  重试 200 次择「与其它路(含 1 格光环)/无关城占地隔开」最优解，无法隔开的边报 ⚠️。公平**只校验报告、不构造保证**(图由用户负责)。
  关城/出生城均为一等 `edges` 节点 → 兵种/路线画像/大城平衡报告直接在城池图上成立。入口 `python gen_graph.py [design/xxx.json]`。
  复用 `embed_grid`(占地/道路加宽/居中/W-H)，只覆盖 setup/place_nodes/connect/routes。
  - **固定格子/精确落位(`fixed_uv`)**：节点带 `fixed_uv:[u,v]`(相对中心城的格偏移) → `_place_uv` 用它**覆盖**楔形布局，城池精确落在该格；
    中心城=(0,0) 恒居地图正中(embed_grid)。**拓扑编辑器 `graph_editor.pyw` 默认走此路**：在固定格子上摆城 → 每节点写 `fixed_uv`、
    每边 `length`=两端曼哈顿距离(自动)，做到「摆哪出哪、路长自动算」。全 fixed_uv 时无抖动 → 布线确定。楔形/`angle` 仅对**无 fixed_uv** 的抽象设计生效。
  - **中心城四条边分配通路**(约束7 的图版落地)：root 的每条通路优先落在**还没有路的那条边**上——4 条以内一边一条
    (0°右 / 90°下 / 180°左 / 270°上，从边中心**正向**穿出)；超过 4 条才在已用最少的边上并排(同边多路在该边 ±45° 楔形内均分)；
    子节点若显式写 `angle` 则先按其**最近的边**认领。取代旧的「root 子节点按叶子数分 0–360° 楔形」(会把多条主干挤在同侧、或从斜角穿角)。
    见 `engine.py: place_nodes.assign_root`。
- **注册表/工厂** `TOPOLOGIES` + `get_topology(name)`；`recipe.topology`(默认 `radial`)选用；`build_map(spec)` 委托工厂。
- **确定性**：阶段划分不改动 RNG 调用顺序(gap/rot/flip 用 `ctx.rng`；腿用每次新建的 `lrng`) →
  `radial` 下 F=3 / F=4 输出与重构前**字节级一致**（已回归 map.tmx/terrain.tsx/cities.json/markers.tsx）。

### 4.5 约束校验器（constraints.py，多样性第三档地基·§10 步骤2）
把公平/结构约束抽成独立、可开关的校验器对象——拓扑只管「生成候选」，公平由校验器判定，
新拓扑不必各自证明公平。
- **候选与最终 mp 同形**：重试循环里拓扑用 `_trial_map` 拼出「map 形状」的候选(含虚拟关城/出生城节点 + 边)，
  与最终 mp 同键(roads_uv/center_uv/center_id/cities/edges/daxing_uv/target) → 同一套 `check/report` 通用。
- **每个 Constraint** 两用：`check(state, spec)->bool`(判候选) + `report(mp, spec)->(lines, ok)`(出报告)。
- **五个约束**：`distinct_spawn`(行列互异,**hard**) / `equidistant`(等距,**hard**) / `route_profile`(路线画像,in_loop) /
  `fairness`(兵种公平,报告) / `balance`(大城平衡,报告)。
- **硬/软退化**：重试循环里，硬约束(等距/行列)不过则弃；记住首个硬约束合格者为兜底；若某候选连软约束
  (如 route_profile)也全过就采用，否则退回兜底(硬约束保证地图有效，软约束在报告标 ⚠️)。
  → 可满足时强制路线画像一致；不可满足配置(2 大城 vs 4 阵营)不会退化成坏图。
- **报告**(fhlc_gen.generate)：遍历 `enabled_constraints(spec)` 调 `report()`，输出 等距/路线画像/兵种/平衡 各段。
- **开关**：recipe 可选 `constraints`(键列表，缺省=全开)。
- **确定性**：默认循环用 in_loop 的 {distinct,equidistant,route_profile}；对称 radial 三者对同一候选同时成立
  → 提交同一候选 → F=3 输出字节级不变(已回归)。

---

## 5. 文件结构
```
mapgen/
├── config.py            工具级配置（退化为路径/默认）：RECIPE_FILE 指定用哪份配方、输出路径、预览缩放
├── spec.py              配方数据结构：Recipe/CityType + load_recipe（见 §4.2）
├── tileset.py           贴图集抽象：加载 tilesets/*.json 描述符 → 角色查询/.tsx 导出（见 §4.1）
├── tilegen.py           自制地形瓦片：程序现画 草/土/过渡 → assets/terrain（避免第三方素材，见 §4.1）
├── engine.py            布局引擎：可插拔 Topology(setup→place_nodes→connect→routes→embed_grid) + 几何 helper（见 §4.4）
├── constraints.py       约束校验器：等距/行列/兵种/大城平衡，可开关；循环判定候选 + 出报告（见 §4.5）
├── fhlc_gen.py          生成器主程序（导出+预览+校验+CLI，全部吃 spec；布局委托 engine）
├── gen_graph.py         用户设计拓扑入口：读 design/*.json → 组内存配方(topology=graph) → generate（见 §4.4 GraphTopology）
├── gui.pyw              图形界面（**左侧面板暴露配方全部参数**，见 §4.3）
├── graph_editor.pyw     拓扑编辑器：固定格子摆城、路长自动算(fixed_uv 精确落位、摆哪出哪)，见 §4.4
├── 打开生成器.bat        双击启动 GUI
├── 打开拓扑编辑器.bat    双击启动拓扑编辑器
├── 随机生成地图.bat      双击随机出图并弹预览
├── DESIGN.md            本文件
├── README.md            使用说明
├── design/              用户设计拓扑（nodes/edges + 引用 recipe），供 gen_graph.py / graph_editor.pyw
├── recipes/
│   ├── fhlc.json        烽火连城预设（3阵营/2大城平衡）← 一款游戏一份配方
│   ├── demo4.json       示例四阵营配方
│   ├── mirror2.json     示例镜像1v1配方（topology:mirror，N=2，见 §4.4）
│   └── multiroute3.json 示例多路线配方（topology:multi_route，双车道，见 §4.4）
├── tilesets/
│   ├── terrain.json     贴图集描述符（指向自制瓦片 assets/terrain；换画风改 tilegen.py）
│   ├── terrain.tsx      地形贴图集 + 道路转角集（由 tileset.write_tsx 生成）
│   ├── markers.tsx      城池标记贴图集
│   └── markers/*.png    自动生成的城池标记（按配方 city_types）
├── assets/
│   └── terrain/*.png    tilegen.py 自制的等轴测地形瓦片（001-008：草/土/过渡）
└── output/
    ├── map.tmx          Tiled 打开微调
    ├── map.json         Tiled 导出、交付程序
    ├── cities.json      城池数据、交付程序
    └── preview.png      预览
美术素材: 全部由 tilegen.py 现画到 mapgen/assets/terrain/（205×84 等轴测，1草地/2土路/3-8草土过渡；纯地面·纯道路各只 1 种，便于油漆桶填），不依赖任何第三方素材。瓦片尺寸的**唯一真相是贴图集描述符 `tile_w/tile_h`**（配方/GUI 可用 `tile_w`/`tile_h` 覆盖）；生成时 `generate` 把最终尺寸传给 `tilegen.build_art`，尺寸变了自动重画。`tilegen.TILE_W/H` 仅为 `python tilegen.py` 独立运行的默认值。
```

## 6. 配方参数（recipes/*.json，策划改这里）
- `factions`（**支持 2–6 阵营**：径向 N 重对称，见 §2.3；内圈环数/角度按 N 自动展开）
- `rings`：兵种金字塔 `[{大城,2},{小城,3},{关城,3},{关城,3}]`
- `layout.ring_gap=6`（random_layout 时作随机基准）、`layout.spawn_margin=4`、`layout.road_width=2`
- `layout.road_style="smooth"`（或 "screen"）、`layout.cross_links=true`（小城环）、`layout.edge_margin=6`（出生城离地图边缘的格数，四周留白）
- `layout.max_bends=3`（每条腿阶梯段最多弯数，1=旧单弯L形）、`layout.mirror=true`（允许整体镜像；均不破坏公平，见 §2.8）
- `layout.random_layout=true`（种子驱动布局；false=固定几何仅纹理随机）
- `seed`（命令行/GUI 不指定时的默认）、`tileset`（相对 mapgen 根的贴图集描述符）
- `topology`（布局拓扑：`radial`(默认,N重径向) / `mirror`(镜像,N=2) / `multi_route`(双车道多路线) / `graph`(用户设计拓扑,读 `design/*.json`)；见 §4.4/§10）、`constraints`（启用的约束键列表：equidistant/distinct_spawn/route_profile/fairness/balance，缺省全开；见 §4.5）
- `layout.mirror_arc`（仅 `topology:mirror` 用：扇形张角度，默认 150）
- `city_types.{类型}`：`size` 占地尺寸 / `gate_count` / `color`（marker+预览色）。**顺序决定标记 gid**
- `roles`：语义角色→类型名（`center`/`gate`/`spawn`，默认 中心城/关城/出生城）——引擎据此识别中心/关卡/出生
- config.py 仅剩：`RECIPE_FILE`（选配方）、输出路径、`PREVIEW_SCALE`、`TILESET_FILE` 兜底、`SEED`（GUI 预填）

## 7. 运行方式
- GUI：双击 `打开生成器.bat` → 填/随机种子 → 生成 → 看预览
- 一键随机：双击 `随机生成地图.bat`
- 命令行：`python fhlc_gen.py [seed|random]`
- 复核：终端会打印「等距校验 / 兵种途经 / 大城平衡」三段报告，须全部 ✅/一致

---

## 8. 已知限制 / 可继续微调的方向
- **2 大城 vs 3 阵营的固有不对称**：三方到大城的**距离组合相同**，但被 2 方共享的那座大城争夺更激烈（一座近1方、一座近2方）。要完全对称只能用方案1（已否决）。
- **仅 3 阵营完整支持** → 已解除：支持 **2–6 阵营**（§2.3 径向 N 重对称，F=3 输出与旧版字节一致）。更大的 N 受「出生城行列互异」约束与地图尺寸限制，靠重试循环保证。
- **关城朝向与路宽奇偶**：奇数维度城池与 2 格路对中会差半格（观感可接受）。
- **转角集(WangSet)过渡贴图**：terrain.tsx 里 6 张草↔土过渡的角落方向按 wangid 生成，在 Tiled 转角集编辑器里核对更稳。
- 可微调点：近/远大城 32/44 的差距（把大城放更靠近中心可缩小）、腿的弯折花样、地形画风（改 `tilegen.py` 配色/噪点）、支持任意阵营数。

---

## 9. 需求演进（时间线，便于理解为何是现状）
1. 读 Excel 玩法文档 + 参考 test.png → 定工具方向（Python 生成 TMX，Tiled 微调）。
2. 硬性要求 Tiled + 地形素材 + 转角集。
3. 布局多轮返工：放射→三叉戟→uv 屏幕坐标 L 形→smooth 斜向→同心环。
4. 中心城居中、路宽 2、去对象层（标记层+cities.json）。
5. 路从城池边中心穿出（占地对中）。
6. 关城只横堵直线、不在拐角（退出环路，作外腿关卡）。
7. 两出生城不同行列（三条腿朝 上/右/下）。
8. 大城争夺平衡：方案1(等距侧翼,否决) → **方案2(必经关卡,大致平衡,采用)**。
9. GUI + 一键批处理（免开脚本/终端）。
10. **种子真正驱动布局**（随机 gap/旋转/腿，生成后校验重试）。
11. **通用化 · 阶段1 贴图集抽象**：美术从代码剥离到 `tilesets/*.json` + `tileset.py`，任意等轴测美术可插拔（F=3 输出字节不变）。
12. **通用化 · 阶段2 N 阵营几何泛化**：内核从写死 3 辐条泛化为径向 N 重对称，支持 2–6 阵营（§2.3）；F=3 与旧版字节一致。
13. **通用化 · 阶段3 配方数据驱动**：地图设计移入 `recipes/*.json` + `spec.py`(§4.2)，城池类型/路线/角色数据驱动，`config.py` 退化为路径/默认；烽火连城=`recipes/fhlc.json`（交付四文件字节不变）。
14. **全参数 GUI**：`gui.pyw` 左侧面板暴露配方全部字段，可视化调参（§4.3）；`generate(recipe=dict)` 直接吃面板参数，不落盘。
15. **自制地形美术 + 去 `defense_hp`**：地形瓦片改由 `tilegen.py` 现画到 `assets/terrain/`（§4.1），**不再使用任何第三方素材**（避免侵权）；`city_types.defense_hp`（城防值，地图设计无用）从 spec/配方/cities.json/GUI 全部移除。
16. **`dixing.tsx`→`terrain.tsx` + 纯地面/路各 1 砖 + 去 `seconds_per_cell` + 出生城离边约束**：地形贴图集改名 terrain；纯草/纯土各只 1 种瓦片（便于 Tiled 油漆桶），过渡保留 6 张给转角集；删除无用的 `seconds_per_cell`（每格秒数）；新增 `layout.edge_margin`（出生城离地图边缘 N 格，地图尺寸据此自动确定，可在 GUI 调）。
17. **多样性 · 第一档(同对称换皮,不破坏公平)**：腿从「单弯 L」升级为「首段直线(含关城)+阶梯段多弯折线」(`layout.max_bends`)，并加整体镜像(`layout.mirror`)；均为保曼哈顿距离的变换 → 等距/兵种/大城平衡全部不变(已多种子回归)。第二/三档(换对称群/换核心拓扑)见 §10。
18. **多样性 · 第三档 步骤1：抽引擎接口**(§4.4/§10.3-1)：`build_map` 拆成可插拔 `Topology`(engine.py) 五阶段，radial 为首个实现；`recipe.topology` 默认 radial；F=3/F=4 输出字节级回归通过。为后续 mirror/multi_route/funnel 模板铺好地基。
19. **多样性 · 第三档 步骤2：约束校验器化**(§4.5/§10.3-2)：等距/行列/兵种/大城平衡抽成 `constraints.py` 可开关校验器；重试循环遍历 in_loop 校验器判定候选，报告遍历启用校验器；`recipe.constraints` 缺省全开；F=3/F=4 字节级回归通过。拓扑只管生成候选，公平交给校验器。
20. **多样性 · 第三档 步骤3：mirror 模板**(§4.4/§10.3-3)：新增 `MirrorTopology`(主对角线双侧对称,非旋转,树结构)，只覆盖 `_ring_angles`+`setup` → 验证接口可承载第二种对称群；N=2 完全公平(平衡为对称 {d,d})，示例 `recipes/mirror2.json`；radial 仍字节级不变。反射轨道≤2 → N>2 需 multi_route/dihedral。
21. **多样性 · 第三档 步骤4：multi_route 模板**(§4.4/§10.3-4)：新增 `MultiRouteTopology`(每阵营两条等长并行路=矩形双车道)，只覆盖 `routes`；等距/无捷径由 in_loop 校验器兜底(拓扑只生成候选、公平交校验器的范例)；N=2/3 完全公平，示例 `recipes/multiroute3.json`；radial/demo4 仍字节级不变。**首个给 N>2 带来真正拓扑多样性**的模板。
22. **路线画像约束 route_profile**(约束14/§4.5)：城池图 BFS 4 度量(直达关城/直达小城/经1关城达小城/经1小城达大城)强制各阵营一致。为此把 in_loop 候选统一成「map 形状」(`_trial_map`，含虚拟节点+边)；约束分硬(等距/行列)/软，软约束不可满足时退回硬约束合格者(不再退化成坏图)。radial F=3 / mirror N=2 / multi_route 天然一致(F=3 字节不变)；demo4(2大城 vs 4阵营)软退化并报告 ⚠️。
23. **GraphTopology 中心城四条边分配通路**(§4.4)：graph 拓扑(用户设计 `design/*.json`)里 root(中心城)的每条通路优先落在**还没有路的那条边**上——4 条以内一边一条(0°右/90°下/180°左/270°上，从边中心正向穿出)，超 4 条才在已用最少的边上并排(同边多路 ±45° 楔形均分)，显式 `angle` 的子节点先按最近边认领。取代旧的「按叶子数分 0–360° 楔形」(会把多条主干挤同侧/斜角穿角)。同时把 GraphTopology 与 `gen_graph.py`/`design/` 补进 §4.4/§5/§6 文档。
24. **拓扑编辑器改固定格子(所见即所得)**(§4.4)：`graph_editor.pyw` 从「自由画布(位置仅作角度提示、路长手输弹窗)」改为**固定格子**——一格=地图一格，城池吸附格子并以 `fixed_uv`(相对中心城)**精确落位**(中心城居正中)，边长**自动=两端曼哈顿距离**并实时显示，取消手输路长。无 `fixed_uv` 的旧/抽象设计加载时借引擎楔形布局(`place_nodes`)算出格子坐标再贴格。**engine 无改动**(本就支持 `fixed_uv` 覆盖 + `embed_grid` 以 uv=(0,0) 居中)。← 当前最新

> 通用化后续（规划中）：阶段4 可插拔约束；阶段5 装饰/障碍层；多样性第二/三档拓扑模板(见 §10)。

---

## 10. 多样性升级规划（第三档：换核心拓扑）

第一档(§2.8：阶梯腿+镜像)已落地——但**抽象拓扑仍是"中心枢纽 + N 条同构辐条腿"**，只是腿的度量嵌入变多样。要生成**结构不同**的公平图，需把"公平"从"靠对称构造自动成立"改为"靠拓扑模板 + 校验器搜索保证"。以下为规划，非本次实现。

### 10.1 核心思想：拓扑模板 + 公平不变量
- **不变量(任何模板都必须满足)**：每个阵营从出生城到中心的**路线子图两两加权同构**——等距、途经各类城**数量集合**相同、大城距离组合相同。只要保住它，整体拓扑可以任意。
- **做法**：把"生成骨架"从写死的径向核，抽象成可插拔的 **topology 模板**；每个模板负责产出「城池节点 + 边(道路) + 每阵营的路线」，并声明它靠什么保证不变量（对称构造 / 求解 / 校验重试）。
- **recipe 新增** `topology: radial | mirror | multi_route | funnel | ...`（默认 `radial`=现状，向后兼容）。

### 10.2 目标模板（对应 `地图设计思路.md` A–F）
| 模板 | 结构 | 公平怎么保 | 难度 |
|---|---|---|---|
| `radial`(现状) | 枢纽+N 同构辐条 | Cn 旋转对称,自动 | — |
| `mirror` | 2/4 阵营镜像对称(非旋转) | 反射对称,自动 | 低 |
| `multi_route` | 每阵营 2+ 条**等长**并行路→战术分流 | 每路等长(构造)+BFS 校验 | 中 |
| `funnel` | 阵营路线在**共享争夺城**汇合(漏斗) | 共享节点对称放置+校验 | 中高 |
| `asym_solver` | 不对称布局,由求解器摆城/连边 | 生成候选→校验不变量→重试/回溯 | 高 |

### 10.3 建议落地顺序（每步独立可交付、可回归）
1. **抽引擎接口**✅(已完成,见 §4.4)：`build_map` 拆成 `setup→place_nodes→connect→routes→embed_grid`(engine.py 的 Topology)，
   radial 为首个实现，F=3/F=4 输出字节级回归通过；`recipe.topology` 默认 radial。
2. **约束校验器化(呼应阶段4)**✅(已完成,见 §4.5)：等距/兵种/大城平衡/行列互异抽成 `constraints.py` 的独立检查器列表；重试循环遍历"启用的检查器"。模板只管生成候选，公平由校验器判定 → 模板开发不必各自证明。recipe `constraints` 可开关；默认循环用 {distinct_spawn, equidistant}，字节回归通过。
3. **加 `mirror` 模板**✅(已完成,见 §4.4)：主对角线双侧对称(非旋转)+树结构；N=2 完全公平(等距/兵种/平衡全 ✅)，
   验证接口可承载第二种对称群。反射轨道≤2 → N>2 大城平衡无法全等(需下一步 multi_route/dihedral)。`recipes/mirror2.json`。
4. **加 `multi_route`**✅(已完成,见 §4.4)：每阵营两条等长并行路(矩形双车道)，只覆盖 `routes` 阶段；等距/无捷径交给 in_loop 校验器兜底(§4.5 的范例)。N=2/3 完全公平，`recipes/multiroute3.json`。这是**第一个给 N>2 带来真正拓扑多样性**的模板。
5. **加 `funnel`/`asym_solver`**：共享争夺城 / 求解器摆布局；此时校验器是唯一公平保证，需加强 `大城平衡` 的通用判定（现结论依赖内圈对称，见 §2.5，需改为纯 BFS 度量校验）。

### 10.4 风险与注意
- **大城平衡最脆弱**(§2.5/§3)：一旦脱离对称，必须用"到每座大城的 BFS 距离组合逐阵营比对"来判定，而非套用对称结论；不满足就重试/回溯。
- **可行性 vs 多样性**：越不对称，重试命中率越低；`multi_route`/`funnel` 可能需要"构造性对称打底 + 局部随机"而非纯随机搜索，才能在 800 次内命中。
- **网格取整**：非 90°/非轴向的对称在整数网格上取整会破坏精确等距(§3 已验证)；模板须保持轴向/90°对称或显式 BFS 校验兜底。
- **向后兼容**：`topology` 默认 radial，现有配方与交付不受影响；新模板逐个加，各自带回归。
