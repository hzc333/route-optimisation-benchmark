# Algorithm Track · Phase 0 求解器评估报告

日期：2026-10-02 · 范围：OR-Tools 9.15.6755、PyVRP 0.14.0、VROOM 1.15（pyvroom 1.15.2）、Timefold Solver 2.7.0 社区版 · 执行方案：`Route_Optimisation_Algorithm_Solver_Benchmark_Plan_CN.md`

> 所有数字均由 `experiments/report.py` 从逐次运行记录计算（`results/summary/*_runs.csv`、`report_tables.md`），每个解都经统一 validator 重新模拟验证。jsprit 未测。

## 1. 结论（对应 Q1–Q4）

| 问题 | 结论 | 主要证据 |
|---|---|---|
| **Q1 核心求解器** | **PyVRP 作为主求解器**。VROOM 是很好的"快速 API baseline"，但长路线实例质量差、时间上限不可靠。OR-Tools 仅作为 PyVRP 不支持的约束（软时间窗、breaks）的后备，且需控制规模。**Timefold 社区版质量不足以做核心**（缺少企业版的 nearby selection），但其建模灵活性在 traffic/复杂规则上值得保留观察 | 73 个实例 × 各时间档，PyVRP 只在 3 个 Solomon 实例（10 s）上输给 VROOM，从未输给 OR-Tools 和 Timefold；1000 点：PyVRP 1.3%，VROOM 21%，OR-Tools 33%，Timefold 133%；同等预算调参后 OR-Tools 最佳配置仍是默认配置，差距不变（§3.1） |
| **Q2 严格 Priority** | 原方案的 **10× 权重不能保证严格优先级**；VROOM 原生 priority 是加权和；**Timefold 原生分层 BendableScore 目标正确，但搜索达不到最高层的最优**；即使精确的"堆叠权重"单次求解也不行。**采用外部 sequential lexicographic controller（带 warm start）**——它在 PyVRP 和 Timefold 上都做到 0% HIGH 层落后 | 10 s 对抗族：sequential（PyVRP、Timefold）0% 在 HIGH 层落后；Timefold native 53%，VROOM native 39% |
| **Q3 Traffic 进入搜索** | **要考虑交通，但不一定要放进搜索。** 忽略交通（自由流矩阵）时 50–70% 的计划至少有一个客户迟到；交通进入搜索（T3）在两档拥堵下都 100% 准时。PyVRP 不能做 T3，但用"高峰矩阵"做保守规划同样 100% 准时，只多 1–4% 行驶时间；迭代重估（T2）介于两者之间。PoC 建议：PyVRP + 高峰/分时段矩阵，T2 作为优化；严重拥堵 + 紧时间窗再考虑支持 T3 的求解器 | 合成交通实验（§5），540 次运行 |
| **Q4 learned/hybrid** | 不进入 Phase 1 主线。PyVRP 在 100 点实例 10 s 内中位 gap 已为 0.00%，learned 方法的提升空间主要在规模与动态场景，不在静态质量 | §3 |

## 2. 实验设置与公平性

- **机器**：i5-13500H（4 P 核 + 8 E 核）、15.7 GB、Windows 11，Windows 电源模式"最佳性能"、接通电源（`results/metadata.json`）。
- **核心绑定**：实测 E 核单线程慢约 2×，所有正式运行固定在 P 核 0/2/4/6（每物理核 1 线程），4 路并行；运行顺序随机打乱，各求解器承受相同的热/频率条件。
- **每次运行**独立子进程；单线程；外部墙钟计时；每配置 10 个 seed。OR-Tools 与 VROOM 是确定性的，seed 用于打乱 job 输入顺序，以同一协议测量其对输入顺序的敏感性。
- **电源与待机防护**：Windows Modern Standby 会暂停桌面进程（一次 Timefold "卡死"即由此引起）。每次运行记录是否接通电源；`experiments/standby_check.py` 读取 Kernel-Power 506/507 事件，凡与待机重叠或在电池下运行的结果都会被删除并重跑。Timefold 这一轮检测到 0 个受污染的运行。
- **数据与 BKS**：Solomon 56、CVRPLIB X 11（100→1000 点）、Gehring & Homberger 1000 点 6 个（每类一个），来自 PyVRP/Instances（CVRPLIB 镜像）。VRPTW 用 DIMACS 约定（距离截断到 1 位小数），X 用四舍五入。**216 个官方 BKS 解在我们的转换 + validator 下全部可行且成本逐位一致**，证明取整约定与模型对齐。
- **求解器配置**：
  - PyVRP 全默认。
  - OR-Tools = `PARALLEL_CHEAPEST_INSERTION` + `GUIDED_LOCAL_SEARCH`（依据见 §6.1）；文档默认 `PATH_CHEAPEST_ARC` 作为对照变体 `ortools_pca`。
  - VROOM = exploration level 5（CLI 默认）、单线程、`timeout` = 时间档；进程内调用 pyvroom，不含 HTTP/Docker 延迟。
  - Timefold = 社区版默认阶段（construction + late acceptance local search），list-variable 模型（与官方 quickstart 同构），`NO_ASSERT`，每次求解一个新 JVM，**计时前在同一 JVM 内先做 5 s 预热求解**（JIT warm-up，不计入预算；冷启动单独测，见 §6.4）。Java 端分数与 Python validator 逐位核对一致。
  - 四者目标均为总距离（+ 固定车辆成本）。
