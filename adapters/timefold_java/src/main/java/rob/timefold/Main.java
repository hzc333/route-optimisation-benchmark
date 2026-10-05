package rob.timefold;

import java.io.File;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryPoolMXBean;
import java.lang.management.MemoryType;
import java.time.Duration;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import ai.timefold.solver.core.api.solver.Solver;
import ai.timefold.solver.core.api.solver.SolverFactory;
import ai.timefold.solver.core.config.constructionheuristic.ConstructionHeuristicPhaseConfig;
import ai.timefold.solver.core.config.constructionheuristic.ConstructionHeuristicType;
import ai.timefold.solver.core.config.heuristic.selector.value.ValueSorterManner;
import ai.timefold.solver.core.config.localsearch.LocalSearchPhaseConfig;
import ai.timefold.solver.core.config.solver.EnvironmentMode;
import ai.timefold.solver.core.config.solver.SolverConfig;
import ai.timefold.solver.core.impl.solver.DefaultSolver;

/**
 * Usage: java -jar timefold-adapter.jar IN.json OUT.json
 *
 * IN  = {"problem": <shared Problem>, "options": {time_limit_s, seed, mode,
 *        penalties?, initial_routes?, warmup_s}}
 * OUT = {"routes": [{vehicle_id, job_ids}], "score", "solver_runtime_s",
 *        "time_to_best_s", "warmup_s", "jvm_startup_s", "load_s"}
 *
 * mode "lexicographic": unassigned optional jobs charged on their class's
 * soft level (native strict priority). mode "weighted": charged
 * penalties[class] * value on the cost level.
 */
public final class Main {
    private static final String[] CLASSES = {"CRITICAL", "HIGH", "NORMAL", "LOW"};
    private static final long NO_LIMIT = Long.MAX_VALUE / 4;

