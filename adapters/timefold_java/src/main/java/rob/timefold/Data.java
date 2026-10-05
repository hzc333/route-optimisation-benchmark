package rob.timefold;

/** Immutable problem data shared by all entities (location-indexed matrices). */
public final class Data {
    public final int depot;
    public final int[][] dist;
    public final int[][] dur;
    /** Non-null = time-dependent travel: replaces dur for times and dist as leg cost. */
    public final TravelTime td;

    public Data(int depot, int[][] dist, int[][] dur, TravelTime td) {
        this.depot = depot;
        this.dist = dist;
        this.dur = dur;
        this.td = td;
    }

    /** Travel time i -> j when leaving at {@code departure}. */
    public long legTime(int i, int j, long departure) {
        return td == null ? dur[i][j] : td.travelTime(i, j, departure);
    }

    /** Leg cost: distance for static problems, time-dependent travel time otherwise. */
    public long legCost(int i, int j, long departure) {
        return td == null ? dist[i][j] : td.travelTime(i, j, departure);
    }
}
