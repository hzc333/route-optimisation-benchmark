**Route Optimisation Engine**

**算法求解器测试与选型执行方案**

Algorithm Solver Benchmark & Selection Plan

版本：v1.0 \| 日期：2026-09-29

适用阶段：项目 Phase 0（Explore and propose）

| **文档定位：**本方案以项目原文 Algorithm Track 的问题为出发点：比较 OR-Tools、PyVRP 或其他候选；验证 priority 建模；评估 traffic 是否应进入搜索；判断 hybrid/learned 方法是否值得继续。执行重点不是“跑通几个 demo”，而是建立一套公平、可复现、能支持最终技术选型的实验流程。 |
|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 1. 研究目标与最终要回答的问题

项目原文把 OR-Tools 作为默认候选、PyVRP 作为高质量模式、VROOM 作为 baseline，并进一步列出 Timefold、jsprit、LKH-3、Hexaly、Gurobi、Nextmv 与神经网络求解器等备选。首轮测试应围绕“约束覆盖、解质量、运行时间、工程复杂度、严格优先级与动态重规划能力”建立证据，而不是只比较最终 objective 数值。

| **研究问题**                             | **需要给出的结论**                                              | **主要证据**                                            |
|------------------------------------------|-----------------------------------------------------------------|---------------------------------------------------------|
| Q1：哪个求解器最适合作为核心？           | OR-Tools / PyVRP / VROOM / Timefold / jsprit 中的主候选与次候选 | 标准 benchmark + 项目自定义约束测试 + 实现成本          |
| Q2：严格 Priority 如何实现？             | 是否需要外部 lexicographic controller，或采用原生分层 score     | 构造反例 + Critical/High/Normal/Low 分阶段测试          |
| Q3：Traffic 是否要进入 Solver search？   | 首版采用静态/分时段矩阵还是 true TDVRP                          | 独立 traffic-aware 实验，不与首轮 solver benchmark 混合 |
| Q4：是否值得研究 learned/hybrid solver？ | 是否进入后续研究，不作为 Phase 0 主线                           | 先证明传统求解器 baseline 与数据可用性，再决定          |

| **核心原则：**首轮 benchmark 必须把“求解器能力”和“问题建模方式”分开。若一个 solver 因不支持某项约束而被迫使用近似建模，应记录为 capability gap，而不能把近似结果与完整模型直接比较。 |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 2. 候选项分层与建议测试顺序

为了在三周探索阶段内获得可执行结论，建议将文档中的候选项分成三层。这样既覆盖原文方案，又避免把时间平均分散到过多工具上。

| **层级**        | **候选**                               | **首轮定位**                                         | **建议投入**  |
|-----------------|----------------------------------------|------------------------------------------------------|---------------|
| A：必须实测     | OR-Tools 9.15                          | 灵活约束核心候选；Python 主线                        | 高            |
| A：必须实测     | PyVRP 0.14.0（稳定版）                 | 标准 VRP 高质量候选；Python                          | 高            |
| A：必须实测     | VROOM 1.15.0                           | 快速 API/baseline；C++ + JSON                        | 中            |
| A：必须实测     | Timefold Solver 2.7.0                  | 严格 Hard/Medium/Soft 与复杂规则对照；Java 21        | 中            |
| B：建议补充     | jsprit 2.0.0                           | Java rich-VRP 对照；时间相关 transport cost 可自定义 | 低-中         |
| C：有资源再测   | Hexaly / Gurobi / Nextmv / LKH-3       | 商业/许可或专用型候选；用于性能或商业可行性补充      | 低            |
| C：暂不作为主线 | Neural solvers（POMO、RouteFinder 等） | 研究对照；不作为生产核心                             | 仅文献/小实验 |

说明：项目原文中的版本与能力判断是 Phase 0 的起点，不应直接当作最终结论。当前官方信息显示 OR-Tools 最新稳定 release 为 9.15；PyVRP 当前稳定 release 为 0.14.0；VROOM 当前 release 为 1.15.0；Timefold 官方 latest 文档为 2.7.0，并要求 Java 21+；jsprit 当前 GitHub 2.0.0 同样要求 Java 21+。实际实验前仍需在仓库中冻结版本并保存 lockfile。

# 3. 公平 Benchmark 的实验纪律

求解器比较最容易出现“结果看似客观、实际上条件不一致”的问题。以下规则建议作为所有实验的硬性要求。