- **运行总数**：9 000 次，除 `ortools_pca` 的 130 次 `NO_SOLUTION` 外全部返回解；无崩溃、无被 runner 杀掉的超时。

## 3. 标准 benchmark 结果（gap to BKS，10 seeds 均值）

| 数据集 | 时间 | PyVRP | VROOM | OR-Tools | Timefold CE |
|---|---|---|---|---|---|
| Solomon 100 点 ×56 | 1 s | **0.75%** | 14.46%（中位 6.80%） | 6.63% | 55.94%（558/560 可行） |
| Solomon 100 点 ×56 | 10 s | **0.22%**（中位 0.00%） | 2.47% | 3.13% | 28.13% |
| Solomon 子集 ×12 | 60 s | **0.00%**（12/12 最好 seed 达到 BKS） | 1.54% | 0.80% | 2.61% |
| CVRPLIB X 100–1000 ×11 | 10 s | **1.31%** | 4.23% | 7.36% | 71.34% |
| CVRPLIB X 100–1000 ×11 | 60 s | **0.59%** | 2.61% | 6.07% | 42.74% |
| HG 1000 点 ×6 | 60 s | **1.32%** | 21.41% | 33.08% | 132.75% |

实例级胜负（按 10 seed 平均 gap；"优 / 平 / 劣"）：

| 对比 | Solomon 1 s | Solomon 10 s | Solomon 60 s | X 10 s / 60 s | HG1000 |
|---|---|---|---|---|---|
| PyVRP vs OR-Tools | 49 / 7 / 0 | 44 / 12 / 0 | 7 / 5 / 0 | 11/0/0 · 11/0/0 | 6 / 0 / 0 |
| PyVRP vs VROOM | 50 / 6 / 0 | 37 / 16 / 3 | 8 / 4 / 0 | 11/0/0 · 11/0/0 | 6 / 0 / 0 |
| PyVRP vs Timefold | 56 / 0 / 0 | 56 / 0 / 0 | 10 / 2 / 0 | 11/0/0 · 11/0/0 | 6 / 0 / 0 |
| VROOM vs OR-Tools | 16 / 4 / 36 | 30 / 12 / 14 | 3 / 4 / 5 | 11/0/0 · 11/0/0 | 5 / 0 / 1 |
| Timefold vs OR-Tools | 0 / 0 / 56 | 0 / 0 / 56 | 1 / 2 / 9 | 0/0/11 · 2/0/9 | 0 / 0 / 6 |

![Solomon](../results/plots/solomon_gap_by_class.png)
![X](../results/plots/x_gap_vs_size.png)
![HG1000](../results/plots/hg1000_gap.png)

要点：

