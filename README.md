# Route Optimisation Benchmark

Algorithm Track（Phase 0）求解器测试与选型仓库。执行方案见上级目录
`Route_Optimisation_Algorithm_Solver_Benchmark_Plan_CN.md`。

**结果报告：[docs/Phase0_Algorithm_Report_CN.md](docs/Phase0_Algorithm_Report_CN.md)**；
生成的表格见 `results/summary/report_tables.md`，图见 `results/plots/`。

完整复现：`python -m data.download` 后运行 `bash experiments/run_all.sh`（约 4.5 h，4 个 P 核）。
单个实验：`python -m experiments.run_benchmark experiments/configs/<name>.yaml`（可断点续跑）；
strict priority：`python -m experiments.run_priority_tests`。

当前范围：**仅 Python 求解器**（OR-Tools、PyVRP）。VROOM / Timefold / jsprit 需要 Docker 或 JDK 21，后续再加。

## 环境

| 项 | 固定版本 |
|---|---|
| Python | 3.13.7（Windows 11, x64） |
| OR-Tools | 9.15.6755 |
| PyVRP | 0.14.0 |
| pyvroom（VROOM 1.15 C++ 核心的 Python 绑定，无需 Docker） | 1.15.2 |
| JDK（Temurin，免安装 zip，`D:\route_opti\tools`） | 21.0.12.1 |
| Maven（免安装 zip，`D:\route_opti\tools`） | 3.9.16 |

Java 工具只对当前 shell 生效：`source environments/java_env.sh`（bash）或
`. .\environments\java_env.ps1`（PowerShell）。Timefold 2.7.0 / jsprit 2.0.0 从 Maven Central 获取。

完整依赖锁定在 `environments/requirements-python.txt`，机器信息见 `results/metadata.json`。

```powershell
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r environments\requirements-python.txt
.venv\Scripts\python -m pytest            # 工具链 smoke test
.venv\Scripts\python environments\record_env.py   # 刷新 results/metadata.json
```

> 升级任何求解器版本后必须重新运行 `record_env.py`，且新结果不得追加到旧结果表（方案 §21）。

## 目录

```
environments/   依赖锁定、环境记录脚本
data/           raw（下载原件，不入库）/ converted（统一 schema JSON）/ bks
schema/         Problem / Solution JSON Schema
adapters/       各求解器 adapter：公共 schema -> 原生 API -> 公共 solution
evaluator/      统一 validator + objective vector 计算
experiments/    runner 与配置
results/        raw（逐次运行，不入库）/ summary / plots / metadata.json
tests/
```

## 公共 Schema 与评价器

- `schema/models.py` 是唯一数据源（pydantic）；`*.schema.json` 由
  `python -m schema.export_json_schema` 生成，测试会检查两者是否同步。
- 约定：距离/时间一律为非负整数（实数输入由 converter 缩放，系数记入 `meta.distance_scale`）；
  `duration_matrix` 只含行驶时间，服务时间挂在 job 上；允许早到等待，晚于窗口结束开始服务即 hard violation；
  车辆须在 `shift` 内出发并返回。首轮仅单 depot、单容量维度、纯配送。
- `evaluator.validate()` 不信任 solver 自报的时间/载重，按最早开始时刻重新模拟每条路线，检查：
  容量、时间窗、班次结束、skills、重复/未知 job 与车辆、必服务 job 未服务、adapter 报告的 unserved 与实际不一致。
- `evaluator.objective_vector()` 输出统一向量；`lex_key()` 按
  hard → unserved CRITICAL/HIGH/NORMAL/LOW → soft 项 严格字典序比较。
- Smoke 实例：`python -m data.generate_smoke` 生成 `data/converted/smoke/`（固定随机种子，按构造保证可行）。

## API 注意事项

- PyVRP 0.14 起 depot/client 需挂在 `Model.add_location(x, y)` 返回的 `Location` 上，
  `add_edge` 连接的是 `Location`；方案 §9 中的旧示例写法已不适用。