- 同一台机器、同一操作系统、同一 CPU governor / 电源模式下测试；记录 CPU、RAM、OS、Python/Java/Docker 版本。

- 所有 solver 使用同一份 instance、同一距离/时间矩阵、同一车辆数、同一容量与时间窗；不能一个 solver 用欧氏距离、另一个用 road matrix。

- 首轮使用相同 wall-clock time budget，例如 1 s / 10 s / 60 s 三档；不要用“一个跑到收敛、一个只跑 1 分钟”。

- 随机算法至少运行 10 个 seed，报告 mean、median、best、worst、standard deviation；单次最好结果不能代表总体能力。

- 除非专门做 tuning 实验，首轮尽量使用官方默认或推荐参数；任何 tuning 都必须对所有 solver 有对等时间预算。

- 记录“外部墙钟时间”而不是只记录 solver 自报 runtime，因为不同工具对预处理、初始化、矩阵解析是否计时并不一致。

- 所有结果先由统一 Solution Validator 验证可行性；不可行解不进入 objective/gap 比较。

- 目标函数必须拆开记录：distance、duration、vehicles、unserved by priority、lateness、overtime 等。不要只保存 solver 的单个 objective 值。

| **强烈建议：**首轮最关键的是“同一个问题定义 + 同一时间预算 + 同一评价器”。如果 objective 语义不一致，任何 gap 对比都没有意义。 |
|--------------------------------------------------------------------------------------------------------------------------------|

# 4. 建议的代码仓库与环境结构

route-optimisation-benchmark/  
├─ README.md  
├─ environments/  
│ ├─ requirements-python.txt  
│ ├─ pom-timefold.xml  
│ └─ docker-compose.yml  
├─ data/  
│ ├─ raw/  
│ ├─ converted/  
│ └─ bks/  
├─ schema/  
│ ├─ problem.schema.json  
│ └─ solution.schema.json  
├─ adapters/  
│ ├─ ortools_adapter.py  
│ ├─ pyvrp_adapter.py  
│ ├─ vroom_adapter.py  
│ ├─ timefold_adapter/ \# Java project  
│ └─ jsprit_adapter/ \# optional  
├─ evaluator/  
│ ├─ validate.py  
│ ├─ objective.py  
│ └─ metrics.py  
├─ experiments/  
│ ├─ configs/  
│ ├─ run_benchmark.py  
│ └─ run_priority_tests.py  
├─ results/  
│ ├─ raw/  
│ ├─ summary/  
│ └─ plots/  
└─ tests/

建议 Python 主环境使用虚拟环境，Java 工具独立构建，VROOM 优先用 Docker。不要为了“统一语言”把所有 solver 强行包到同一进程里；统一 JSON Problem/Solution Schema 即可。

\# Python 环境（示例）  
python -m venv .venv  
source .venv/bin/activate \# Windows: .venv\Scripts\activate  
python -m pip install -U pip  
python -m pip install ortools==9.15.6755 pyvrp==0.14.0 pandas numpy pydantic psutil  
python -m pip freeze \> environments/requirements-python.txt  
  
\# 记录环境  
python --version  
python -c "import ortools, pyvrp; print(ortools.\_\_version\_\_); print(pyvrp.\_\_version\_\_)"

| **版本注意：**若某个平台暂时无法安装精确 patch 版本，不要悄悄换版本。改用该大版本可获得的稳定包，并在 results/metadata.json 中记录准确版本、安装时间与平台。 |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 5. 先建立统一 Problem Schema，再写各 Solver Adapter

避免直接在各 solver 的原生 API 上分别造数据。建议先定义一个最小公共问题格式，首轮只包含所有候选都能合理映射的字段；第二轮再增加 rich constraints。

{  
"depot": {...},  
"vehicles": \[  
{"id": 0, "capacity": 100, "fixed_cost": 0, "skills": \[1\]}  
\],  
"jobs": \[  
{  
"id": 101,  
"demand": 10,  
"service": 300,  
"time_window": \[28800, 32400\],  
"required": true,  
"priority_class": "HIGH",  
"skills": \[1\]  
}  
\],  
"distance_matrix": \[\[...\]\],  
"duration_matrix": \[\[...\]\]  
}

建议同时定义统一 Solution Schema，使每个 adapter 输出完全相同的结果字段：routes、arrival_times、loads、unserved、solver_status、solver_runtime、wall_runtime、native_objective、seed。之后由 evaluator 重新计算统一 objective，而不是直接比较 native_objective。