- **PyVRP 全面领先**，差距随规模扩大；seed 间 gap 标准差 ≤ 0.34 个百分点，最稳定。
- **VROOM 的质量取决于路线长度**：短路线类（C1/C2）10 s 内 0.00–0.02%，并在 3 个 Solomon 实例（10 s：R108、RC102、RC108）上优于 PyVRP；长路线/宽时间窗类（R2、RC2）1 s 时 30–38%、10 s 时仍 ~6%。100 点实例约 7 s 自行结束。
- **OR-Tools 的 gap 随时间几乎不收敛**（X：10 s → 60 s 只从 7.4% 到 6.1%），1000 点规模基本失效（HG1000 全部 `LOCAL_OPTIMUM_NOT_REACHED`）。
- **Timefold 社区版收敛慢、规模扩展差**：100 点给足 60 s 能到 2.6%（并在 3 个实例上优于 VROOM），但 10 s 时 28%，500 点以上 40–150%。每秒约 4–11 万次移动评估，模型本身不是瓶颈；差距来自搜索——**限制候选移动到邻近客户的 nearby selection 是企业版功能**，社区版只能在所有位置中随机选，规模越大越低效（项目原文"Key scaling features are Enterprise only"在此得到量化）。
- **时间上限可靠性**：PyVRP 超时 ≤ 0.43 s，Timefold 求解超时 ≤ 2.6 s（另有 JVM 启动/预热开销，见 §6.4）。OR-Tools 在 HG1000 平均超 4.9 s、最坏 74 s；VROOM 在 X 60 s 档有 4 次跑了约 130 s。对有实时要求的调度 API，后两者需要外部看门狗。
- **车队规模敏感性**：HG 文件给出 250 辆车而 BKS 仅用 32–100 条路线。把车队限制为 1.2×BKS 路线数后，OR-Tools 33.1% → 18.5%，VROOM 21.4% → 19.7%，PyVRP 不受影响（1.32% → 1.28%）；Timefold 132.8% → 81.9%，但 18 次中 8 次违反时间窗（C1/C2 全部不可行）——紧车队下社区版连可行解都难以找到。
- **资源**：Python 进程峰值内存 < 280 MB；Timefold JVM 峰值堆 ≤ 424 MB（1000 点）。

### 3.1 调参实验：OR-Tools 的差距能否靠调参弥补？

协议（`experiments/tuning.py`，`run_tuning.sh`）：OR-Tools 与 PyVRP **同等调参预算**——各 24 组随机配置（第 1 组为主 benchmark 的默认配置），在 9 个**训练实例**（6 个 Solomon + 3 个不在测试集中的 X）× 2 seeds × 10 s 上评分（不可行记 100%）；最佳配置再在**留出的测试集**（其余 50 个 Solomon、11 个 X、6 个 HG1000，seeds 0–4）上与**同一天重跑的默认配置**对比。随机抽样没有覆盖"默认只改一处"的点，因此补充了每个求解器 4 个单项改动（OFAT）。

OR-Tools 搜索空间：初始解 {并行插入, 局部插入, Savings} × 元启发式 {GLS, 模拟退火, 两种禁忌搜索} × 9.15 新的迭代局部搜索（破坏重建：SISR / random walk / 邻近路线）× 邻域比例 × GLS λ × 一组默认关闭的 LNS 算子。PyVRP：邻居数、等待时间权重、历史长度、重启条件、扰动强度、exhaustive_on_best、可行目标比例。

| 测试集 | 求解器 | 默认（同一天） | 调参后（同一天） |
|---|---|---|---|
| Solomon 10 s | OR-Tools | 3.85% | 3.85%（最佳配置 = 默认） |
| | PyVRP | 0.25% | 0.24% |
| X 10 s / 60 s | OR-Tools | 7.72% / 6.48% | 同默认 |
| | PyVRP | 1.75% / 0.72% | 1.66% / 0.67% |
| HG1000 60 s | OR-Tools | 38.9% | 同默认 |
| | PyVRP | 1.61% | **3.42%** |

- **OR-Tools 的默认配置（并行插入 + GLS）在 24 组中排第 1**。最好的单项改动（默认 + 邻近路线破坏重建）在训练集上只从 4.33% 改善到 4.09%；SISR 无变化；LNS 算子组 6.28%、模拟退火 7.84% 更差；缩小邻域（0.1 / 0.3）明显变差。
- **差距不是参数造成的**：同一天 OR-Tools 与 PyVRP 的差距仍为 15×（Solomon）、4–10×（X）、24×（HG）；调参能带来的改善（≈0.2 个百分点）比差距（≈4 个百分点）小一个数量级。根本原因是搜索框架：OR-Tools 是通用约束编程 + 局部搜索，PyVRP 是专门为 VRP 设计的迭代局部搜索。
- **PyVRP 调参后的配置过拟合**：在 100–300 点训练集上选出的"邻居数 20"在 X 上略好，但在 1000 点上明显更差（3.42% vs 1.61%）。**保留 PyVRP 默认配置。**
- **日间波动**：同一配置、同一 seed，今天的结果普遍比 9 月 29 日稍差（OR-Tools Solomon 3.25% → 3.85%、HG 33.6% → 38.9%；PyVRP X 10 s 1.33% → 1.75%），说明机器状态不同。用满时间预算、仍在改进的求解器（OR-Tools）受影响最大。**跨日期的小差异不可直接比较，对比必须在同一时段内完成**（本节的对比均为同日）。

