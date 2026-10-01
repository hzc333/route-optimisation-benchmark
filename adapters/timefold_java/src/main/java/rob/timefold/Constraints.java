package rob.timefold;

import static rob.timefold.RoutePlan.HARD_LEVELS;
import static rob.timefold.RoutePlan.SOFT_LEVELS;

import java.util.ArrayList;
import java.util.List;

import ai.timefold.solver.core.api.score.BendableScore;
import ai.timefold.solver.core.api.score.stream.Constraint;
import ai.timefold.solver.core.api.score.stream.ConstraintFactory;
import ai.timefold.solver.core.api.score.stream.ConstraintProvider;

/** Hard: shared-schema feasibility. Soft: unassigned value per level + cost. */
public class Constraints implements ConstraintProvider {
    /** Hard units per unassigned required visit, so search fills them first. */
    static final long REQUIRED_WEIGHT = 1_000_000L;

    private static BendableScore hard() {
        return BendableScore.ofHard(HARD_LEVELS, SOFT_LEVELS, 0, 1);
    }

    private static BendableScore soft(int level) {
        return BendableScore.ofSoft(HARD_LEVELS, SOFT_LEVELS, level, 1);
    }

    @Override
    public Constraint[] defineConstraints(ConstraintFactory f) {
        List<Constraint> out = new ArrayList<>(List.of(
                f.forEach(Vehicle.class)
                        .filter(v -> v.getCapacityExcess() > 0)
                        .penalize(hard(), Vehicle::getCapacityExcess)
                        .asConstraint("capacity"),
                f.forEach(Visit.class)
                        .filter(v -> v.getLateness() > 0)
                        .penalize(hard(), Visit::getLateness)
                        .asConstraint("timeWindow"),
                f.forEach(Vehicle.class)
                        .filter(v -> v.getOvertime() > 0)
                        .penalize(hard(), Vehicle::getOvertime)
                        .asConstraint("shiftEnd"),
                f.forEach(Visit.class)
                        .filter(Visit::isSkillMismatch)
                        .penalize(hard())
                        .asConstraint("skills"),
                f.forEachIncludingUnassigned(Visit.class)
                        .filter(v -> v.getVehicle() == null && v.isRequired())
                        .penalize(hard(), v -> REQUIRED_WEIGHT)
                        .asConstraint("requiredUnassigned"),
                f.forEach(Visit.class)
                        .penalize(soft(RoutePlan.COST_LEVEL), Visit::getDistanceFromPrevious)
                        .asConstraint("distance"),
                f.forEach(Vehicle.class)
                        .filter(v -> !v.getVisits().isEmpty())
                        .penalize(soft(RoutePlan.COST_LEVEL), Vehicle::getClosingCost)
                        .asConstraint("returnLegAndFixedCost")));
        // One constraint per soft level: the score weight must be constant.
        for (int level = 0; level < SOFT_LEVELS; level++) {
            final int lv = level;
            out.add(f.forEachIncludingUnassigned(Visit.class)
                    .filter(v -> v.getVehicle() == null && !v.isRequired() && v.getUnassignedLevel() == lv)
                    .penalize(soft(lv), Visit::getUnassignedAmount)
                    .asConstraint("unassignedLevel" + lv));
        }
        return out.toArray(Constraint[]::new);
    }
}