# 6. Benchmark 数据与测试阶段

| **阶段**           | **数据**                           | **目的**                                            | **首轮是否必须** |
|--------------------|------------------------------------|-----------------------------------------------------|------------------|
| 0：Smoke test      | 自制 10–30 点小实例                | 验证 adapter、可行性检查、输出格式                  | 必须             |
| 1：CVRP            | CVRPLIB X 系列（先 100–500 点）    | 容量约束与基础解质量                                | 必须             |
| 2：VRPTW           | Solomon 100 点                     | 时间窗；便于快速重复                                | 必须             |
| 3：Large VRPTW     | Gehring & Homberger（200–1000 点） | 规模扩展与 60 s 内解质量                            | 必须             |
| 4：Pickup/Delivery | Li & Lim                           | 测试 shipment / pickup-delivery                     | 建议             |
| 5：Project-rich    | 自制 Stockholm/Voi-style 抽象实例  | priority、optional、skills、fixed cost、soft window | 必须             |
| 6：Traffic/Dynamic | 静态矩阵 + 分时段矩阵 + 事件注入   | traffic-aware / replanning                          | 第二轮           |
| 7：Realistic       | Amazon Last Mile / LaDe            | 真实分布验证；注意许可                              | 后续             |

| **不要一开始上 1000 点：**先保证 100 点实例在所有 adapter 上定义一致、结果能被统一 validator 复核。模型一致性未确认前，大规模 benchmark 只会放大调试成本。 |
|------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 7. 统一评价指标

每次运行至少保存以下指标。建议 CSV 一行对应一次 solver × instance × time_limit × seed。

| **指标组**  | **字段**                                       | **解释**                                   |
|-------------|------------------------------------------------|--------------------------------------------|
| 可行性      | feasible, violations                           | 任何 violation \> 0 的解不能参与质量排名   |
| 质量        | distance, duration, vehicles                   | 基础运营成本分量                           |
| Priority    | unserved_critical/high/normal/low              | 严格分层记录，不压成一个数                 |
| Time window | lateness_total, max_lateness                   | 硬窗应为 0；软窗单独计                     |
| BKS         | gap_to_bks                                     | 标准 benchmark： (cost-BKS)/BKS × 100%     |
| 速度        | wall_time_s, solver_time_s, time_to_best_s     | 统一用墙钟时间做主比较                     |
| 稳定性      | seed, mean/median/std                          | 随机算法至少 10 seed                       |
| 资源        | peak_rss_mb, threads                           | 避免“一个 solver 用 16 线程、另一个单线程” |
| 工程性      | LOC_adapter, setup_hours, unsupported_features | 作为选型的重要非性能指标                   |

# 8. OR-Tools 测试步骤

## 8.1 首轮目标

验证 OR-Tools RoutingModel 对容量、硬时间窗、optional/drop penalty、skills、pickup-delivery、fixed vehicle cost 与后续 replanning 的建模便利性；同时测量其在标准 CVRP/VRPTW 上的有限时间解质量。项目原文把 OR-Tools 作为 default 候选，主要理由就是 constraint coverage 与 warm-start/route-lock 方向。

## 8.2 执行步骤

1.  安装并固定 OR-Tools 9.15.x；先运行官方 VRP/VRPTW 示例确认环境。

2.  实现 ortools_adapter.py：读公共 Problem Schema，建立 RoutingIndexManager、RoutingModel、distance/time callbacks。

3.  先只实现 CVRP；在 10–30 点 smoke test 上用统一 validator 检查每个客户恰好服务一次、容量不超限。

4.  加入 Time Dimension 与硬时间窗，再跑 Solomon 小实例。

5.  加入 AddDisjunction 实现 optional jobs；不要在这一阶段把 priority penalty 当成严格字典序。

6.  加入 SetAllowedVehiclesForIndex / vehicle compatibility、pickup-delivery、fixed vehicle cost。

7.  设置统一 time limit；记录 first_solution_strategy、local_search_metaheuristic、线程相关配置。首轮只测试一套默认/推荐配置。

8.  执行 1 s / 10 s / 60 s 三档；对随机性相关配置至少运行多次。

9.  最后单独实现 strict-priority controller：Hard 作为硬约束，Critical→High→Normal→Low→SoftCost 分阶段重建模型或锁定上层最优值。