## 4. Strict Priority 实验

目标：`lexmin(P_CRITICAL, P_HIGH, P_NORMAL, P_LOW, SoftCost)`，P 为各层未服务 value 之和。比较：

- `weighted`：原方案，单次求解，class penalty 约 10× 间隔（NORMAL = 最远往返距离，按实例标定）；
- `weighted_fixed`：同上但用固定"米"单位表（100/1 000/10 000/100 000），模拟合作方直接配置；
- `stacked`：单次求解，penalty 逐层堆叠，保证每层严格压过所有下层 + 任何软成本（带 int64 溢出检查）；
- `sequential`：外部控制器，每层一次求解并锁定已服务集合，下一层从上一层解 **warm start**，最后一次求解优化软成本；
- `native`：求解器自带的优先级——VROOM 的 0–100 priority（先最大化已分配 priority 之和，映射 CRITICAL 100 / HIGH 10 / NORMAL 1 / LOW 0）；Timefold 的 `BendableScore` 分层（1 hard + [CRITICAL, HIGH, NORMAL, LOW, cost] 5 层 soft，即原生严格字典序）。

Timefold 在 priority 实验中使用**按难度排序的构造（先 required、再高优先级、再大 demand）**。不排序时，小件 LOW/NORMAL job 先把车装满，任何单步局部搜索移动都无法再塞进大件 CRITICAL（容量是硬约束），20 s 后仍会漏掉 CRITICAL。注意：仅设置比较器会被静默忽略，必须显式设置 `ValueSorterManner.DESCENDING`。

### 4.1 构造反例（5 seeds，2 s，命中严格最优向量的比例）

| Case | 场景 | OR-Tools / PyVRP weighted | weighted_fixed | stacked | sequential | VROOM native | Timefold native |
|---|---|---|---|---|---|---|---|
| P1 | 1 HIGH vs 20 NORMAL，容量只够一边 | **0%** | **0%** | 100% | 100% | **0%** | 100% |
| P2 | CRITICAL 在 60 km 外 | 100% | **0%** | 100% | 100%（Timefold 80%） | 100% | 100% |
| P3 | HIGH 层内按 value 取舍 | 100% | 100% | 100% | 100% | 100% | 100% |
| P4 | 服务最后 1 个 NORMAL 需多开一辆固定成本 1e6 的车 | **0%** | **0%** | 100% | 100% | 100% | 100% |

Timefold 的 weighted 在 P1 也"通过"，但那是因为它的局部搜索找不到"拿掉 1 个大件、换进 20 个小件"的移动——目标函数本身同样偏好丢掉 HIGH，属于碰巧。P4 中 weighted 实际**丢弃了全部 5 个 job**（第一辆车的固定成本就超过所有 penalty 之和）。P2 说明 penalty 数值依赖距离尺度。Timefold sequential 在 P2 的 80% 来自 2 s 预算被切成 5 段、每段 0.4 s 且是新 JVM（见 4.3）。

### 4.2 随机压力测试（2 s，30 实例 × 5 seeds）

"在 HIGH 层落后" = 与该实例上任一方法找到的最优优先级向量相比，第一个出现差异的层是 HIGH（即放弃了本可保住的 HIGH job）。

**对抗族**（高优先级 job 体积大、容量约为需求的 50%——即 P1 模式）：

| 求解器 | 策略 | 在 HIGH 层落后 | 平均未服务 CRITICAL | 平均未服务 HIGH | 平均未服务 NORMAL | 距离 |
|---|---|---|---|---|---|---|
| PyVRP | weighted | 98.7% | 0.00 | 3.57 | 11.2 | 5 411 |
| PyVRP | stacked | 98.7% | 0.00 | 3.72 | 10.8 | 5 552 |
| PyVRP | **sequential** | **0.0%** | 0.00 | **1.43** | 20.7 | 4 820 |
| OR-Tools | weighted | 32.7% | 0.00 | 1.76 | 18.9 | 5 081 |
| OR-Tools | stacked | 31.3% | 0.00 | 1.75 | 19.0 | 5 104 |
| OR-Tools | **sequential** | **12.0%** | 0.00 | **1.55** | 20.5 | 4 839 |
| VROOM | native | 39.3% | 0.00 | 1.83 | 18.0 | 5 031 |
| Timefold | native | 53.3% | 0.00 | 2.35 | 16.4 | 10 102 |
| Timefold | sequential（2 s 下失效） | 11.3%* | **4.79** | 5.42 | 6.8 | 9 737 |

