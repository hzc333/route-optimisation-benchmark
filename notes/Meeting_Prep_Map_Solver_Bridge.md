# 会前准备：连接地图（Valhalla）与求解器
# Meeting prep: connecting the map (Valhalla) and the solver

> 中英文对照：每一节先中文，后英文。
> Bilingual: each section is in Chinese first, then English.

---

## 1. 会议目标 / Meeting goals

**中文**

这次会议要定下五件事，会后两人就能各自动手：

1. **数据格式 v0**：站点、车辆、优先级、矩阵、结果分别长什么样，单位和编号怎么约定。
2. **Valhalla 的访问方式**：先用文件交换，还是直接调用服务；服务放在哪台机器上、怎么访问。
3. **第一个演示的范围**：20–30 个斯德哥尔摩站点、1 个仓库、2 辆车，有必做站点和几个优先级，用真实道路矩阵，在地图上显示路线、预计时间和没做的站点。
4. **第一批任务怎么分**：谁做哪一块，什么时候对一次结果。
5. **交通怎么处理**：第一步先不加交通；第二步用历史速度，或者先用高峰/平峰的假设代替。

**English**

The meeting should settle five things, so that we can both start right after:

1. **Data format v0**: what stops, vehicles, priorities, matrices and results look like, with agreed units and IDs.
2. **Access to Valhalla**: file exchange first or calling the service directly; which machine it runs on and how we reach it.
3. **Scope of the first demo**: 20–30 Stockholm stops, one depot, two vehicles, required stops and several priority classes, real road matrices, and a map showing routes, estimated times and unserved stops.
4. **The first tasks**: who does which part, and when we check results together.
5. **Traffic**: none in the first step; in the second step, historical speeds or, until those exist, a labelled peak/off-peak assumption.

---

## 2. 会前要准备的材料 / Materials to prepare

### 2.1 示例站点 / Sample stops

**中文**

准备一份 20–30 个站点的示例，用斯德哥尔摩真实坐标：

- 1 个仓库；
- 3–5 个**必做**站点，其中一两个带时间窗（例如 08:00–09:00）；
- 其余是**可选**站点，分成 CRITICAL / HIGH / NORMAL / LOW，确保车辆做不完全部站点，这样才看得出优先级的效果；
- 2 辆车：1 辆货车、1 辆货运自行车，容量不同；
- 有 1–2 个站点故意放在不好到达的地方（比如靠近水边或公园），用来测试吸附和"无法到达"的处理。

**已生成**：`route-optimisation-benchmark/roads/exchange/demo_v0/`，用 `python -m roads.demo_v0` 重新生成。26 个站点（4 个必做、CRITICAL 3、HIGH 6、NORMAL 8、LOW 5），两辆车共能装 16 块电池，所以会有约 10 个站点做不完。用直线距离试解：必做、CRITICAL、HIGH 全部完成，放弃了 5 个 NORMAL 和全部 LOW。

**English**

Prepare a sample of 20–30 stops with real Stockholm coordinates:

- one depot;
- 3–5 **required** stops, one or two with a time window (e.g. 08:00–09:00);
- the rest **optional**, split into CRITICAL / HIGH / NORMAL / LOW, with more work than the vehicles can do, so the priorities visibly matter;
- two vehicles: one van and one cargo bike with different capacities;
- one or two stops deliberately placed where they are hard to reach (near water or in a park) to test snapping and unreachable stops.

**Generated**: `route-optimisation-benchmark/roads/exchange/demo_v0/` (regenerate with `python -m roads.demo_v0`). 26 stops (4 required; CRITICAL 3, HIGH 6, NORMAL 8, LOW 5); the two vehicles carry 16 batteries, so about 10 stops cannot be served. A trial solve on straight-line distances serves every required, CRITICAL and HIGH stop and leaves out 5 NORMAL and all LOW stops.

### 2.2 数据格式草案 v0 / Data format draft v0

**中文**

带一份草案到会上讨论，不必一次定死。约定先写清楚：