\# OR-Tools 运行配置示意（不是完整模型）  
search = pywrapcp.DefaultRoutingSearchParameters()  
search.time_limit.seconds = 60  
search.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC  
search.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH  
solution = routing.SolveWithParameters(search)

## 8.3 重点注意事项

- Hard constraints 不要用“大 penalty”模拟；容量、强制时间窗、车辆资格等应直接定义为可行域约束。

- AddDisjunction 的正 penalty + max_cardinality 表示“最多 k 个 active，并允许少选时付 penalty”，不要误当成天然 exactly-k。

- OR-Tools 的 native objective 是多个 cost mechanism 的标量组合。对外比较时必须由 evaluator 重新拆分计算。

- 严格 Priority 不应靠“10×”经验权重保证；单独跑 lexicographic controller。

- 不要首轮就尝试 true time-dependent VRP；先用静态矩阵保证 solver benchmark 可比。

# 9. PyVRP 测试步骤

## 9.1 首轮目标

验证 PyVRP 在标准 CVRP/VRPTW/optional-prize/pickup-delivery 等已支持问题上的解质量和速度。官方 0.14.0 benchmark 在多类 VRP 上报告了较低的平均 BKS gap，因此它应作为“质量基准”重点测试，而不是只作为备用工具。

## 9.2 执行步骤

10. 安装并固定 pyvrp==0.14.0；运行官方 quick-start 或 Solomon 示例。

11. 实现 pyvrp_adapter.py：公共 schema → Model/ProblemData；distance 与 duration 使用同一矩阵。

12. 先跑 CVRPLIB 与 Solomon；使用 MaxRuntime(1/10/60) 对齐时间预算。

13. 每个 instance 运行 10 个 seed；保存 Result 统计信息与 best solution。

14. 加入 optional clients / prize，验证与 OR-Tools drop penalty 对应的业务语义。

15. 加入 shipments（0.14.0 已加入完整 pickup/delivery 支持）后跑 Li & Lim 子集。

16. 对项目自定义 rich instance，逐项标记 supported / workaround / unsupported，不要为了“能跑”而悄悄删约束。

17. 将 PyVRP 结果统一转换到 Solution Schema，再由相同 evaluator 计算 feasibility 与 objective vector。

from pyvrp import Model  
from pyvrp.stop import MaxRuntime  
  
m = Model()  
\# add depot / vehicle type / clients / edges ...  
res = m.solve(stop=MaxRuntime(60), seed=0)  
best = res.best

## 9.3 重点注意事项

- PyVRP 也是以标量 cost 搜索，并不天然解决 Critical ≻ High ≻ Normal ≻ Low 的严格字典序。

- 不要只跑一个 seed；PyVRP 的搜索是随机化的。

- 使用外部 wall-clock 计时。PyVRP 的 MaxRuntime 主要限制搜索阶段，初始化/建模开销需要单独记录。

- 优先用稳定 0.14.0 做正式 benchmark；若实验 1.0 alpha 功能，必须分开报告，不能混入同一主表。

- 对 missing edge / unreachable 的处理要与公共 evaluator 约定一致，避免大常数语义差异。

# 10. VROOM 测试步骤

VROOM 适合做“快速、工程化、JSON API” baseline。项目原文重点关注其速度、priority 0–100、skills 与 shipments。当前 1.15.0 还增加了按车辆类型设置任务时间及相关成本的能力。首轮不建议深入修改 C++ 核心。

18. 准备 Docker；优先用 vroom-docker:v1.15.0。若尚未搭 OSRM/Valhalla，可先向 VROOM 提交 custom matrix，避免把路由引擎性能混入 solver benchmark。

19. 启动 vroom-express 并通过 /health 确认服务正常。

20. 实现 vroom_adapter.py：公共 Problem Schema → VROOM JSON；将 jobs、vehicles、skills、capacity、time_windows、priority、shipments 映射。

21. 首轮固定 exploration level、threads、timeout；在结果 metadata 中完整记录。

22. 用相同 CVRP/VRPTW 子集与 1/10/60 s 时间预算测试；注意 VROOM 的输入/输出 API 与其他库不同，要统一 wall time。

23. 在 rich instance 中重点看“priority”是倾向性还是严格层级；不要把 0–100 priority 误认为 lexicographic guarantee。