\* Timefold sequential 有 84% 的运行在 CRITICAL 层就已落后：每阶段 0.4 s 的新 JVM 连构造都完成不了，阶段解被锁定后无法挽回。这是预算问题，不是方法问题——见 4.3。

**均匀族**（各类 demand 相同）中 OR-Tools、PyVRP、VROOM 没有任何运行在 CRITICAL/HIGH 层落后（Timefold 在 2 s 下有 1–11%，sequential 更多，原因同上）；VROOM native 在 94% 的运行中达到字典序最优（所有方法中最高），因为它总是先服务尽可能多的 job。优先级冲突只在"高优先级 job 更占资源"时出现，而这恰是 Voi 场景（高价值区域电池需求大）的常态。

### 4.3 10 s 对抗族（关键策略，每个求解器同样的更长预算）

2 s 对 Timefold 主要是在测 JVM 启动与 JIT（2 s 时约 2 800 次移动评估/秒，20 s 时约 5 万次/秒），因此对每个求解器的关键策略再跑一次 10 s：

| 求解器 | 策略 | 在 HIGH 层落后 | 平均未服务 HIGH | 平均未服务 NORMAL | 字典序最优比例 | 距离 |
|---|---|---|---|---|---|---|
| PyVRP | sequential | **0.0%** | 1.43 | 20.7 | 44.0% | 4 815 |
| Timefold | **sequential** | **0.0%** | 1.43 | 20.5 | **54.7%** | 5 145 |
| OR-Tools | sequential | 7.3% | 1.51 | 20.7 | 31.3% | 4 765 |
| VROOM | native | 39.3% | 1.83 | 18.0 | 34.0% | 5 030 |
| Timefold | native（BendableScore） | 53.3% | 2.35 | 15.9 | 39.3% | 6 733 |

结论：

1. 10× 权重在结构上就不是字典序（P1、P4），且依赖尺度（P2）；VROOM 的原生 priority 同样是加权和。
2. **把字典序写进目标函数不够**：无论是精确的 stacked 权重（PyVRP 99% 在 HIGH 层落后）还是 Timefold 原生的分层 BendableScore（10 s 仍 53%），单次元启发式搜索都到不了最高层的最优——要多放一个大件 HIGH，必须同时拿掉多个小件，而这超出单步移动的能力。
3. **分阶段求解在三个能接外部控制器的求解器上都 ≤ 7%，其中两个为 0%**（VROOM 没有 drop penalty 与 warm start，无法接控制器）；同一个 Timefold，由外部控制器驱动后从 53% 降到 0%，并给出最多的字典序最优解。严格优先级应由控制器实现，而不是依赖任何一个求解器的权重或分层。
4. Sequential 的代价在 NORMAL 层（约 20.5 vs 16–19）。一部分是保住体积大的 HIGH 必然让出的容量（正是严格优先级要求的取舍），另一部分来自"锁定已服务集合"（比真正字典序更严格）与时间切分。Phase 1 可通过"只锁数量不锁集合"、按层分配时间来缩小后者。
5. warm start 是必需的：不做 warm start 时，OR-Tools 的 sequential 在均匀族上约 21% 的运行在后续阶段重新装箱失败。
6. 以上数字在完整重跑间波动几个百分点（短时限下的正常噪声），结论不变。

## 5. Traffic 实验（Q3）：交通要不要进入搜索？

**设计**（`traffic/`）：合成城市 20 × 20 km、车场在西侧、每题 100 个客户（60% 有 1 小时时间窗），班次 07:00–16:00（路线必然经过早高峰）。行驶时间按 Ichoua 模型：每 15 分钟一档车速，越靠近市中心越堵，逐档积分（保证 FIFO）。两档拥堵：**中度 T**（市中心高峰约慢 2.5×，全天平均 1.11×）和**重度 H**（约慢 4.7×，平均 1.16×），各 10 题 × 3 seeds，每次 30 s，同一总预算。所有计划都放到"真实"的时变交通里重新核算（`traffic/evaluate.py`）。Timefold 的 Java 时变行驶时间与 Python 模型逐秒一致（有测试）。