- **编号**：每个站点一个唯一的字符串 `id`，矩阵的行列顺序和站点列表一致；
- **坐标**：用 `lat`、`lon` 两个字段，不用数组。数组在 GeoJSON 里是 [经度, 纬度]，很容易弄反；
- **单位**：距离用整数米，时间用整数秒，时刻用当天 0 点起的秒数，或 "HH:MM"；
- **无法到达**：矩阵里用 `null` 表示，同时单独列出受影响的站点；
- **车型**：用名字对应 Valhalla 的配置，例如 `van` → `auto`，`cargo_bike` → `bicycle`。

三个示例：

**English**

Bring a draft to discuss; it does not have to be final. Conventions to state up front:

- **IDs**: every stop has a unique string `id`; matrix rows and columns follow the stop list order;
- **coordinates**: separate `lat` and `lon` fields, not arrays (GeoJSON arrays are [lon, lat], an easy mistake);
- **units**: whole metres for distance, whole seconds for duration, times of day as seconds since midnight or "HH:MM";
- **unreachable**: `null` in the matrix, plus a separate list of the affected stops;
- **vehicle types**: named profiles mapped to Valhalla costing, e.g. `van` → `auto`, `cargo_bike` → `bicycle`.

Three examples:

**① 求解请求 / Solve request**（用户输入 / user input）

```json
{
  "depot": {"id": "HUB", "lat": 59.2985, "lon": 18.0400},
  "stops": [
    {"id": "s1", "lat": 59.3310, "lon": 18.0590, "service_s": 150,
     "required": true, "time_window": ["08:00", "09:00"]},
    {"id": "s2", "lat": 59.3195, "lon": 18.0720, "service_s": 150,
     "required": false, "priority": "HIGH", "value": 3}
  ],
  "vehicles": [
    {"id": "van1", "profile": "van", "capacity": 30, "shift": ["06:00", "14:00"]},
    {"id": "bike1", "profile": "cargo_bike", "capacity": 10, "shift": ["06:00", "14:00"]}
  ],
  "options": {"priority_mode": "strict", "time_limit_s": 10}
}
```

**② 矩阵（Valhalla 返回）/ Matrix (from Valhalla)**

```json
{
  "profile": "van",
  "ids": ["HUB", "s1", "s2"],
  "distance_m": [[0, 4501, 5290], [4959, 0, 2671], [5120, 2374, 0]],
  "duration_s": [[0, 672, 790], [1003, 0, 613], [880, 493, 0]],
  "snap_m": {"HUB": 4, "s1": 12, "s2": 7},
  "unreachable": []
}
```

**③ 计划结果（求解器返回）/ Plan (from the solver)**

```json
{
  "routes": [
    {"vehicle": "van1",
     "stops": [{"id": "s1", "arrive": "08:12", "start": "08:12"},
               {"id": "s2", "arrive": "08:31", "start": "08:31"}],
     "path": "<Valhalla route shape for the map>"}
  ],
  "unserved": [{"id": "s9", "priority": "LOW", "reason": "no capacity"}],
  "summary": {"distance_m": 18400, "duration_s": 7200}
}
```

### 2.3 需要 Eren 确认的问题 / Questions for Eren

**中文**

1. Valhalla 现在跑在哪里？我能直接访问吗，还是先交换文件？
2. 用的是哪个 Valhalla 版本和哪一份地图数据？能不能固定下来？
3. 货车和货运自行车分别用哪个配置（`auto`、`truck`、`bicycle`）？要设哪些参数？
4. 200 个站点和 450 个站点，算一张矩阵各要多久？单次请求最多能放多少个点对？
5. 地图数据里有没有随时段变化的车速（历史交通）？传入出发时间后，结果会变吗？
6. 站点吸附到路上时，偏移超过多少米算异常？吸附到路的哪一侧能控制吗？
7. 显示路线用哪种格式最方便：Valhalla 的编码折线（shape），还是 GeoJSON？
8. `exclude_polygons`（禁止进入某个区域）能不能用在矩阵请求上？

**English**