\# Docker 示例（需自行准备 conf；路由层可切 osrm/valhalla）  
docker run -dt --name vroom \\  
--net host \\  
-v \$PWD/conf:/conf \\  
-e VROOM_ROUTER=osrm \\  
ghcr.io/vroom-project/vroom-docker:v1.15.0

| **公平性：**如果用 VROOM 自带 routing engine 调用，而 OR-Tools/PyVRP 使用预先给定矩阵，结果会混入 routing latency 与不同矩阵差异。Solver benchmark 阶段建议全部使用同一 custom matrix。 |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 11. Timefold Solver 测试步骤

Timefold 的测试重点不是单纯追求 Solomon 上的最好 gap，而是验证项目非常关心的“严格多层 score + 复杂业务规则 + 后续实时变化”是否更自然。当前官方 latest 为 2.7.0，开源 core 使用 Apache 2.0，运行要求 Java 21+；部分多线程扩展属于 Enterprise。

24. 安装 JDK 21 与 Maven/Gradle；创建独立 timefold_adapter Java 项目，版本固定 2.7.0。

25. 先完成官方 quickstart，理解 @PlanningSolution、planning entities 与 ConstraintProvider。

26. 建立与公共 Problem Schema 对应的 Java domain model；不要在 Java 内重新定义不同的业务语义。

27. 首先用 Hard/Medium/Soft 三层 score 建一个最小 VRP 或 field-service 风格实例，验证“hard 永远压过 medium，medium 永远压过 soft”。

28. 若要映射 Critical/High/Normal/Low，可评估 BendableScore 或多层 score 设计，使 priority class 之间真正按字典序比较。

29. 使用相同 1/10/60 s wall-clock budget；记录启动/JVM warm-up 影响。对短时间 benchmark 建议先预热 JVM。

30. 再测试 ProblemChange / pinned planning entities 的概念性 replanning；这一部分与静态 benchmark 分表报告。

31. 使用 STEP_ASSERT 等诊断模式只做开发验证，不用于正式性能数据。

| **特别注意：**Timefold 与 Python solver 的 runtime 比较要做 JVM warm-up，否则 1 s 档会严重混入 JVM 启动/类加载开销。建议先运行 3–5 次 warm-up，再开始记录；同时仍保留“冷启动成本”作为工程指标单独统计。 |
|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 12. jsprit 补充测试步骤（Tier B）

jsprit 是 Java 的 rich-VRP toolkit。当前 2.0.0 要求 Java 21+。它值得作为补充对照，尤其因为 transport cost/time 接口可自定义，但其社区与现代 benchmark 生态相对前四者弱，因此不建议占用首周主力时间。

32. 在独立 Maven module 中引入 com.graphhopper:jsprit-core:2.0.0。

33. 实现 CVRP/VRPTW 的最小 adapter；使用同一 distance/duration matrix。

34. 验证 VehicleRoutingTransportCosts 是否能表达未来的 departure-time-aware cost 接口；此项先做 API feasibility，不要与静态 benchmark 混为一谈。

35. 选择少量 Solomon/CVRPLIB 实例跑 10/60 s，用于“Java rich-VRP toolkit”横向参考。

36. 如果解质量、文档维护或实现成本明显不优于 Timefold/VROOM，则停止深入。

# 13. Hexaly / Gurobi / Nextmv / LKH-3 的处理方式

项目原文把这些工具归为“学术限定或商业许可”的候选。首轮的目标不是全部深入实现，而是判断是否存在足够大的性能/功能收益，值得后续承担许可或集成成本。

| **工具** | **建议测试方式**                                                           | **停止条件/注意**                                               |
|----------|----------------------------------------------------------------------------|-----------------------------------------------------------------|
| Hexaly   | 如可获得免费试用/学术许可，复现其 CVRP/CVRPTW 示例并在同一实例/60 s 下测试 | 厂商 benchmark 只能作参考；最终结论以自己环境为准               |
| Gurobi   | 做小/中规模 MIP baseline，尤其用于验证最优性或 lower bound                 | 大规模 VRP 不应默认用纯 MIP 与专用 heuristic 比速度；许可需确认 |
| Nextmv   | 如果团队考虑云端部署/商业服务，再评估其 API 与 workflow                    | 不要把云端网络延迟与本地 solver runtime 直接比较                |
| LKH-3    | 可作为某些经典 routing variant 的专用算法学术对照                          | 模型映射与许可边界需单独核实；不作为复杂业务规则主框架          |