| 求解器 | 做法 | 准时计划比例 T / H | 每个计划平均迟到客户 T / H | 行驶时间 vs PyVRP+平均矩阵 T / H | 计划对行驶时间的估计误差 T / H |
|---|---|---|---|---|---|
| PyVRP | T0 自由流矩阵 | 50% / 30% | 0.83 / 1.30 | −0.3% / −0.4% | **低估 8.0% / 10.6%** |
| PyVRP | T0 全天平均矩阵 | 50% / 40% | 0.87 / 0.90 | 参照 | −1.1% / −0.8% |
| PyVRP | **T0 高峰矩阵（保守）** | **100% / 100%** | 0 / 0 | +1.1% / +3.5% | 高估 44% / 66% |
| PyVRP | **T2 迭代重估** | 97% / 70% | 0.03 / 0.30 | +1.0% / +1.6% | −0.9% / −1.9% |
| OR-Tools | T0 全天平均 | 53% / 50% | 0.63 / 0.73 | +4.5% / +4.2% | −1.3% / −1.2% |
| OR-Tools | T2 迭代重估 | 93% / 63% | 0.07 / 0.37 | +6.4% / +8.6% | −1.4% / −2.6% |
| Timefold | T0 全天平均 | 53% / 37% | 0.50 / 0.97 | +17.3% / +14.8% | −1.4% / −1.3% |
| Timefold | T2 迭代重估 | 93% / 87% | 0.07 / 0.13 | +23.9% / +30.3% | −0.5% / −1.7% |
| Timefold | **T3 交通进入搜索** | **100% / 100%** | 0 / 0 | +18.4% / +13.5% | 精确 |

"准时计划" = 一个计划里没有任何客户迟到、没有车辆超班。所有 540 次运行都有效（全部客户服务、容量满足），无待机/电池污染。

结论：

1. **忽略交通会出问题**：自由流规划低估行驶时间 8–11%，一半以上的计划至少有一个客户迟到；拥堵越重越明显。
2. **同一个求解器内，交通进入搜索（T3）效果最干净**：Timefold 从 53% / 37% 准时提升到 100% / 100%，行驶时间与它自己的静态计划基本持平（+1% / −1%）。它整体行驶时间偏高是社区版求解质量问题（§3），不是 T3 的代价。
3. **但用 PyVRP 也能做到 100% 准时**：按高峰矩阵保守规划，只多 1–4% 行驶时间（重度拥堵下平均多用约 0.4 辆车）。代价是计划严重高估时间（44–66%），ETA 不可直接给客户。
4. **迭代重估（T2）兼顾准确与成本**：PyVRP 估计误差 ≈1–2%、行驶时间 +1–2%，中度拥堵 97% 准时；重度拥堵下仍有 30% 的计划出现迟到，因为每轮重排都会改变出发时刻。
5. **能力**：只有 Timefold 能在 Python 栈里做 T3；OR-Tools 的 C++ 支持随时间变化的转移（cumul-dependent transit），但 9.15 的 Python 绑定未开放所需的 `FloatSlopePiecewiseLinearFunction`；PyVRP / VROOM 只有静态矩阵。

**建议**：PoC 阶段用 PyVRP + 保守（高峰或分时段上分位）矩阵保证准时，再用 T2 迭代给出准确 ETA 和较短路线；当 Voi 的真实数据显示"重度拥堵 + 紧时间窗"很常见时，再评估支持 T3 的求解器（Timefold 企业版，或经 C++ 使用 OR-Tools）。以上基于合成交通，需要用斯德哥尔摩真实速度数据复核。

## 6. 工程发现（选型时同样重要）

### 6.1 OR-Tools

- **文档默认 `PATH_CHEAPEST_ARC` 在紧时间窗上找不到可行初始解**：8 个 Solomon 实例（R101/102/103/105/106、RC101/102/105）在所有 seed、1 s 与 10 s 下均 `NO_SOLUTION`（R1 类 36%、RC1 类 27.5% 的运行）。`PARALLEL_CHEAPEST_INSERTION` 是唯一在 Solomon/X/HG 上都可行且接近最好的策略（基于 4 个实例的 6 策略对比，属于轻度调参，已披露）。
- **`SetAllowedVehiclesForIndex` 的 Python 绑定在 9.15 不可用**（拒绝所有序列类型），且传空列表语义为"允许所有车辆"。改用 `VehicleVar(index).SetValues(...)`。
- 大规模下 time limit 不可靠，车队规模强烈影响质量（§3）。

### 6.2 PyVRP

