package rob.timefold;

/** Immutable problem data shared by all entities (location-indexed matrices). */
public final class Data {
    public final int depot;
    public final int[][] dist;
    public final int[][] dur;

    public Data(int depot, int[][] dist, int[][] dur) {
        this.depot = depot;
        this.dist = dist;
        this.dur = dur;
    }
}