# 14. 必须单独做的 Strict Priority 实验

这是项目原文方案中最需要实验验证的一点。原文以约 10× penalty 间隔表达 priority，但这并不能保证“一个 High 永远胜过任意数量 Normal”。因此必须构造专门的反例，而不是只看普通 benchmark。

| **Case** | **场景**                                            | **期望**                                              |
|----------|-----------------------------------------------------|-------------------------------------------------------|
| P1       | 1 个 High vs 20 个 Normal，资源只能服务一侧         | 严格层级应优先 High；10× weighted penalty 可能失败    |
| P2       | Critical 任务需要明显更长距离                       | 只要 hard 可行，Critical 不应因 distance 变大而被丢弃 |
| P3       | Critical 全部可服务；High 之间有不同 business value | 先固定 Critical 最优，再在 High 层内部按价值优化      |
| P4       | SoftCost 改善巨大但会损失 1 个更高层任务            | 严格 lexicographic 不允许这种交换                     |

建议正式目标写为：所有 hard constraints 定义可行域；在可行域内 lexmin(P_Critical, P_High, P_Normal, P_Low, SoftCost)。OR-Tools/PyVRP 若无原生层级 score，则使用外部 sequential controller；Timefold 则用原生分层 score 做对照。

\# Sequential lexicographic controller（概念伪代码）  
levels = \["CRITICAL", "HIGH", "NORMAL", "LOW"\]  
locked = {}  
for level in levels:  
model = build_model(problem, locked=locked, objective=("unserved", level))  
sol = solve(model)  
best = evaluate_unserved(sol, level)  
locked\[level\] = best  
  
model = build_model(problem, locked=locked, objective="soft_cost")  
final = solve(model)

# 15. 目标函数对齐：最容易做错的地方

不同 solver 的 native objective 含义不完全一致，因此“native objective 更小”并不能直接证明更好。建议所有结果都由 evaluator 重新计算一套公共 objective vector。

objective_vector = {  
"hard_violations": 0,  
"unserved_critical": 0,  
"unserved_high": 1,  
"unserved_normal": 3,  
"unserved_low": 0,  
"distance_m": 48213,  
"duration_s": 13620,  
"vehicles_used": 4,  
"lateness_s": 0,  
"overtime_s": 0  
}

标准 CVRP/VRPTW benchmark 可以使用其传统 BKS objective 做 gap；项目 rich instance 则优先报告上述向量，并在完全相同的 priority vector 下再比较 SoftCost。这样才符合严格字典序语义。

# 16. Traffic / Time-Dependent 功能应作为第二轮独立实验

项目原文提出“traffic 能否进入 search，而不是只在结果之后重算”这一研究问题。它不应该与第一轮静态 solver benchmark 混合，因为不同求解器对 time-dependent travel 的支持差异很大，会破坏公平性。

| **阶段** | **方法**                                                     | **目的**                                 |
|----------|--------------------------------------------------------------|------------------------------------------|
| T0       | 单一静态 duration matrix                                     | 建立所有 solver 公平 baseline            |
| T1       | 按早高峰/平峰/晚高峰提供不同静态矩阵，分别求解               | 观察 traffic-aware planning 的潜在价值   |
| T2       | Iterative re-evaluation：求解→按预计出发时刻换 bucket→再求解 | 三个月 PoC 的现实方案                    |
| T3       | True TDVRP / departure-time-dependent cost                   | 研究项；只对支持度较高的 solver 单独测试 |

| **不要混淆：**如果 jsprit/Timefold 更容易自定义 time-dependent cost，也不能直接用这一高级模型与 OR-Tools/PyVRP 的静态模型比较“谁更优”。应分别报告 capability 与同模型 benchmark。 |
|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 17. Benchmark Runner 与结果文件设计

\# experiments/configs/base.yaml  
instances:  
- data/converted/solomon/R101.json  
- data/converted/cvrplib/X-n101-k25.json  
solvers: \[ortools, pyvrp, vroom, timefold\]  
time_limits_s: \[1, 10, 60\]  
seeds: \[0,1,2,3,4,5,6,7,8,9\]  
threads: 1

\# results/raw/results.csv 建议字段  
solver,version,instance,variant,time_limit_s,seed,threads,  
feasible,wall_time_s,solver_time_s,time_to_best_s,peak_rss_mb,  
native_objective,distance,duration,vehicles_used,  
unserved_critical,unserved_high,unserved_normal,unserved_low,  
lateness,overtime,gap_to_bks,notes

