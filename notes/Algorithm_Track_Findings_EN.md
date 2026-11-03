# Zicheng Huang

Last updated 12 Oct 2026. Full report and code: [link]. An independent validator re-simulates every route and checks every constraint, and all numbers here come from solutions that passed it. I did not trust what the solvers report about their own solutions.

## TL;DR

- **Core solver: PyVRP.** It had the best quality on every benchmark we ran. With 60 s on 1,000-stop instances it was 1.3% from the best known solution. VROOM was 21% away, OR-Tools 33% and Timefold Community Edition 133%.
- **Priorities: keep the "must / priority / nice to have" idea, but don't use 10x weights.** Weighted penalties, even exact stacked ones, regularly give up a HIGH stop that could have been served. Instead, a small controller around the solver solves one priority class at a time and locks it in (staged solving). This was the only approach that never gave up a HIGH stop it could have kept.
- **Traffic can go inside the search, even with PyVRP.** PyVRP only accepts a static matrix, so I make one copy of each stop per 90-minute time bucket. On a synthetic city this made 100% of plans on time, with no extra driving.
- **Other solvers:** VROOM is a fast baseline. OR-Tools is a fallback for small problems or constraints PyVRP cannot express. Timefold CE is not worth it for now.
- **Still open:** driver breaks during re-planning, plan stability, real Stockholm data, and Q4 (learned methods), which I have not tested yet.

## How I tested

- **Solvers:** OR-Tools 9.15, PyVRP 0.14, VROOM 1.15 (through pyvroom) and Timefold 2.7 Community Edition. I did not test jsprit.
- **Fair conditions:** all solvers ran on the same laptop with one thread each, pinned to the same performance cores, in random order. Each configuration ran with 10 seeds.
- **Standard benchmarks:** 56 Solomon instances (100 stops), 11 CVRPLIB X instances (100 to 1,000 stops) and 6 Gehring & Homberger instances (1,000 stops). That is 9,000 runs in total.
- **Sanity check:** all 216 official best known solutions pass our validator, and their cost matches the published value exactly. So our instance conversion and rounding are correct.

## Q1: Is OR-Tools, PyVRP or something else the better core?

The table shows the average gap to the best known solution (lower is better):

| Dataset | Time | PyVRP | VROOM | OR-Tools | Timefold CE |
|---|---|---|---|---|---|
| Solomon, 100 stops | 1 s | **0.75%** | 14.5% | 6.6% | 55.9% |
| Solomon, 100 stops | 10 s | **0.22%** | 2.5% | 3.1% | 28.1% |
| CVRPLIB X, 100–1,000 stops | 60 s | **0.59%** | 2.6% | 6.1% | 42.7% |
| G&H, 1,000 stops | 60 s | **1.32%** | 21.4% | 33.1% | 132.8% |

- **PyVRP never lost to OR-Tools or Timefold on a single instance.** It lost to VROOM on only 3 Solomon instances, at 10 s.
- **Tuning OR-Tools does not close the gap.** I gave OR-Tools and PyVRP the same tuning budget: 24 configurations each, scored on held-out test instances. The best OR-Tools configuration was the default one. The gap comes from the search method itself: OR-Tools is a general constraint solver, while PyVRP's search is built specifically for vehicle routing.
- **VROOM** is very fast and excellent on short routes. It is weak on long routes, and its time limit is not reliable (one run went 77 s over). It also has no "drop penalty" and no "must visit" flag.
- **OR-Tools** barely improves with more time (X instances: 7.4% at 10 s, 6.1% at 60 s). It also overruns its time limit at 1,000 stops. The default first-solution strategy in the docs (PATH_CHEAPEST_ARC) finds no solution on tight time windows, so we need PARALLEL_CHEAPEST_INSERTION.
- **Timefold CE:** the doc says "Key scaling features are Enterprise only", and we can now put a number on it. Without nearby selection, an Enterprise feature, quality collapses above about 500 stops. It also needs a JVM that stays running: with a cold JVM, only 98 of 560 runs found a feasible plan within 1 s.
- **One update to the solver table:** PyVRP indeed has no time-dependent travel built in, but a workaround works well (see Q3).

## Q2: Would I model priorities differently?

**Yes. Keep the three-level idea (hard, then priority, then soft cost), but don't use weights to enforce the priority level.**

The problem with penalties spaced about 10x apart:

