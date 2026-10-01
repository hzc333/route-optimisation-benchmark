package rob.timefold;

import java.util.Set;

import ai.timefold.solver.core.api.domain.common.PlanningId;
import ai.timefold.solver.core.api.domain.entity.PlanningEntity;
import ai.timefold.solver.core.api.domain.variable.InverseRelationShadowVariable;
import ai.timefold.solver.core.api.domain.variable.PreviousElementShadowVariable;
import ai.timefold.solver.core.api.domain.variable.ShadowSources;
import ai.timefold.solver.core.api.domain.variable.ShadowVariable;

/** A job of the shared schema. Times follow the shared conventions: wait if
 *  early, service must *start* by twEnd, travel times exclude service. */
@PlanningEntity
public class Visit {
    @PlanningId
    private String id;
    private Data data;
    private int location;
    private int demand;
    private long service;
    private long twStart;
    private long twEnd;
    private boolean required;
    private Set<Integer> skills;
    /** Soft level (0-3 = class, 4 = cost) and amount charged when unassigned. */
    private int unassignedLevel;
    private long unassignedAmount;
    /** 3 = CRITICAL ... 0 = LOW: higher is more important (for sorting). */
    private int priorityRank;

    @InverseRelationShadowVariable(sourceVariableName = "visits")
    private Vehicle vehicle;
    @PreviousElementShadowVariable(sourceVariableName = "visits")
    private Visit previousVisit;
    @ShadowVariable(supplierName = "arrivalTimeSupplier")
    private Long arrivalTime;

    public Visit() {
    }

    public Visit(String id, Data data, int location, int demand, long service, long twStart, long twEnd,
                 boolean required, Set<Integer> skills, int unassignedLevel, long unassignedAmount,
                 int priorityRank) {
        this.id = id;
        this.data = data;
        this.location = location;
        this.demand = demand;
        this.service = service;
        this.twStart = twStart;
        this.twEnd = twEnd;
        this.required = required;
        this.skills = skills;
        this.unassignedLevel = unassignedLevel;
        this.unassignedAmount = unassignedAmount;
        this.priorityRank = priorityRank;
    }

    @ShadowSources({"vehicle", "previousVisit.arrivalTime"})
    public Long arrivalTimeSupplier() {
        if (vehicle == null) {
            return null;
        }
        if (previousVisit == null) {
            return vehicle.getShiftStart() + data.dur[data.depot][location];
        }
        Long prevDeparture = previousVisit.getDepartureTime();
        return prevDeparture == null ? null : prevDeparture + data.dur[previousVisit.location][location];
    }

    public Long getStartServiceTime() {
        return arrivalTime == null ? null : Math.max(arrivalTime, twStart);
    }

    public Long getDepartureTime() {
        Long start = getStartServiceTime();
        return start == null ? null : start + service;
    }

    public long getLateness() {
        Long start = getStartServiceTime();
        return start == null ? 0 : Math.max(0, start - twEnd);
    }

    public long getDistanceFromPrevious() {
        int from = previousVisit == null ? data.depot : previousVisit.location;
        return data.dist[from][location];
    }

    public boolean isSkillMismatch() {
        return vehicle != null && !vehicle.getSkills().containsAll(skills);
    }

    public String getId() { return id; }
    public int getLocation() { return location; }
    public int getDemand() { return demand; }
    public boolean isRequired() { return required; }
    public int getUnassignedLevel() { return unassignedLevel; }
    public long getUnassignedAmount() { return unassignedAmount; }
    public int getPriorityRank() { return priorityRank; }
    public Vehicle getVehicle() { return vehicle; }
    public void setVehicle(Vehicle vehicle) { this.vehicle = vehicle; }
    public Visit getPreviousVisit() { return previousVisit; }
    public void setPreviousVisit(Visit previousVisit) { this.previousVisit = previousVisit; }
    public Long getArrivalTime() { return arrivalTime; }
    public void setArrivalTime(Long arrivalTime) { this.arrivalTime = arrivalTime; }

    @Override
    public String toString() {
        return id;
    }
}