自动化 runner 应负责：启动/调用 solver → 捕获 stdout/stderr → 保存原始 solution → 统一 validator → evaluator → 写 CSV。任何 solver crash、timeout 或无解都必须保留一行结果，不能在汇总时静默删除。

# 18. 三周执行计划（建议）

| **时间**  | **任务**                                                      | **完成标准**                                             |
|-----------|---------------------------------------------------------------|----------------------------------------------------------|
| Day 1–2   | 冻结环境、建立公共 schema、validator、2 个 smoke instances    | OR-Tools/PyVRP 能读同一 JSON 并输出统一 solution         |
| Day 3–5   | OR-Tools 与 PyVRP：CVRP + Solomon                             | 跑通 1/10/60 s；至少 10 seed；结果可复现                 |
| Day 6–7   | VROOM Docker + custom matrix adapter                          | 同一实例可比较；确认 priority/skills/shipments 映射      |
| Day 8–10  | Timefold Java 21 adapter + 分层 score 小实验                  | Hard/Medium/Soft 语义验证；JVM warm-up 流程固定          |
| Day 11    | jsprit 快速 feasibility；决定是否继续                         | 得到 API/性能初步结论                                    |
| Day 12–13 | Gehring & Homberger / Li & Lim 扩展                           | 观察 200–1000 点 scalability 与 pickup-delivery          |
| Day 14–15 | Strict Priority 专项实验                                      | 证明 10× penalty 的边界；实现 lexicographic baseline     |
| Day 16–17 | Project-rich instance：priority/skills/soft window/fixed cost | 形成 constraint coverage matrix                          |
| Day 18    | 复现实验、排除异常、补测                                      | 同配置重复结果一致；无静默失败                           |
| Day 19    | 汇总图表与结论                                                | solution quality/runtime/capability/engineering 四维比较 |
| Day 20–21 | 撰写 1:1 报告与推荐技术路线                                   | 能明确回答 Q1–Q4，并列出下一阶段风险                     |

# 19. 最终选型建议使用的评分框架

不要只按 benchmark gap 选 solver。对本项目，约束覆盖和可维护性与解质量同等重要。建议最终报告使用定量指标 + 非量化结论，但不要把主观分数伪装成客观性能。

| **维度**            | **建议观察内容**                                                        | **权重思路（内部使用）** |
|---------------------|-------------------------------------------------------------------------|--------------------------|
| Constraint coverage | time windows、optional、skills、shipments、vehicle profiles、soft rules | 最高                     |
| Solution quality    | BKS gap；rich instance lexicographic vector                             | 高                       |
| Runtime/scalability | 1/10/60 s，100/500/1000 点                                              | 高                       |
| Priority modelling  | strict hierarchy 是否自然、是否需要外部 controller                      | 高                       |
| Replanning          | warm start / pinned / partial solution / live change                    | 中高                     |
| Integration effort  | 语言、API、容器、adapter LOC、调试难度                                  | 中高                     |
| Licence/deployment  | Apache/MIT/BSD/商业限制、self-host                                      | 中                       |
| Observability       | 统计、日志、diagnostics、可复现性                                       | 中                       |

# 20. 每个候选的“停止深入”条件

Phase 0 的目标是做选择，而不是证明所有工具都能被改造成万能求解器。建议预先定义停止条件，防止陷入单个 solver 的长期调试。

| **候选**    | **建议停止深入的信号**                                                       |
|-------------|------------------------------------------------------------------------------|
| OR-Tools    | 若关键业务约束无法可靠表达，或严格 priority 的外部 controller 复杂度不可接受 |
| PyVRP       | 若 rich constraints 需要大量修改内部算法，且项目主要价值恰好来自这些规则     |
| VROOM       | 若 custom constraints/strict priority 无法表达，保留为速度 baseline 即可     |
| Timefold    | 若 Java 技术栈/建模工作显著拖慢团队，且分层 score 优势不足以抵消成本         |
| jsprit      | 若在解质量、维护活跃度或建模便利性上均没有明显补充价值                       |
| 商业 solver | 若许可/部署限制与项目 partner 使用目标冲突，或性能收益不足                   |

# 21. 常见错误与注意事项清单

