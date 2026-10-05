package rob.timefold;

/**
 * Time-dependent travel times (Ichoua et al.): piecewise-constant speed per
 * time bucket, driven through bucket by bucket, so FIFO holds. Must match
 * traffic/model.py exactly, including floor(x + 0.5) rounding of each leg.
 */
public final class TravelTime {
    private final double[][] length;
    private final double[][] congestion;
    private final double[] profile;
    private final double vFree;
    private final double a;
    private final double b;
    private final int bucketS;

    public TravelTime(double[][] length, double[][] congestion, double[] profile,
                      double vFree, double a, double b, int bucketS) {
        this.length = length;
        this.congestion = congestion;
        this.profile = profile;
        this.vFree = vFree;
        this.a = a;
        this.b = b;
        this.bucketS = bucketS;
    }

    private double speed(int i, int j, long bucket) {
        double p = profile[(int) Math.floorMod(bucket, (long) profile.length)];
        return vFree * (1.0 - (a + b * congestion[i][j]) * p);
    }

    /** Seconds to drive i -> j departing at time t (seconds since 00:00). */
    public long travelTime(int i, int j, long departure) {
        double d = length[i][j];
        if (d <= 0) {
            return 0;
        }
        double t = departure;
        long k = Math.floorDiv(departure, (long) bucketS);
        while (true) {
            double v = speed(i, j, k);
            double end = (k + 1) * (double) bucketS;
            if (d <= v * (end - t)) {
                return (long) Math.floor(t + d / v - departure + 0.5);
            }
            d -= v * (end - t);
            t = end;
            k++;
        }
    }
}
