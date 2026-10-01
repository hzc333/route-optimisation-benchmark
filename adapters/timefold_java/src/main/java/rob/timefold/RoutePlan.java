package rob.timefold;

import java.util.List;

import ai.timefold.solver.core.api.domain.solution.PlanningEntityCollectionProperty;
import ai.timefold.solver.core.api.domain.solution.PlanningScore;
import ai.timefold.solver.core.api.domain.solution.PlanningSolution;
import ai.timefold.solver.core.api.domain.valuerange.ValueRangeProvider;
import ai.timefold.solver.core.api.score.BendableScore;

/**
 * Score: 1 hard level, 5 soft levels = [CRITICAL, HIGH, NORMAL, LOW, cost].
 * In "lexicographic" mode unassigned optional visits are charged at their
 * class level (native strict priority); in "weighted" mode their penalty
 * goes to the cost level, like the OR-Tools / PyVRP adapters.
 */
@PlanningSolution
public class RoutePlan {
    public static final int HARD_LEVELS = 1;
    public static final int SOFT_LEVELS = 5;
    public static final int COST_LEVEL = 4;

    @PlanningEntityCollectionProperty
    private List<Vehicle> vehicles;

    @PlanningEntityCollectionProperty
    @ValueRangeProvider
    private List<Visit> visits;

    @PlanningScore(bendableHardLevelsSize = HARD_LEVELS, bendableSoftLevelsSize = SOFT_LEVELS)
    private BendableScore score;

    public RoutePlan() {
    }

    public RoutePlan(List<Vehicle> vehicles, List<Visit> visits) {
        this.vehicles = vehicles;
        this.visits = visits;
    }

    public List<Vehicle> getVehicles() { return vehicles; }
    public List<Visit> getVisits() { return visits; }
    public BendableScore getScore() { return score; }
    public void setScore(BendableScore score) { this.score = score; }
}