- 把不同 solver 的 native objective 直接放在同一图里比较。

- 把 infeasible solution 的低 cost 当成好结果。

- OR-Tools 用 road-time matrix，而 PyVRP 用 Euclidean distance。

- PyVRP 只跑一次 seed，取最好结果；其他 solver 却跑固定 deterministic 配置。

- 一个 solver 允许多线程，另一个限制单线程，但没有记录。

- 把建模不支持的约束删掉后仍声称“求解相同问题”。

- 把 10× penalty 当成严格 priority 保证。

- 把 VROOM priority 0–100 或 PyVRP prize 当成严格 lexicographic 层级。

- 用 Big-M 时不检查 64-bit cost 上界与溢出风险。

- 在静态 solver benchmark 中混入 Valhalla/OSRM API 延迟。

- 没有保存原始 solution，导致无法复核异常结果。

- 版本升级后继续把新结果追加到旧表中，却不标记版本差异。

# 22. Phase 0 最终交付物

| **交付物**                     | **建议内容**                                                |
|--------------------------------|-------------------------------------------------------------|
| 1\. Reproducible repository    | 环境文件、adapters、runner、validator、数据转换脚本         |
| 2\. Solver capability matrix   | 每个约束：native / workaround / unsupported / 未测试        |
| 3\. Benchmark CSV              | 所有原始运行记录；不可只保留汇总                            |
| 4\. Benchmark report           | BKS gap、runtime、scalability、seed 稳定性                  |
| 5\. Strict priority report     | 10× penalty 反例；sequential lexicographic 与 Timefold 对照 |
| 6\. Recommendation memo        | 推荐 core solver、secondary solver、停止使用的候选及理由    |
| 7\. Next-phase experiment plan | traffic-aware 与 replanning 的独立实验设计                  |

| **建议的 Phase 0 决策形式：**最可能的结果不是“唯一赢家”，而是确定角色：例如 OR-Tools = constraint-heavy core，PyVRP = quality benchmark/standard-VRP engine，VROOM = fast API baseline，Timefold = hierarchical/replanning benchmark。只有实验结果证明某一工具足够覆盖全部需求时，才收敛为单 solver。 |
|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|

# 23. 你现在可以直接开始的最小执行序列

37. 今天：创建仓库、Python venv，安装 OR-Tools 9.15.x 与 PyVRP 0.14.0；写 20 点 CVRP JSON。

38. 明天：实现统一 validator 与 objective evaluator；跑 OR-Tools/PyVRP 1/10/60 s。

39. 第三天：导入 Solomon R101，加入 time windows；确认两个 adapter 使用完全相同 duration matrix。

40. 第四天：做 10 seed 自动化，并输出 results.csv；开始 CVRPLIB。

41. 第五天：构造 High-vs-Normal priority 反例，验证普通 penalty 不能保证 strict lexicographic。

42. 随后：按 VROOM → Timefold → jsprit 的顺序增加候选；每加入一个 solver，先通过 smoke + Solomon，再进入大规模 benchmark。

# 24. 参考基线与官方资料（截至 2026-09-29）

项目来源：Route Optimisation Engine: Idea & Research Directions（用户提供，7 页）。其中 Algorithm Track、solver table、benchmark datasets、traffic/replanning roadmap 是本执行方案的直接依据。

| **工具**        | **官方入口**                                       | **本方案使用的信息**                                 |
|-----------------|----------------------------------------------------|------------------------------------------------------|
| OR-Tools        | https://developers.google.com/optimization/routing | Routing/VRPTW/installation；GitHub release v9.15     |
| PyVRP           | https://pyvrp.org/                                 | stable v0.14.0；benchmark、installation、Model/solve |
| VROOM           | https://github.com/VROOM-Project/vroom             | v1.15.0；API、Docker、vroom-express                  |
| Timefold Solver | https://docs.timefold.ai/timefold-solver/latest/   | 2.7.0；Java 21+；Hard/Medium/Soft；service/library   |
| jsprit          | https://github.com/graphhopper/jsprit              | 2.0.0；Java 21+；rich VRP toolkit                    |
| Hexaly          | https://www.hexaly.com/vehicle-routing             | 商业/学术试用；vehicle routing 与 benchmarks         |

注：商业软件、云服务与学术专用工具的许可条件可能变化。在进入 partner use、对外发布或商业部署之前，需要重新核实当时有效的 license / terms。