- **10x spacing does not make one HIGH stop outweigh all NORMAL stops, only up to 10 of them.** Example: one large HIGH job against 20 small NORMAL jobs, with room for only one side. The weighted model keeps the 20 NORMAL jobs.
- **Weights interact with other costs.** If a vehicle's fixed cost is larger than all the penalties together, the weighted model drops every job.
- **Penalty values depend on the distance scale**, so the same table does not work for every partner.
- **Even an exact lexicographic objective is not enough.** I tried stacked penalties large enough to guarantee strict order, and Timefold's built-in score levels. Both still gave up HIGH stops. To fit one large HIGH job, the search has to remove several small jobs at once, and a single move cannot do that.

What works is **staged solving**. First solve for CRITICAL only and lock the result. Then add HIGH, starting from the previous plan (warm start), and so on down the classes. The last stage optimises cost. The table shows how often each approach gave up a HIGH stop that could have been kept (stress test with large high-priority jobs, 10 s):

| Approach | Runs that gave up a HIGH stop |
|---|---|
| PyVRP + staged | **0%** |
| Timefold + staged | **0%** |
| OR-Tools + staged | 7% |
| VROOM built-in priority (a weighted sum) | 39% |
| Timefold built-in score levels | 53% |
| PyVRP with 10x or stacked weights (2 s) | 99% |

Strict order vs weights is also a business decision, not only a technical one. If "priority" means strict order, we need the controller. If partners want a cost trade-off, the weights define that trade-off, and the dispatcher should see it explicitly.

## Q3: Can traffic go inside the search?

**Yes.** Test setup: a synthetic 20 x 20 km city with speeds in 15-minute buckets, slower near the centre and during rush hour. Each instance has 100 stops, 60% of them with 1-hour windows, on a 07:00–16:00 shift. I tested two congestion levels, moderate and heavy, with 30 s per run. Every plan is then re-timed in the "real" time-dependent traffic.

| Approach | On-time plans (moderate / heavy) | Driving time vs ignoring traffic |
|---|---|---|
| PyVRP, ignore traffic (average matrix) | 57% / 47% | baseline |
| PyVRP, plan with rush-hour matrix | 100% / 100% | +1.4% / +3.7%, and ETAs are 44–66% too high |
| PyVRP, plan then re-estimate times in a loop | 97% / 67% | +1.4% / +1.9% |
| Timefold, traffic inside the search | 100% / 100% | +14% (solver quality, see Q1) |
| **PyVRP + 90-minute time buckets** | **100% / 100%** | **+0.3% / −0.4%**, ETAs 2–3% conservative |
| OR-Tools + 90-minute time buckets | 100% / 100% | +15–17% |

**How the time buckets work:** each stop is copied once for every 90-minute bucket its time window touches, and the solver must pick exactly one copy. The travel time out of a copy is the worst case within that bucket. Choosing a copy means choosing when to serve the stop, so traffic becomes part of the search. Because traffic is FIFO, the plan stays on time as long as the driver does not start a stop earlier than planned. The cost is about 0.4 extra vehicles on average, and 100 stops grow to about 360 nodes.

This doesn't conflict with the "historical averages first, LightGBM second" plan. That plan decides where the travel times come from. The bucket method decides how the solver uses them.

**Caveats:** the traffic is synthetic, so the results may not reflect real city conditions. I also haven't tested 200–500 stops, where the node count grows into the thousands.

## Q4: Is a hybrid or learned approach worth trying?

**I haven't tested anything here yet.** My view so far: on 100-stop instances, PyVRP already reaches a 0.00% median gap in 10 s. So learned methods have little to add on static quality. Their room is in scale and in dynamic re-planning. I agree with the doc that neural solvers should not be the core. Ideas worth a small experiment later:

- LLM-generated heuristics (ReEvo-style), for example for re-planning stability;
- natural language to constraint model (ARS-style), which could connect to the Interface track;
- learned travel times, which connect to the Data track.

## Proposal for Phase 1 (19 Oct – 8 Nov)

1. **Stack:** PyVRP with a staged priority controller behind our shared problem format. VROOM as a quick comparison, and OR-Tools as a fallback.
2. **End to end on Stockholm:** feed real travel time matrices (Valhalla or OSRM, from the Data track) into a real Stockholm instance, solve it with priorities and draw it on a map.
3. **Traffic:** PyVRP with 90-minute time buckets. A rush-hour matrix is the simplest safe fallback.
4. **Fix:** handling driver breaks and keeping plans stable when re-planning during the day.

**What I need from other tracks:**

- **Data:** travel time matrices per vehicle profile and time bucket, plus real variation in travel and service times.
- **Interface:** how a dispatcher chooses "strict priority" vs "cost trade-off".
- **Partners:** does Voi treat priority as strict?

## Limitations

- Everything ran on one laptop.
- The traffic is synthetic, with no real road network or real speeds.
- The priority stress tests use synthetic instances.
- VROOM and Timefold were not tuned, and Timefold Enterprise was not tested.
