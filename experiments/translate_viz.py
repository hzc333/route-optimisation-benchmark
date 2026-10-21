"""Make the English explainer (docs/viz/explainer_en.html) from the Chinese one.

The page text above the script is written separately (docs/viz/_en_head.html);
the shared script is translated string by string below, and the run fails if
any Chinese character is left. Run after editing explainer.html:

    python -m experiments.translate_viz && python -m experiments.build_viz
"""

import re
from pathlib import Path

VIZ = Path(__file__).resolve().parents[1] / "docs" / "viz"

PAIRS = [
    ('"拥堵强度 p(t)"', '"Congestion level p(t)"'),
    ("<br>拥堵强度 ${p.toFixed(2)}", "<br>congestion ${p.toFixed(2)}"),
    ('"班次 07:00–16:00"', '"shift 07:00–16:00"'),
    ('"约 3 km 路段的行驶时间（分钟）"', '"Travel time of a ~3 km leg (minutes)"'),
    ("`出发 ${hhmm(T.arcs[0].times[k])}<br>`", "`Leave ${hhmm(T.arcs[0].times[k])}<br>`"),
    ("`${a.name}：${fmt(a.travel_s[k] / 60, 1)} 分钟`", "`${ARC(a.name)}: ${fmt(a.travel_s[k] / 60, 1)} min`"),
    ("`${a.name}（${fmt(a.length_m / 1000, 1)} km，受拥堵程度 ${a.exposure}）`",
     "`${ARC(a.name)} (${fmt(a.length_m / 1000, 1)} km, exposure ${a.exposure})`"),
    ("a.name, { \"text-anchor\": \"end\", class: \"lbl\" }", "ARC(a.name), { \"text-anchor\": \"end\", class: \"lbl\" }"),
    ("`车 ${i + 1}`", "`Veh ${i + 1}`"),
    ("<br>时间窗 ${hhmm(st.window[0])}", "<br>window ${hhmm(st.window[0])}"),
    ("`计划 ${hhmm(st.planned)} · `", "`planned ${hhmm(st.planned)} · `"),
    ("实际开始 ${hhmm(st.start)}", "actual start ${hhmm(st.start)}"),
    ("`<br>迟到 ${fmt((st.start - st.window[1]) / 60)} 分钟`", "`<br>late by ${fmt((st.start - st.window[1]) / 60)} min`"),
    ('"个站点迟到（这一份计划）"', '"late stops (this plan)"'),
    ('"辆车至少迟到一次"', '"vehicles late at least once"'),
    ("`重度拥堵下 ${agg.runs} 份同类计划中出现迟到的比例`", "`of ${agg.runs} such plans in heavy traffic have a late stop`"),
    ("`副本 ${i + 1}`, { \"text-anchor\": \"middle\"", "`copy ${i + 1}`, { \"text-anchor\": \"middle\""),
    ("`客户 ${B.job} 的 ${B.copies.length} 个副本（每个限定在一个 90 分钟时段里服务）`",
     "`Customer ${B.job}: ${B.copies.length} copies, each served only inside its 90-minute slot`"),
    ("`到 ${B.dest} 的行驶时间（分钟，约 ${fmt(B.length_m / 1000, 1)} km）`",
     "`Travel time to ${B.dest} (minutes, about ${fmt(B.length_m / 1000, 1)} km)`"),
    ("`副本服务时段 ${hhmm(c.lo)}–${hhmm(c.hi)}<br>交给 PyVRP 的耗时 ${fmt(c.planned_leg_s / 60, 1)} 分钟<br>真实耗时 ${fmt(tmin / 60, 1)}–${fmt(tmax / 60, 1)} 分钟`",
     "`Copy served ${hhmm(c.lo)}–${hhmm(c.hi)}<br>time given to PyVRP ${fmt(c.planned_leg_s / 60, 1)} min<br>true time ${fmt(tmin / 60, 1)}–${fmt(tmax / 60, 1)} min`"),
    ('"真实行驶时间（随出发时刻变化）"', '"True travel time (depends on departure)"'),
    ('"副本使用的保守值（时段内最慢）"', '"Conservative value per copy (slowest in slot)"'),
    ('[B.n_jobs, "个客户"]', '[B.n_jobs, "customers"]'),
    ('"个副本节点（90 分钟时段）"', '"copy nodes (90-minute slots)"'),
    ('["必选其一", "每个客户的副本组"]', '["exactly one", "copy per customer is visited"]'),
    ('static_mean: "全天平均", static_peak: "高峰车速", iterative: "迭代修正", bucketed_90: "时段复制 90′", bucketed_60: "时段复制 60′", td_search: "交通进搜索", static_free: "畅通车速"',
     'static_mean: "all-day average", static_peak: "peak speeds", iterative: "iterative re-estimate", bucketed_90: "slot copies 90′", bucketed_60: "slot copies 60′", td_search: "traffic in search", static_free: "free-flow speeds"'),
    ('"纵轴：准时计划比例"', '"Vertical: share of on-time plans"'),
    ('"多开的行驶时间 →"', '"extra driving time →"'),
    ("<br>准时 ${fmt(r.on_time * 100)}%（${r.runs} 次）<br>行驶时间 ", "<br>on time ${fmt(r.on_time * 100)}% (${r.runs} runs)<br>driving time "),
    ("<br>平均用车 ${fmt(r.vehicles, 2)}", "<br>vehicles used ${fmt(r.vehicles, 2)}"),
    ('["solver", "求解器"', '["solver", "Solver"'),
    ('["strategy", "做法"', '["strategy", "Approach"'),
    ('["on_time", "准时比例"', '["on_time", "On time"'),
    ('["travel_vs_ref_pct", "行驶时间 vs 参照"', '["travel_vs_ref_pct", "Driving vs reference"'),
    ('["planning_error_pct", "计划估计误差"', '["planning_error_pct", "Planning error"'),
    ('["vehicles", "平均用车"', '["vehicles", "Vehicles"'),
    ('["runs", "运行次数"]', '["runs", "Runs"]'),
    ('[["H", "重度拥堵"], ["T", "中度拥堵"]]', '[["H", "Heavy congestion"], ["T", "Moderate congestion"]]'),
    ('h.id === "HUB_S" ? "南仓" : "北仓"', 'h.id === "HUB_S" ? "Hub S" : "Hub N"'),
    ('`${sh.required ? "违停处理（必做）" : `挪车（${sh.cls}，价值 ${sh.value}）`}<br>${sh.id}`',
     '`${sh.required ? "Parking violation (mandatory)" : `Rebalancing (${sh.cls}, value ${sh.value})`}<br>${sh.id}`'),
    ("`${j.id} · ${j.cls} · 价值 ${j.value}", "`${j.id} · ${j.cls} · value ${j.value}"),
    ("`<br>必须 ${hhmm(j.tw[1])} 前完成`", "`<br>must be done by ${hhmm(j.tw[1])}`"),
    ("`<br>尽量 ${hhmm(j.soft)} 前（软截止）`", "`<br>ideally before ${hhmm(j.soft)} (soft deadline)`"),
    ('"<br>环保区内：只能电动车"', '"<br>inside the zone: electric vehicles only"'),
    ("`<br>区域组 ${j.group}：8 辆里任换 3 辆`", "`<br>zone group ${j.group}: swap any 3 of 8`"),
    (">区域组成员</span>", ">zone group member</span>"),
    (">违停处理（必做，取 → 送）</span>", ">parking violation (mandatory, pick up → drop)</span>"),
    (">挪车（虚线）</span>", ">rebalancing (dashed)</span>"),
    (">环保区（近似）</span>", ">environmental zone (approx.)</span>"),
    ("`${r.vehicle} · ${r.visits.length} 个访问<br>回仓 ${r.visits.filter((v) => v[0] === \"reload\").length} 次`",
     "`${r.vehicle} · ${r.visits.length} visits<br>${r.visits.filter((v) => v[0] === \"reload\").length} hub reloads`"),
    ("`${fmt(got)} / ${fmt(tot)}（丢 ${fmt(tot - got)}）`", "`${fmt(got)} / ${fmt(tot)} (lost ${fmt(tot - got)})`"),
    ("`阶段 ${i + 1} · ${st.stage}`", "`Stage ${i + 1} · ${st.stage}`"),
    ('["pyvrp_weighted", "对比：10 倍权重"], ["ortools_seqfull", "对比：OR-Tools 分阶段"]',
     '["pyvrp_weighted", "Compare: 10× weights"], ["ortools_seqfull", "Compare: OR-Tools stages"]'),
    ('pyvrp_weighted: "PyVRP + 原方案 10 倍权重（一次求解 60 秒）", ortools_seqfull: "OR-Tools + 分阶段（60 秒）"',
     'pyvrp_weighted: "PyVRP + original 10× weights (one 60 s solve)", ortools_seqfull: "OR-Tools + priority stages (60 s)"'),
    ("`PyVRP 分阶段 · 阶段 ${+key.slice(1) + 1}：${st.stage} 的奖励设为 M`",
     "`PyVRP priority stages · stage ${+key.slice(1) + 1}: ${st.stage} prize set to M`"),
    ('"个任务已锁定为必做"', '"jobs locked as mandatory"'),
    ('"次回仓补货"]', '"hub reloads"]'),
    ('"单换电完成"', '"swaps served"'),
    ('"软截止累计迟到"', '"total soft-deadline lateness"'),
    ('"单换电（分阶段最终）"', '"swaps (stages, final)"'),
    ('"空心 = 这一阶段没做"', '"hollow = not served in this stage"'),
    ('"路线（悬停高亮）"', '"route (hover to highlight)"'),
    ('drive: ["--rule-2", "开车"], serve: [null, "服务（按优先级着色）"], wait: ["--accent-soft", "等时间窗开门"], reload: ["--accent", "回仓补货"], break: ["--ink", "休息（排完后插入）"], load: ["--accent", "出车装货"]',
     'drive: ["--rule-2", "driving"], serve: [null, "service (coloured by priority)"], wait: ["--accent-soft", "waiting for a window"], reload: ["--accent", "hub reload"], break: ["--ink", "break (inserted after routing)"], load: ["--accent", "loading at start"]'),
    ('"休息窗口"', '"break window"'),
    ('evan: "电动货车", dvan: "柴油货车", bike: "自行车"', 'evan: "e-van", dvan: "diesel van", bike: "cargo bike"'),
    ('[[css("--rule-2"), "开车", "sq"], [css("--norm"), "服务（颜色 = 优先级）", "sq"], [css("--ink-2"), "取送滑板车", "sq"], [css("--accent"), "装货 / 回仓补货", "sq"], [css("--ink"), "休息", "sq"], [css("--accent-soft"), "等待", "sq"]]',
     '[[css("--rule-2"), "driving", "sq"], [css("--norm"), "service (colour = priority)", "sq"], [css("--ink-2"), "scooter pick-up / drop", "sq"], [css("--accent"), "loading / hub reload", "sq"], [css("--ink"), "break", "sq"], [css("--accent-soft"), "waiting", "sq"]]'),
    ("`${hhmm(S.due + st)} 前`", "`by ${hhmm(S.due + st)}`"),
    ('"不限（按晚 2 小时计）"', '"open (charged as 2 h late)"'),
    ("`副本 ${i + 1}：${label}`", "`copy ${i + 1}: ${label}`"),
    ("`奖励 −${fmt(S.late_cost * st / 1000)} SEK` : `全额奖励 ${fmt(base / 1000)} SEK`",
     "`prize −${fmt(S.late_cost * st / 1000)} SEK` : `full prize ${fmt(base / 1000)} SEK`"),
    ("`价值 3 的 HIGH 任务，10 倍权重下奖励 ${fmt(base / 1000)} SEK；迟到每秒扣 ${S.late_cost / 1000} SEK。五个副本只能选一个。`",
     "`A HIGH job of value 3 is worth ${fmt(base / 1000)} SEK under 10× weights; each second late costs ${S.late_cost / 1000} SEK. Only one of the five copies can be served.`"),
    ("`${r.vehicle} · 剩余 ${r.visits.length} 个访问`", "`${r.vehicle} · ${r.visits.length} visits left`"),
    ('`${it.id.startsWith("new_viol") ? "新违停（必做）" : "新紧急换电（CRITICAL，12:00 前）"}<br>${served ? "已排进新计划" : "原计划里没有"}`',
     '`${it.id.startsWith("new_viol") ? "New parking violation (mandatory)" : "New urgent swap (CRITICAL, by 12:00)"}<br>${served ? "in the new plan" : "not in the old plan"}`'),
    ("`${p.vehicle} · ${hhmm(p.avail)} 起可用<br>车上已占用：${p.initial_load.join(\" / \")}（满电位 / 旧电池 / 滑板车）`",
     "`${p.vehicle} · free from ${hhmm(p.avail)}<br>room already taken: ${p.initial_load.join(\" / \")} (charged slots / depleted / scooters)`"),
    ('[["new", "重新规划后"], ["old", "原计划剩余部分"]]', '[["new", "After re-planning"], ["old", "Rest of the old plan"]]'),
    ('[[css("--ink-3"), "10:00 前已走过", "sq"], [css("--ink"), "10:00 时车辆位置"], [css("--crit"), "新事件（实心 = 已排进计划）", "sq"], [css("--accent"), "新计划路线", "sq"], [css("--ink-2"), "原计划剩余（虚线）", "sq"]]',
     '[[css("--ink-3"), "driven before 10:00", "sq"], [css("--ink"), "vehicle position at 10:00"], [css("--crit"), "new event (filled = planned)", "sq"], [css("--accent"), "new routes", "sq"], [css("--ink-2"), "rest of old plan (dashed)", "sq"]]'),
    ('keep: "不重新规划", warm5: "热启动 5 秒", warm30: "热启动 30 秒", cold30: "从头求解 30 秒"',
     'keep: "no re-planning", warm5: "warm start 5 s", warm30: "warm start 30 s", cold30: "from scratch 30 s"'),
    ('events: "新事件", breakdown: "新事件 + 自行车抛锚"', 'events: "new events", breakdown: "new events + bike breakdown"'),
    ('["scenario", "场景"', '["scenario", "Scenario"'),
    ('["arm", "方式"', '["arm", "Approach"'),
    ('["runs", "次数"]', '["runs", "Runs"]'),
    ('["feasible", "可行"', '["feasible", "Feasible"'),
    ('["new_served", "新任务完成"', '["new_served", "New jobs served"'),
    ('["unserved_NORMAL", "丢 NORMAL"', '["unserved_NORMAL", "NORMAL lost"'),
    ('["kept_same_vehicle", "留在原车"', '["kept_same_vehicle", "Same vehicle"'),
    ('["old_dropped", "原任务被放弃"', '["old_dropped", "Old jobs dropped"'),
    ('"纵轴：超班超过 x 分钟的天数占比"', '"Vertical: share of days with more than x minutes of overtime"'),
    ('"x：全车队当天超班合计（分钟）"', '"x: total fleet overtime that day (minutes)"'),
    ('[[A, "--s2", "不加缓冲"], [B, "--s1", "规划时加 20% 缓冲"]]', '[[A, "--s2", "No buffer"], [B, "--s1", "20 % buffer when planning"]]'),
    ("`${name}：${fmt(pts[0][1] * 100)}% 的天超班`", "`${name}: overtime on ${fmt(pts[0][1] * 100)}% of days`"),
    ("`超班超过 ${fmt(v)} 分钟的天数<br>不加缓冲：${fmt(share(A.samples_overtime_min) * 100, 1)}%<br>加 20% 缓冲：${fmt(share(B.samples_overtime_min) * 100, 1)}%`",
     "`Days with over ${fmt(v)} min overtime<br>no buffer: ${fmt(share(A.samples_overtime_min) * 100, 1)}%<br>20 % buffer: ${fmt(share(B.samples_overtime_min) * 100, 1)}%`"),
    ('"整天准时 · 不加缓冲"', '"days fully on time · no buffer"'),
    ('"整天准时 · 加 20%"', '"days fully on time · 20 % buffer"'),
    ('"单换电 · 不加缓冲"', '"swaps · no buffer"'),
    ('"单换电 · 加 20%"', '"swaps · 20 % buffer"'),
    ('["arm", "求解器"', '["arm", "Solver"'),
    ('["buffer", "缓冲"', '["buffer", "Buffer"'),
    ('["served_jobs", "换电单数"', '["served_jobs", "Swaps"'),
    ('["moderate_on_time_prob", "整天准时（中等波动）"', '["moderate_on_time_prob", "Days on time (moderate)"'),
    ('["moderate_overtime_min_mean", "超班均值"', '["moderate_overtime_min_mean", "Mean overtime"'),
    ('["high_on_time_prob", "整天准时（高波动）"', '["high_on_time_prob", "Days on time (high)"'),
    ('"pyvrp:sequential_full": ["--s1", "PyVRP 分阶段"], "ortools:sequential_full": ["--s2", "OR-Tools 分阶段"], "pyvrp:weighted": ["--s3", "PyVRP 10 倍权重"]',
     '"pyvrp:sequential_full": ["--s1", "PyVRP stages"], "ortools:sequential_full": ["--s2", "OR-Tools stages"], "pyvrp:weighted": ["--s3", "PyVRP 10× weights"]'),
    ('S: "S · 约 160 站点", M: "M · 约 430 站点", L: "L · 约 850 站点"', 'S: "S · ~160 stops", M: "M · ~430 stops", L: "L · ~850 stops"'),
    ("`${ARMS[arm][1]} · ${sz} · ${r.time_limit_s} 秒<br>丢失 CRITICAL ", "`${ARMS[arm][1]} · ${sz} · ${r.time_limit_s} s<br>lost CRITICAL "),
    ("<br>完成换电 ${fmt(r.served_jobs, 1)}`", "<br>swaps served ${fmt(r.served_jobs, 1)}`"),
    ('"还丢了 HIGH 或 CRITICAL"', '"also lost HIGH or CRITICAL"'),
    ('["size", "规模"]', '["size", "Size"]'),
    ('["time_limit_s", "时间"', '["time_limit_s", "Time"'),
    ('["arm", "做法"', '["arm", "Approach"'),
    ('["unserved_CRITICAL", "丢 CRITICAL"', '["unserved_CRITICAL", "CRITICAL lost"'),
    ('["unserved_HIGH", "丢 HIGH"', '["unserved_HIGH", "HIGH lost"'),
    ('["served_jobs", "完成换电"', '["served_jobs", "Swaps served"'),
    ("` · 本页数据生成于 ${d.generated}`", "` · data generated ${d.generated}`"),
    ('"计算数据没有载入：请确认 viz_data.json 与本页一起发布。"', '"The computed data did not load: publish viz_data.json together with this page."'),
    ('toLocaleString("zh-CN"', 'toLocaleString("en-GB"'),
    # Labels that come from the data file.
    ("buttons(document.getElementById(\"t2-ctl\"), keys.map((k) => [k, T.plans[k].label])",
     "buttons(document.getElementById(\"t2-ctl\"), keys.map((k) => [k, PLAN_EN[k] || T.plans[k].label])"),
    ('const CLS_VAR = { CRITICAL: "--crit", HIGH: "--high", NORMAL: "--norm", LOW: "--low" };',
     'const CLS_VAR = { CRITICAL: "--crit", HIGH: "--high", NORMAL: "--norm", LOW: "--low" };\n'
     'const ARC = (n) => ({ "\\u5e02\\u4e2d\\u5fc3\\u8def\\u6bb5": "City-centre leg", "\\u5916\\u56f4\\u8def\\u6bb5": "Outer leg" }[n] || n);\n'
     'const PLAN_EN = { static_mean: "Plan on all-day average speed", bucketed_90: "Time-slot copies (90 min)" };'),
]

# The v1 legend counts classes with a Chinese full-width bracket.
PAIRS.append(("${c}（${V.jobs.filter((j) => j.cls === c).length}）", "${c} (${V.jobs.filter((j) => j.cls === c).length})"))


def main() -> None:
    page = (VIZ / "explainer.html").read_text(encoding="utf-8")
    script = page[page.index("<script>\n(() => {"):]
    for old, new in PAIRS:
        if old not in script:
            raise SystemExit(f"not found in script: {old[:70]}")
        script = script.replace(old, new)
    left = sorted({m for m in re.findall(r"[^\n]*[一-鿿][^\n]*", script)})
    if left:
        raise SystemExit("untranslated:\n" + "\n".join(left))
    head = (VIZ / "_en_head.html").read_text(encoding="utf-8")
    (VIZ / "explainer_en.html").write_text(head + "\n" + script, encoding="utf-8")
    print("wrote", VIZ / "explainer_en.html")


if __name__ == "__main__":
    main()
