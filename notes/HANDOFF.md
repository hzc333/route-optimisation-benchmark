# 交接文档：Route Optimisation Engine · Algorithm Track

写于 2026-10-07 17:00，18:05 更新（时段复制实验已完成）；2026-10-11 更新（Voi 风格实例与 V2–V4 后续实验已完成）；2026-10-22 更新（英文报告、道路引擎对接、GitHub 上传准备）。写给没有任何上下文的新对话。用户用中文交流，喜欢简洁、通俗的总结。

---

## 1. 我们在做什么

用户是 Route Optimisation Engine 项目（斯德哥尔摩，首个目标场景 Voi 换电调度）**Algorithm Track** 的成员。Phase 0（2026-09-28 至 10-18）要回答项目原文中的四个问题，并在 **10 月 20 日那一周的 1:1** 上汇报：

1. 用 OR-Tools、PyVRP 还是别的求解器做核心，能否满足我们的约束？
2. 优先级是否要换一种建模方式，不用"三层分数 + 每级罚分大约 10 倍"？
3. 交通能否放进搜索过程，而不是排完路线再修正？
4. 有没有值得尝试的混合或学习方法？

背景文档在 `D:\route_opti\`：
- `Route_Optimisation_Engine_Idea_and_Research_Directions.md`（项目原文，英文）
- `Route_Optimisation_Algorithm_Solver_Benchmark_Plan_CN.md`（执行方案，中文）

## 2. 代码仓库与关键位置

仓库：`D:\route_opti\route-optimisation-benchmark`（本地 git，没有 remote，每一步都已提交）

| 路径 | 内容 |
|---|---|
| `docs/Phase0_Algorithm_Report_CN.md` | **主报告**（全部结论、数字、坑、局限性） |
| `docs/Phase0_Algorithm_Report_EN.md` | 主报告的完整英文版（章节编号、数字与中文版一致；中文版改了要同步） |
| `docs/DEV_NOTES_CN.md` | 本交接文档的公开版（去掉本机路径和协作偏好），随仓库提交 |
| `schema/models.py` | 统一的 Problem/Solution 格式（pydantic，是唯一的数据定义） |
| `evaluator/` | 统一 validator：重新模拟每条路线核对约束，不信任求解器自报的结果；还有目标向量和 BKS 差距计算 |
| `adapters/` | 四个求解器的 adapter（ortools、pyvrp、vroom、timefold）；`timefold_java/` 是 Java/Maven 项目 |
| `priority/lexicographic.py` | 严格优先级的几种策略（weighted / stacked / **sequential 分阶段控制器**） |
| `experiments/` | benchmark runner、汇总、调参、待机检测（`standby_check.py`）、`run_all.sh` |
| `traffic/` | 交通实验：时变行驶时间模型、合成实例、各种策略、**按时段复制客户**（`bucketed.py`）、runner |
| `roads/` | **与道路引擎（Valhalla）对接**：`build_matrices.py`（给道路引擎同学运行的独立脚本，只用标准库）、`export_stops.py`（生成坐标文件到 `roads/exchange/`）、`load_matrices.py`（把返回的 JSON 读进 Voi 实例）、英文说明 `README.md`；打包好的 `D:/route_opti/road_engine_handoff.zip` 已可转发。返回的 `*.matrices.json` 放到 `roads/exchange/results/`（不入库） |
| `rich/` | **Voi 风格复杂实例**：第二轮格式（`model.py`）、校验器（`validate.py`）、斯德哥尔摩生成器（`voi.py`，S/M/L）、PyVRP 和 OR-Tools 建模（`pyvrp_rich.py`、`ortools_rich.py`）、优先级控制器（`priority.py`）、实验：主实验 `run_experiment.py`、重新规划 `dynamic.py`、执行波动 `robust.py`、通用运行记录 `journal.py` |
| `results/summary/` | 所有结果 CSV（已提交）；`results/raw/` 是逐次运行的原始结果（不入库） |
| `D:\route_opti\tools\` | 免安装的 JDK 21 和 Maven |

计算过程图解网页（交通进入搜索 + Voi 换电日，10 个步骤，可交互）：中文 https://claude.ai/artifact/KTWGLunce4TuwtnzzqH1Xe ，英文 https://claude.ai/artifact/1KSYZaFNmejLeJHsLLtxds 。
- 文件说明和更新方法见 `docs/viz/README.md`。成品是 `docs/viz/walkthrough_zh.html` 和 `walkthrough_en.html`（离线可开），源码在 `docs/viz/src/`。
- 更新：`python -m experiments.export_viz`（重算数据，约 5 分钟）→ `python -m experiments.build_viz`（生成两个成品，同时翻译英文）→ 用 Artifact 工具把两个成品分别发布到上面两个链接（传 `url`，保持链接不变）。

组会演示文稿（14 页，中文）：https://claude.ai/artifact/EmH7gYGn3mTBnJtsj5A5Ba
- 封面上的 `[你的名字]` 还没替换。
- 交通实验那部分还没加进去。
- 只有用户本人能打开，需要用户自己在 Share 菜单里分享。

## 3. 环境与运行

- Python 3.13 虚拟环境：`.venv`。依赖锁定在 `environments/requirements-python.txt`（OR-Tools 9.15.6755、PyVRP 0.14.0、pyvroom 1.15.2 等）。
- Java：用之前先执行 `source environments/java_env.sh`。Timefold 的 jar 在 `adapters/timefold_java/target/`，构建命令是在该目录下执行 `mvn -q package`。
- 测试：`.venv/Scripts/python -m pytest`，共 358 个（其中 3 个按求解器能力跳过），约 3.5 分钟。
- 机器是 i5-13500H 笔记本，混合架构：**逻辑 CPU 0–7 是性能核，8–15 是效率核（慢一倍）**。正式实验一律固定在 CPU 0、2、4、6 上运行。

## 4. 已完成的工作（主要结论）

| 内容 | 结论 |
|---|---|
| 标准 benchmark（Solomon、CVRPLIB X、HG1000，共 9,000 次运行） | **PyVRP 全面最好**。1000 点：PyVRP 1.3%、VROOM 21%、OR-Tools 33%、Timefold 社区版 133%（与已知最优解的差距） |
| 调参实验（同等预算，同一天对照） | OR-Tools 的默认配置在 24 组中已是最佳；调参无法弥补差距。PyVRP 调出的参数会过拟合小题，保留默认 |
| 严格优先级（5,230 次运行） | 10 倍权重、VROOM 原生优先级、Timefold 原生分层评分、精确的堆叠权重，**都会丢掉本可保住的 HIGH 任务**。**分阶段控制器**（逐级求解并锁定 + 热启动）在 PyVRP 和 Timefold 上做到 0% |
| 交通实验 T0/T2/T3（540 次运行，合成城市） | 按自由流规划时 50–70% 的计划会迟到。Timefold 把交通放进搜索 100% 准时。PyVRP 按高峰矩阵规划也 100% 准时，只多 1–4% 行驶时间。迭代修正（T2）在中度拥堵下 97% 准时，重度下 70% |
| **按时段复制客户**（480 次运行，同一天对照） | **PyVRP + 90 分钟时段：两档拥堵都 100% 准时，行驶时间与"只用平均矩阵"持平**（比按高峰规划省 1–4%），平均多用约 0.4 辆车。OR-Tools 用同样方法也 100% 准时，但行驶时间多 15–21%。报告第 5.1 节 |
| **Voi 风格实例**（报告第 6 节，同一天约 520 次运行） | **PyVRP 能表达全部约束**：多维容量、成对取送、回仓补货、多仓库、车型差异 5 项原生；技能、任选 k 个、软截止、司机休息 4 项用替代方案，独立校验 0 违规。M 规模（约 430 个站点）：PyVRP + `sequential_full` 不丢 CRITICAL / HIGH，丢失的 NORMAL 价值只有 2.1；10× 权重是 17.5，OR-Tools 是 95。时间预算：M 15–60 s 够用，L（约 850 个站点）要 240 s。重新规划：5 s 就能把新来的必做任务全部排进去，但休息的替代方案会与新时间窗冲突，计划稳定性只有 30–40%。执行波动：不加缓冲时整天准时的概率只有约 5%，加 20% 缓冲后约 99% |
| 推荐技术路线 | **PyVRP 做核心 + 外部分阶段优先级控制器 + 时段复制处理交通**；OR-Tools 作为后备（处理 PyVRP 不支持的约束）；VROOM 作为快速对照；Timefold 暂不采用 |

全部细节见报告。所有结果都由统一 validator 重新核对；216 个官方最优解在我们的转换下逐位复现。

## 5. 当前状态

**没有正在运行的实验。** 最后完成的是 Voi 风格实例的全部实验：主实验 `voi_*_final.csv`、规模 `voi_*_scale.csv`、重新规划 `voi_dynamic_*.csv`、执行波动 `voi_robust_*.csv`，都在 `results/summary/`，结果写在报告第 6 节。`results/raw/voi.jsonl` 及对应的 `voi_runs.csv`、`voi_summary.csv` 是开发过程的记录（v1/v2 和旧的随机初始解），不作为最终结论。所有代码和结果都已提交到 git。

还没做的收尾工作：**组会演示文稿还没有加交通实验**（见第 6 节第 1 项）。

### 上传到团队 GitHub 仓库（2026-10-22）

- 用户要把算法部分放进**项目小组的 GitHub 仓库**的一个子文件夹（例如 `algorithm/`），只复制文件、不带提交历史，走新分支 + 合并请求。
- 准备好的上传版本在 `D:\route_opti\Algorithm\route-optimisation-benchmark`（用户把 github_upload 改名成了 Algorithm）（278 个文件，约 96 MB，已删掉 `.git`）。这是**纯英文版**：删掉了中文报告、中文开发笔记、中文执行方案、中文图解网页和翻译工具；英文图解网页改成独立源文件 `docs/viz/src/page_en.html`，`build_viz` 只生成 `walkthrough_en.html`。在该文件夹里跑测试：111 通过、32 跳过、0 失败。
- 原仓库保留中英双语，是工作主线。**上传版本是从原仓库导出后再删改的，原仓库以后有改动时需要重新导出**：`git clone` 原仓库 → 删 `.git` → 重复去中文的处理（删上述中文文件；`docs/viz` 只保留英文；README 去掉中文行和中文文档行；`results/metadata.json` 的电源方案名用英文）；另外删掉开发过程记录 `results/summary/voi_runs.csv`、`voi_summary.csv` 和后台启动脚本 `experiments/run_voi_followups*.cmd`；**道路引擎交接内容也不上传**：删掉 `roads/`、`tests/test_roads.py`、README 里相关的行、`.gitignore` 里矩阵文件的规则，以及 `rich/run_experiment.py` 的 `--matrices` 开关；**去掉一切能看出工作日期的内容**（用户不希望组员知道哪天做了什么）：英文报告开头的实验日期、§3.1 和 §10 里的具体日期（改成“主 benchmark / 调参那次 / 另一次运行”）；图解网页的生成日期（`viz_data.json` 的 generated、页面上的显示、`export_viz.py` 不再写入）；`results/metadata.json` 的 recorded_at（`record_env.py` 也不再写入）；6 个逐次运行结果表的 `t_start`/`t_end` 列；`standby_check.py` 示例里的日期）。
- 还没定的：题库数据（约 90 MB）是否放进团队仓库；团队仓库根目录 README 加一行指向算法文件夹；许可证。

- **已上传（2026-10-22）**：团队仓库 `KTH-Developer-Society/Project-Route_Optimisation`（私有，用户的工作账号 `zichenghuang-jimmy` 有 Maintain 权限），内容放在 `Algorithm/` 文件夹，分支 `algorithm-track`，提交标题 "Add Algorithm Track"（不带 Claude 署名，用户要求），提交者 `Zicheng Huang (Jimmy) <zicheng.huang@kthdeveloper.com>`。合并请求：https://github.com/KTH-Developer-Society/Project-Route_Optimisation/pull/1 （等组员审阅后合并）。
- 团队仓库的本地克隆在 `D:oute_opti	eam_repo`：只在这个仓库里设置了工作身份和 `gh auth git-credential` 登录方式，全局 git 设置没动。GitHub 命令行工具里有两个账号（工作 `zichenghuang-jimmy`、个人 `hzc333`），用 `gh auth switch -u <账号>` 切换；登录工作账号时 gh 的默认连接方式从 ssh 改成了 https，可用 `gh config set -h github.com git_protocol ssh` 改回。

## 6. 下一步

1. **更新组会演示文稿**：加一页交通结果（报告第 5.1 节）和一到两页 Voi 结果（报告第 6.2、6.3 节的表格），并更新第 13 页"下一步"。修改前先用 Artifact 工具 read 一下这份文稿。
2. **PyVRP 重新规划的两个缺口**（报告第 6.4 节）：休息改为在回仓时安排、或按车辆单独建模；目标里加入稳定性成本（换车罚分 / 锁定每辆车接下来的 N 站），然后重跑 `python -m rich.dynamic`。
3. **时段复制在更大规模上的表现**：200–500 个客户时节点会膨胀到上千个，需要验证 PyVRP 的求解质量。
（原第 3 项"构造 Voi 风格实例"已完成，见报告第 6 节。）
4. **第 4 题（混合/学习方法）完全没做**：先做文献梳理（例如 ReEvo、自然语言转 VRP），挑一个小实验。
5. **其他未测**：Li & Lim 标准取送题库；VROOM 和 Timefold 在 Voi 实例上没测；Voi 实例与交通时段复制的组合也没测。司机休息和重新规划已在 Voi 实例上测过（报告第 6.4 节）。
7. **用真实数据标定时间缓冲**（报告第 6.6 节：合成波动下需要 10–20%）。
6. **交通模型要用真实数据复核**：拿到 Data 方向的斯德哥尔摩速度数据后，替换合成模型重跑。

## 7. 踩过的坑：绝对不要再踩

### 运行环境（最耗时间）
- **笔记本会进入 Modern Standby，进程会被暂停。** 合盖、手动睡眠、用户离开都会触发；保持唤醒只能防止闲置休眠。长实验之前要提醒用户**插电、不要合盖**。所有实验都必须带 `experiments/standby_check.py` 的保护（检查待机事件 506/507 和是否插电）。
- **会话结束时，会话里启动的子进程会被一起杀掉**（包括 nohup）。长实验要用 WMI 独立启动：`Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine=...; CurrentDirectory=...}`。runner 必须**每跑完一次就写一次文件**，不能等全部跑完再写。
- **用电池时测出的时间不可比**：runner 会在每次运行前检查电源，用电池就暂停（`wait_for_ac`）。
- **E 核慢一倍**，所有计时实验必须固定在 P 核 0/2/4/6 上。
- **不同日期的结果会波动**：同一配置、同一 seed，不同天会差 0.1–5 个百分点。做对比时必须在**同一天**跑对照组。
- **正在跑实验时不要改 adapter 或重建 jar**：每次运行都会重新 import adapter。要测 Java 改动，就用 `ROB_TIMEFOLD_JAR` 指向另一份临时构建的 jar。
- **手动杀掉 runner 时，它会把正在启动的运行写成 ERROR 记录**（退出码 0xC0000142）。现在 resume 会重跑这类记录，但杀进程之前要先停掉外层的 bash 链。
- **用命令行字符串搜索进程会误计**：你自己执行的查询命令里也含有这个字符串，会被算进去。
- **用 Python heredoc 改文件时，`"\\n"` 字面量容易被写成真实换行**。改含换行符字面量的代码，用 Edit 工具。
- **Windows 下写文件要显式指定 `encoding="utf-8"`**，否则默认 GBK，遇到 `§` 这类字符会出错。
- **Bash 的安全检查偶尔会报临时故障**：重试一次即可，或者先做别的事。

### 求解器
- **OR-Tools**：
  - 文档默认的初始解策略 PATH_CHEAPEST_ARC 在紧时间窗题上找不到解，要用 PARALLEL_CHEAPEST_INSERTION。
  - `SetAllowedVehiclesForIndex` 的 Python 绑定在 9.15 不可用，改用 `VehicleVar(index).SetValues`。
  - 迭代局部搜索（ILS）必须显式设置 `ruin_strategies`，否则返回 `ROUTING_INVALID`。
  - 时变行驶时间所需的 `FloatSlopePiecewiseLinearFunction` 在 Python 中不可用。
  - 车辆数越多质量越差，要控制车队规模。
- **PyVRP 0.14**：
  - depot 和 client 要挂在 `Location` 上；路线迭代得到的是 `ScheduledActivity`。
  - 遇到大数值（固定成本、罚分超过 1e5）会返回不可行解，adapter 里已按成本量级调高 `max_penalty`。
- **VROOM（pyvroom）**：
  - 在 Windows + numpy 2 下，必须用 `np.uintc` 自己构造 `_vroom.Matrix`。
  - 时间上限不严格（最多超出 77 秒）。
  - 没有"放弃任务的代价"（drop penalty），也没有 required 标记。
- **Timefold**：
  - 社区版缺少邻近选择，大规模质量很差。
  - 必须预热 Java（冷启动时 1 秒内 82% 的运行无可行解）。
  - 优先级实验必须用"先排最难"的构造方式，而且要**显式设置** `ValueSorterManner.DESCENDING`，只写比较器会被静默忽略。
  - 标准 benchmark 必须用默认构造（`construction: default`），否则会退化成"先排体积最大的"。
  - 2 秒时限对它来说主要是在测 JVM 启动。

### Voi 复杂实例（rich/）
- **PyVRP 没有热启动时必须从空解起步**（`pyvrp.Solution(data, [])`）。默认的随机初始解把所有客户都塞进路线，几百个可选站点加上大额奖励时严重超载，L 规模 15 s 0/6 可行。已写进 `pyvrp_rich.solve`。
- **软截止的"复制客户"不能在更高等级的阶段启用**：会挤满清晨时段，导致 PyVRP 漏掉 CRITICAL。规则是从它所属等级的阶段起才建模（`rich/priority.py`）；如果只在最后一个阶段建模，迟到会多出近两倍。
- **分阶段控制器在大规模下必须保留低优先级任务**（`sequential_full`）：只放当前等级的旧版在 M 规模上丢失 NORMAL 价值 129，保留后只丢 2。
- **OR-Tools 有司机休息时，热启动后的局部搜索不再插入新节点**：分阶段改为每阶段从头求解，失败时才用热启动兜底。
- **PyVRP 热启动的计划必须满足互斥分组**，否则报 "Group visited more than once"；`pyvrp_rich` 会跳过冲突的访问。
- **重新规划的现场快照**："当前这一趟"要在下一次回仓处截断；已出发前往的下一站视为锁定。
- **运行记录里的 ERROR 行会被断点续跑当成"已完成"**：代码修好后要先删掉这些行（或整个 jsonl）再重跑。
- 改了求解代码后，旧结果要改名保留（例如 `_v1`、`_randinit`），新结果在同一天重跑，不要混在一起比较。

### 实验设计
- **BKS 的取整约定要对齐**：Solomon/HG 用 DIMACS 约定（截断到 1 位小数，乘以 10），X 用四舍五入。HG 200–800 点的 BKS 约定不同，所以没用。
- **调参要用留出的测试集**，否则会过拟合（PyVRP 就是例子）。
- **runner 写日志要 flush**：进程池里的 print 默认会被缓冲，看起来像没有进度。
- 换行：仓库用 `.gitattributes` 统一为 LF；Windows 上的 CRLF 警告可以忽略。

## 8. 用户偏好与协作方式

- 记忆文件在 `C:\Users\黄子澄\.claude\projects\D--route-opti\memory\`。用户授权了**自动执行**：每一步做完直接提交 commit，不必逐步征求同意。
- **改动系统设置**（电源、待机等）必须让用户自己做。
- 回复用中文，先给结论，语言通俗。
- 需要用户插电或做别的事时，要明确告知用户。
