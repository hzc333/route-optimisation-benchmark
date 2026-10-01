package rob.timefold;

import java.util.Comparator;

/**
 * Ascending difficulty, used by FIRST_FIT_DECREASING to insert the hardest
 * visits first: required before optional, then higher priority class, then
 * larger demand. Without it the construction heuristic inserts in input
 * order, small low-priority visits fill the vehicles, and no single local
 * search move can later fit a bulky critical visit (capacity is hard).
 */
public class VisitDifficultyComparator implements Comparator<Visit> {
    private static final Comparator<Visit> ORDER = Comparator
            .comparing(Visit::isRequired)
            .thenComparing(Visit::getPriorityRank)
            .thenComparingInt(Visit::getDemand)
            .thenComparing(Visit::getId);

    @Override
    public int compare(Visit a, Visit b) {
        return ORDER.compare(a, b);
    }
}
