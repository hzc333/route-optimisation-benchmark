package rob.timefold;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

import ai.timefold.solver.core.api.domain.common.PlanningId;
import ai.timefold.solver.core.api.domain.entity.PlanningEntity;
import ai.timefold.solver.core.api.domain.variable.PlanningListVariable;

@PlanningEntity
public class Vehicle {
    @PlanningId
    private String id;
    private Data data;
    private int capacity;
    private long shiftStart;
    private long shiftEnd;
    private long fixedCost;
    private Set<Integer> skills;

    @PlanningListVariable(allowsUnassignedValues = true)
    private List<Visit> visits = new ArrayList<>();

    public Vehicle() {
    }

    public Vehicle(String id, Data data, int capacity, long shiftStart, long shiftEnd, long fixedCost,
                   Set<Integer> skills) {
        this.id = id;
        this.data = data;
        this.capacity = capacity;
        this.shiftStart = shiftStart;
        this.shiftEnd = shiftEnd;
        this.fixedCost = fixedCost;
        this.skills = skills;
    }

    public long getCapacityExcess() {
        long load = 0;
        for (Visit v : visits) {
            load += v.getDemand();
        }
        return Math.max(0, load - capacity);
    }

    /** Back at the depot; shiftStart for an unused vehicle. */
    public long getReturnTime() {
        if (visits.isEmpty()) {
            return shiftStart;
        }
        Visit last = visits.get(visits.size() - 1);
        Long dep = last.getDepartureTime();
        return dep == null ? shiftStart : dep + data.dur[last.getLocation()][data.depot];
    }

    public long getOvertime() {
        return Math.max(0, getReturnTime() - shiftEnd);
    }

    /** Last leg back to the depot plus the fixed cost; 0 for an unused vehicle. */
    public long getClosingCost() {
        if (visits.isEmpty()) {
            return 0;
        }
        return data.dist[visits.get(visits.size() - 1).getLocation()][data.depot] + fixedCost;
    }

    public String getId() { return id; }
    public long getShiftStart() { return shiftStart; }
    public Set<Integer> getSkills() { return skills; }
    public List<Visit> getVisits() { return visits; }
    public void setVisits(List<Visit> visits) { this.visits = visits; }

    @Override
    public String toString() {
        return id;
    }
}