    public static void main(String[] args) throws Exception {
        double jvmStartup = ManagementFactory.getRuntimeMXBean().getUptime() / 1000.0;
        long t0 = System.nanoTime();
        ObjectMapper mapper = new ObjectMapper();
        JsonNode in = mapper.readTree(new File(args[0]));
        JsonNode problem = in.get("problem");
        JsonNode opt = in.get("options");
        double timeLimit = opt.get("time_limit_s").asDouble();
        long seed = opt.path("seed").asLong(0);
        double warmup = opt.path("warmup_s").asDouble(0);
        String construction = opt.path("construction").asText("default");
        double loadS = (System.nanoTime() - t0) / 1e9;

        if (warmup > 0) {  // JIT warm-up on a fresh copy; result discarded
            solver(seed + 1000, warmup, construction).solve(build(problem, opt));
        }

        RoutePlan plan = build(problem, opt);
        Solver<RoutePlan> solver = solver(seed, timeLimit, construction);
        long[] lastBestMs = {-1};
        solver.addEventListener(e -> lastBestMs[0] = e.getTimeMillisSpent());
        long ts = System.nanoTime();
        RoutePlan best = solver.solve(plan);
        double solveS = (System.nanoTime() - ts) / 1e9;

        List<Map<String, Object>> routes = new ArrayList<>();
        for (Vehicle v : best.getVehicles()) {
            if (!v.getVisits().isEmpty()) {
                Map<String, Object> r = new LinkedHashMap<>();
                r.put("vehicle_id", v.getId());
                r.put("job_ids", v.getVisits().stream().map(Visit::getId).toList());
                routes.add(r);
            }
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("routes", routes);
        out.put("score", String.valueOf(best.getScore()));
        out.put("solver_runtime_s", solveS);
        out.put("time_to_best_s", lastBestMs[0] < 0 ? null : lastBestMs[0] / 1000.0);
        out.put("warmup_s", warmup);
        out.put("jvm_startup_s", jvmStartup);
        out.put("load_s", loadS);
        out.put("java_peak_heap_mb", peakHeapMb());
        if (solver instanceof DefaultSolver<RoutePlan> ds) {
            out.put("move_evaluation_speed", ds.getMoveEvaluationSpeed());
        }
        mapper.writeValue(new File(args[1]), out);
    }

    /** Sum of heap pools' peak usage; the Python side only sees its own RSS. */
    private static double peakHeapMb() {
        long bytes = 0;
        for (MemoryPoolMXBean pool : ManagementFactory.getMemoryPoolMXBeans()) {
            if (pool.getType() == MemoryType.HEAP && pool.getPeakUsage() != null) {
                bytes += pool.getPeakUsage().getUsed();
            }
        }
        return bytes / 1048576.0;
    }

    /**
     * construction "default": Timefold's default phases (construction in input
     * order). "first_fit_decreasing": construction inserts the hardest visits
     * first (VisitDifficultyComparator), then the default local search.
     */
    private static Solver<RoutePlan> solver(long seed, double seconds, String construction) {
        SolverConfig config = new SolverConfig()
                .withSolutionClass(RoutePlan.class)
                .withEntityClasses(Vehicle.class, Visit.class)
                .withConstraintProviderClass(Constraints.class)
                .withEnvironmentMode(EnvironmentMode.NO_ASSERT)
                .withRandomSeed(seed)
                .withTerminationSpentLimit(Duration.ofMillis(Math.max(1, Math.round(seconds * 1000))));
        if ("first_fit_decreasing".equals(construction)) {
            config.withPhases(
                    new ConstructionHeuristicPhaseConfig()
                            .withConstructionHeuristicType(ConstructionHeuristicType.FIRST_FIT_DECREASING)
                            .withValueSorterManner(ValueSorterManner.DESCENDING),
                    new LocalSearchPhaseConfig());
        } else if (!"default".equals(construction)) {
            throw new IllegalArgumentException("construction: " + construction);
        }
        return SolverFactory.<RoutePlan>create(config).buildSolver();
    }

    private static Set<Integer> ints(JsonNode arr) {
        Set<Integer> s = new HashSet<>();
        if (arr != null) {
            arr.forEach(n -> s.add(n.asInt()));
        }
        return s;
    }

    private static int[][] matrix(JsonNode m) {
        int n = m.size();
        int[][] out = new int[n][n];
        for (int i = 0; i < n; i++) {
            JsonNode row = m.get(i);
            for (int j = 0; j < n; j++) {
                out[i][j] = row.get(j).asInt();
            }
        }
        return out;
    }

    private static double[][] doubles(JsonNode m) {
        int n = m.size();
        double[][] out = new double[n][];
        for (int i = 0; i < n; i++) {
            JsonNode row = m.get(i);
            out[i] = new double[row.size()];
            for (int j = 0; j < row.size(); j++) {
                out[i][j] = row.get(j).asDouble();
            }
        }
        return out;
    }

    /** options.td = traffic/model.py TDModel.to_json(), or absent for static travel. */
    private static TravelTime travelTime(JsonNode td) {
        if (td == null || td.isNull()) {
            return null;
        }
        double[] profile = new double[td.get("profile").size()];
        for (int k = 0; k < profile.length; k++) {
            profile[k] = td.get("profile").get(k).asDouble();
        }
        return new TravelTime(doubles(td.get("length_m")), doubles(td.get("congestion")), profile,
                td.get("v_free").asDouble(), td.get("a").asDouble(), td.get("b").asDouble(),
                td.get("bucket_s").asInt());
    }

    static RoutePlan build(JsonNode p, JsonNode opt) {
        Data data = new Data(p.get("depot").asInt(), matrix(p.get("distance_matrix")),
                matrix(p.get("duration_matrix")), travelTime(opt.get("td")));
        boolean lexicographic = "lexicographic".equals(opt.path("mode").asText("weighted"));
        JsonNode penalties = opt.path("penalties");

        List<Vehicle> vehicles = new ArrayList<>();
        Map<String, Vehicle> vehicleById = new HashMap<>();
        for (JsonNode v : p.get("vehicles")) {
            JsonNode shift = v.get("shift");
            Vehicle veh = new Vehicle(v.get("id").asText(), data, v.get("capacity").asInt(),
                    shift.get(0).asLong(), shift.get(1).asLong(), v.path("fixed_cost").asLong(0),
                    ints(v.get("skills")));
            vehicles.add(veh);
            vehicleById.put(veh.getId(), veh);
        }

        List<Visit> visits = new ArrayList<>();
        Map<String, Visit> visitById = new HashMap<>();
        for (JsonNode j : p.get("jobs")) {
            String cls = j.path("priority_class").asText("NORMAL");
            int classLevel = List.of(CLASSES).indexOf(cls);
            long value = j.path("value").asLong(1);
            int level = lexicographic ? classLevel : RoutePlan.COST_LEVEL;
            long amount = lexicographic ? value : penalties.path(cls).asLong(0) * value;
            JsonNode tw = j.get("time_window");
            boolean hasTw = tw != null && !tw.isNull();
            Visit visit = new Visit(j.get("id").asText(), data, j.get("location").asInt(),
                    j.path("demand").asInt(0), j.path("service").asLong(0),
                    hasTw ? tw.get(0).asLong() : 0, hasTw ? tw.get(1).asLong() : NO_LIMIT,
                    j.path("required").asBoolean(true), ints(j.get("skills")), level, amount,
                    CLASSES.length - 1 - classLevel);
            visits.add(visit);
            visitById.put(visit.getId(), visit);
        }

        JsonNode initial = opt.get("initial_routes");
        if (initial != null && !initial.isNull()) {
            for (JsonNode r : initial) {  // [[vehicle_id, [job ids]], ...]
                Vehicle veh = vehicleById.get(r.get(0).asText());
                for (JsonNode jid : r.get(1)) {
                    veh.getVisits().add(visitById.get(jid.asText()));
                }
            }
        }
        return new RoutePlan(vehicles, visits);
    }
}