1. Where does Valhalla run now? Can I call it directly, or do we exchange files first?
2. Which Valhalla version and map extract are used? Can we pin both?
3. Which costing should the van and the cargo bike use (`auto`, `truck`, `bicycle`), with which options?
4. How long does a matrix take for 200 and for 450 stops? How many pairs fit in one request?
5. Do the tiles have time-dependent (historical) speeds? Does the result change with a departure time?
6. How far may a stop be moved when snapping before we treat it as a problem? Can we control which side of the street?
7. Which path format is easiest for the map: Valhalla's encoded shape, or GeoJSON?
8. Does `exclude_polygons` (keep out of an area) work in matrix requests?

### 2.4 可以展示的现有成果 / Existing work to show

**中文**

- 算法部分的 README 和英文报告（团队仓库 `Algorithm/`），重点是结论表；
- 图解网页 `walkthrough_en.html`：用它解释"按时段复制站点"怎样把交通放进求解，以及分阶段的优先级控制器；
- 已经写好的对接脚本：导出站点、调用 Valhalla 建表、把矩阵读进求解器。在模拟服务上测试通过，还没在真实服务上跑过。

**English**

- The Algorithm README and the English report (team repo `Algorithm/`), mainly the conclusions table;
- the walkthrough page `walkthrough_en.html`, to explain how time-slot copies bring traffic into the solver and how the staged priority controller works;
- the integration scripts already written: export stops, build matrices with Valhalla, load matrices into the solver. Tested against a mock service, not yet against the real one.

---

## 3. 会前可以先做的小验证 / Quick checks before the meeting

**中文**

如果 Eren 会前有时间，下面三件小事能让会议更具体。每件都只需要几分钟：

1. **小矩阵**：用 2.1 的示例站点，在 Eren 的 Valhalla 上跑一次建表脚本，看三件事：
   - 有没有无法到达的点；
   - 吸附距离是否正常；
   - 真实距离和直线距离差多少（斯德哥尔摩水多，可能差得不少）。
2. **一条路线**：拿 3–4 个站点，按固定顺序请求一次 `route`，确认返回的路线形状能在地图上画出来。
3. **出发时间**：同一对站点，分别传 08:00 和 12:00 两个出发时间，看耗时会不会变。用来判断有没有交通数据。

结果不必整理，截图或原始 JSON 带到会上就行。

**English**

If Eren has time before the meeting, these three small checks (a few minutes each) would make the discussion concrete:

1. **Small matrix**: run the matrix script on the sample stops from 2.1 on Eren's Valhalla, and look at three things:
   - unreachable stops;
   - whether snapping distances look normal;
   - how far real distances are from straight lines (Stockholm's water may make this large).
2. **One route**: request `route` for 3–4 stops in a fixed order and check that the shape can be drawn on a map.
3. **Departure time**: request the same pair of stops with departures at 08:00 and 12:00 and see whether the time changes. This tells us whether traffic data is present.

No need to tidy the results; screenshots or raw JSON are enough.

---

## 4. 议程建议（约 60 分钟）/ Suggested agenda (about 60 min)

| 时间 / Time | 内容（中文） | Topic (English) |
|---|---|---|
| 5 min | 对齐目标：第一个演示要做成什么样 | Align on the goal: what the first demo looks like |
| 10 min | 我：求解器现状、优先级处理、交通的做法 | Me: solver status, priority handling, traffic approach |
| 10 min | Eren：Valhalla 现状、车型配置、交通数据 | Eren: Valhalla status, vehicle profiles, traffic data |
| 15 min | 过一遍数据格式草案，定下 v0 | Walk through the data format draft and settle v0 |
| 10 min | Valhalla 访问方式、会前验证的结果、风险 | Valhalla access, results of the quick checks, risks |
| 10 min | 分工、下一次对结果的时间 | Task split and when we next check results together |

---

## 5. 会后的第一批任务（草案）/ First tasks after the meeting (draft)

**中文**

| 任务 | 建议负责人 | 完成的标志 |
|---|---|---|
| 把数据格式 v0 写成一页文档，附示例 | 我 | 两人都认可，放进仓库 |
| 示例站点（20–30 个）和车辆输入 | 我 | CSV 和 JSON 各一份 |
| 用示例站点在 Valhalla 上出矩阵（货车、自行车各一套） | Eren | 矩阵 JSON，附耗时和吸附信息 |
| 求解器读入真实矩阵，按优先级求解，输出计划 JSON | 我 | 计划 JSON，所有必做站点都完成 |
| 按计划的站点顺序请求 Valhalla 路线 | Eren | 每辆车一条路线形状 |
| 地图显示：路线、站点按优先级着色、预计时间、没做的站点 | 会上决定 | 一个能打开的地图页面 |
| 端到端脚本：输入 → 矩阵 → 求解 → 路线 → 地图 | 一起 | 一条命令跑通整个演示 |
| 交通：查清有没有历史速度；没有的话定一个高峰/平峰假设 | Eren 查数据，我接进求解器 | 第二步开始前有结论 |

**English**

| Task | Suggested owner | Done when |
|---|---|---|
| Write data format v0 as a one-page document with examples | Me | Both of us agree; it is in the repo |
| Sample stops (20–30) and vehicle inputs | Me | One CSV and one JSON |
| Matrices for the sample stops from Valhalla (van and bike) | Eren | Matrix JSON with timing and snapping info |
| Solver reads real matrices, solves with priorities, outputs a plan | Me | Plan JSON with every required stop served |
| Valhalla routes for each planned stop order | Eren | One route shape per vehicle |
| Map view: routes, stops coloured by priority, estimated times, unserved stops | Decide at the meeting | A map page that opens |
| End-to-end script: input → matrix → solve → routes → map | Together | One command runs the whole demo |
| Traffic: find out whether historical speeds exist; if not, agree on a peak/off-peak assumption | Eren checks data, I add it to the solver | Decided before step two starts |

---

## 6. 可能的问题和备选方案 / Risks and fallbacks

**中文**

| 可能的问题 | 备选方案 |
|---|---|
| 还没法直接访问 Valhalla | 先交换文件：我发站点文件，Eren 回传矩阵 |
| 矩阵计算太慢 | 演示先用 20–30 个站点；之后再做缓存和只补算新站点 |
| 站点吸附错误或无法到达 | 在结果里明确列出这些站点；把演示站点放在路边 |
| 没有历史交通数据 | 第一步不加交通；第二步用标明清楚的高峰/平峰系数 |
| 地图上的时间和计划对不上 | 路线和矩阵用同一个 Valhalla 版本和配置，并检查差距 |

**English**

| Possible problem | Fallback |
|---|---|
| Valhalla not reachable yet | Exchange files: I send stops, Eren returns matrices |
| Matrices too slow | Keep the demo at 20–30 stops; add caching and incremental updates later |
| Stops snap wrongly or are unreachable | List them clearly in the output; place demo stops on streets |
| No historical traffic data | No traffic in step one; clearly labelled peak/off-peak factors in step two |
| Times on the map differ from the plan | Use the same Valhalla version and costing for routes and matrices, and check the difference |

---

## 7. 会前清单 / Pre-meeting checklist

**中文**

- [ ] 示例站点（20–30 个）准备好，CSV 和 JSON 各一份
- [ ] 数据格式草案 v0（第 2.2 节的三个示例）
- [ ] 问题清单发给 Eren（第 2.3 节），最好会前就发
- [ ] 请 Eren 有空时做第 3 节的小验证
- [ ] 打开报告的结论表和图解网页，准备 10 分钟的现状介绍
- [ ] 想好自己更倾向哪种分工，尤其是地图显示由谁做

**English**

- [ ] Sample stops (20–30) ready as CSV and JSON
- [ ] Data format draft v0 (the three examples in 2.2)
- [ ] Questions sent to Eren (2.3), ideally before the meeting
- [ ] Ask Eren to try the quick checks in section 3 if there is time
- [ ] Report conclusions table and walkthrough page open, for a 10-minute status update
- [ ] Decide which task split I prefer, especially who builds the map view