- **0.14 API 与旧文档/执行方案示例不同**：depot/client 挂在 `Location` 上，路线迭代得到 `ScheduledActivity`。
- **大数值尺度会返回不可行解**：罚分上限 `max_penalty = 1e5`/单位；固定成本或 prize 超过该量级时超载解反而"更便宜"。adapter 已将上限设为 `max(1e5, 10 × 最大成本系数)`。**任何 big-M 建模都必须检查这一点。**
- 不支持：skills（可用多 profile 矩阵变通，未测）、软时间窗、breaks、真正 time-dependent travel。

### 6.3 VROOM（pyvroom）

- **pyvroom 1.15.2 在 Windows + numpy 2 上无法设置矩阵**（`uint32` 缓冲区格式 `L` vs 绑定只接受 `I`）；adapter 用 `np.uintc` 自建 `_vroom.Matrix` 绕过（依赖私有模块，升级时需复查）。
- **没有 drop penalty、没有"必须服务"标记**：总是先最大化分配数量；这与"optional + penalty"的业务语义不同。
- **timeout 不严格**，小实例提前结束；原生支持 skills、breaks、shipments、多维容量。

### 6.4 Timefold（社区版 2.7.0）

- **必须作为常驻服务运行**：冷 JVM 在 Solomon 1 s 下只有 **98/560 次**给出可行解（JIT 前约 5 600 次移动评估/秒 vs 预热后约 4.3 万），1 s 内连构造都完成不了。每次请求启动新 JVM 不可行；生产中需常驻 JVM（如 SolverManager / Timefold 服务形态）。
- **构造顺序是业务语义的一部分**：优先级场景必须按难度排序构造（见 §4）；但在全部 required、同一优先级的标准实例上，排序退化为"大 demand 优先"，忽略地理与时间窗，Solomon 1 s / 10 s gap 从 55.9% / 28.1% 恶化到 100.3% / 44.7%（保留为对照变体 `timefold_ffd`）。因此标准 benchmark 用默认构造，priority 实验用排序构造。
- **企业版功能**：nearby selection、多线程求解为企业版；社区版在 500 点以上质量差距主要来自此。若考虑商业许可，需用企业版重测后再下结论。
- **建模体验**：约 480 行 Java（list variable + 声明式影子变量 + constraint streams），任意规则可直接写成约束，原生分层分数；这是四者中表达力最强的，但与 Python 主栈分离、需要 JVM 运维。
- 求解时间上限可靠（超时 ≤ 2.6 s）。

### 6.5 约束能力矩阵（本轮实测 / 文档）

| 约束 | OR-Tools | PyVRP | VROOM | Timefold |
|---|---|---|---|---|
| 容量、硬时间窗、班次 | ✅ 实测 | ✅ 实测 | ✅ 实测 | ✅ 实测 |
| Optional job / drop penalty | ✅ 实测（Disjunction） | ✅ 实测（prize） | ⚠️ 只有"尽量多分配" | ✅ 实测（soft 约束） |
| 必须服务（hard） | ✅ | ✅ | ❌ 只能靠 priority 倾向 | ✅ 实测（hard 约束） |
| 固定车辆成本 | ✅ 实测 | ✅ 实测（需 max_penalty 修正） | ✅ 实测 | ✅ 实测 |
| Skills / 车辆兼容 | ✅ 实测（VehicleVar） | ⚠️ 不支持；profile 变通未测 | ✅ 实测 | ✅ 实测 |
| 严格多层 priority | ❌ 需外部控制器 ✅ 实测 | ❌ 需外部控制器 ✅ 实测 | ❌ 原生为加权和；无法接外部控制器 | ⚠️ 原生分层目标正确但搜索不达；外部控制器 ✅ 实测 |
| Warm start | ✅ 实测 | ✅ 实测 | 文档支持（steps），未接 | ✅ 实测 |
| Pickup & delivery | 文档支持，未测 | 文档支持（0.14），未测 | 文档支持，未测 | 需自写约束，未测 |
| 软时间窗 | 文档支持，未测 | ❌ | ❌ | 可写成 soft 约束，未测 |
| Breaks | 文档支持，未测 | ❌ | 文档支持，未测 | 需自写，未测 |
| Time-dependent travel（交通进入搜索） | ⚠️ C++ 支持，Python 绑定不可用 | ❌（仅静态矩阵；T2 迭代 ✅ 实测） | ❌ | ✅ 实测（§5） |
| 可靠的时间上限 | ⚠️ 大规模超时 | ✅ | ❌ 最多超 77 s | ✅（但需常驻 JVM） |

## 7. 建议的技术路线

1. **Core = PyVRP + 外部 sequential lexicographic controller**（`priority/lexicographic.py` 已可用，含 warm start 和溢出检查）。
2. **VROOM 定位为快速 baseline / 对照**：适合短路线、"尽量多服务"类场景的快速估算；不做核心。
3. **OR-Tools 保留为 rich-constraint fallback**，仅在出现 PyVRP 无法表达的约束（软时间窗等）时使用，且限制规模、严格控制车队数、使用插入类初始解策略。
4. **Timefold 不进入 Phase 1 主线**：社区版在标准 VRP 上质量差距过大。它的价值在于"任意约束 + 可在搜索中做 time-dependent travel"（§5 中唯一做到 T3 且 100% 准时）；如果真实数据显示重度拥堵 + 紧时间窗常见，或业务规则超出 PyVRP 能力，再评估企业版（需许可，且需重测）。
5. **交通（§5）**：PoC 用 PyVRP + 保守（高峰或分时段上分位）矩阵保证准时，再用 T2 迭代重估给出准确 ETA；从第一天起记录真实行驶时间，用于标定交通模型。
6. **Voi 场景的约束需尽早验证 PyVRP 覆盖度**：换电车辆的电池容量（多维容量，PyVRP 支持）、车辆类型差异（profile）、软时间窗（不支持 → 需评估是否可用硬窗 + 优先级替代）。
7. 不采纳原方案中"约 10× penalty 即代表 priority"的写法；对外 API 以 priority class 表达，内部由控制器保证字典序。

## 8. 下一步

| 优先级 | 事项 |
|---|---|
| 高 | 构造 Voi 风格 rich 实例（斯德哥尔摩坐标、换电 + 调度、priority class、车型差异），跑 PyVRP + sequential 与其他求解器 |
| 高 | Traffic 复核：用斯德哥尔摩真实速度数据（Data 方向）替换合成交通模型，重跑 §5；测分时段上分位矩阵（介于平均与高峰之间）的准时率与成本 |
| 中 | Li & Lim pickup-delivery；PyVRP skills 的 profile 变通；VROOM warm start（steps） |
| 中 | sequential 改进：只锁数量、按层分配时间 |
| 低 | Timefold 企业版（nearby selection）重测；Timefold 常驻服务形态下的 time-dependent 原型；jsprit |

## 9. 局限性

- 单台笔记本；VROOM（exploration 5）与 Timefold（社区版默认阶段）未调参；OR-Tools 与 PyVRP 做了同等预算的随机搜索 + 单项改动（§3.1），覆盖有限但结论（默认配置已接近最佳）在两种方法下一致。
- 同一配置的结果存在日间波动（§3.1：Solomon 约 0.1–0.6 个百分点，HG1000 最多约 5 个百分点）。主 benchmark 中 OR-Tools / PyVRP / VROOM 在 9 月 29 日运行，Timefold 在 10 月 1–2 日运行；求解器之间的差距（多为数倍到数十倍）远大于这一波动，结论不受影响，但不同日期的小差异不应解读为改进或退化。
- HG 仅 1000 点、每类 1 个实例；200–800 点因可得 BKS 的目标约定不一致而未用。
- 车队敏感性只有 3 个 seed；priority 实验为合成实例，时限 2 s / 10 s。
- VROOM 通过 pyvroom 进程内调用；Timefold 每次新 JVM + 预热，均非生产服务形态。
- §3–§4 的结果为静态矩阵；§5 的交通为合成模型（Ichoua 型速度曲线、以市中心为拥堵核心），真实路网与速度分布可能改变各做法的差距；实时重规划性能未测。

## 复现

```bash
cd route-optimisation-benchmark
py -3.13 -m venv .venv && .venv/Scripts/python -m pip install -r environments/requirements-python.txt
source environments/java_env.sh && (cd adapters/timefold_java && mvn -q package)   # Timefold jar
.venv/Scripts/python -m data.download        # 实例 + BKS
bash experiments/run_all.sh                  # priority + 全部 benchmark + 图表（首次全量约 12 h，需接电源）
.venv/Scripts/python -m traffic.instances && .venv/Scripts/python -m traffic.run_experiment   # 交通实验（约 80 min）
.venv/Scripts/python -m pytest               # 340 个测试（3 个按能力跳过）
```
