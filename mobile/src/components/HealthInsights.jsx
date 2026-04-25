import { View, Text, StyleSheet } from "react-native";
import { COG, TYPE, S, CARD } from "../lib/brand";

/**
 * Per-member dynamic statistics card. Renders three views:
 *   - Compliance score (donut + percent)
 *   - Appointment status breakdown (stacked bar)
 *   - Care gap progress per measure (mini bars)
 *
 * All values derive from props so the parent can re-render in real time.
 */
export default function HealthInsights({ profile = {}, gaps = [], appointments = [] }) {
  // A measure is "covered" if either the gap is closed OR there is at least one Completed appointment for it.
  const completedMeasures = new Set(
    appointments.filter((a) => (a.status || "") === "Completed").map((a) => a.measure_id),
  );

  const isClosed = (g) =>
    ((g.gap_status || g.status || "").toLowerCase() === "closed") ||
    (g.is_open === false) ||
    completedMeasures.has(g.measure_id);

  // Total = open gaps received + measures we already covered via completed appts (de-duped)
  const openGapMeasures = new Set(gaps.map((g) => g.measure_id).filter(Boolean));
  const allMeasureIds   = new Set([...openGapMeasures, ...completedMeasures]);
  const totalGaps       = allMeasureIds.size || gaps.length;
  const closedGaps      = [...allMeasureIds].filter((mid) =>
    completedMeasures.has(mid) || gaps.find((g) => g.measure_id === mid && isClosed(g))
  ).length;
  const openGaps    = Math.max(0, totalGaps - closedGaps);
  const compliance  = totalGaps === 0 ? 100 : Math.round((closedGaps / totalGaps) * 100);

  const counts = appointments.reduce(
    (acc, a) => {
      const s = a.status || "Scheduled";
      if (s === "Scheduled") acc.scheduled++;
      else if (s === "Completed") acc.completed++;
      else if (s === "Cancelled") acc.cancelled++;
      else if (s === "No Show") acc.noshow++;
      else acc.scheduled++;
      return acc;
    },
    { scheduled: 0, completed: 0, cancelled: 0, noshow: 0 },
  );
  const apptTotal = appointments.length;

  // Per-measure progress: count open gaps vs total (open + completed appointments).
  const byMeasure = {};
  for (const g of gaps) {
    const id = g.measure_id || "—";
    byMeasure[id] = byMeasure[id] || { open: 0, total: 0, name: g.measure_name || id };
    byMeasure[id].total++;
    if (!isClosed(g)) byMeasure[id].open++;
  }
  // Also include measures that have completed appointments but no open gap left
  for (const a of appointments) {
    if ((a.status || "") !== "Completed") continue;
    const id = a.measure_id;
    if (!id || byMeasure[id]) continue;
    byMeasure[id] = { open: 0, total: 1, name: a.screening_name || id };
  }
  const measures = Object.entries(byMeasure).slice(0, 6);

  return (
    <View style={styles.card}>
      <Text style={styles.title}>Your health at a glance</Text>

      {/* Row 1 — compliance donut + label */}
      <View style={styles.row}>
        <Donut percent={compliance} />
        <View style={{ flex: 1, marginLeft: 16 }}>
          <Text style={styles.metric}>{compliance}%</Text>
          <Text style={styles.metricLabel}>Compliance score</Text>
          <Text style={styles.metricSub}>
            {closedGaps} of {totalGaps} care gap{totalGaps === 1 ? "" : "s"} closed
          </Text>
        </View>
      </View>

      {/* Row 2 — appointments stacked bar */}
      <Text style={styles.sectionLabel}>Appointments</Text>
      <View style={styles.bar}>
        <Segment value={counts.scheduled} total={apptTotal} color={COG.blueDark} />
        <Segment value={counts.completed} total={apptTotal} color={COG.green} />
        <Segment value={counts.cancelled} total={apptTotal} color={COG.grayMedium} />
        <Segment value={counts.noshow}    total={apptTotal} color={COG.red} />
        {apptTotal === 0 && <View style={[styles.barEmpty]} />}
      </View>
      <View style={styles.legend}>
        <Legend color={COG.blueDark}   label="Scheduled" value={counts.scheduled} />
        <Legend color={COG.green}      label="Completed" value={counts.completed} />
        <Legend color={COG.grayMedium} label="Cancelled" value={counts.cancelled} />
        <Legend color={COG.red}        label="Missed"    value={counts.noshow} />
      </View>

      {/* Row 3 — per-measure progress */}
      {measures.length > 0 && (
        <>
          <Text style={[styles.sectionLabel, { marginTop: S.md }]}>Screening progress</Text>
          {measures.map(([id, m]) => {
            const closed = m.total - m.open;
            const pct = m.total === 0 ? 0 : Math.round((closed / m.total) * 100);
            return (
              <View key={id} style={styles.measureRow}>
                <View style={{ flex: 1 }}>
                  <Text style={styles.measureName}>{m.name}</Text>
                  <View style={styles.measureBar}>
                    <View style={[styles.measureFill, { width: `${pct}%`, backgroundColor: closed > 0 ? COG.green : COG.tealLight }]} />
                  </View>
                </View>
                <Text style={[styles.measureCount, closed > 0 && { color: COG.green }]}>
                  {closed}/{m.total} {closed === m.total ? "✓" : ""}
                </Text>
              </View>
            );
          })}
        </>
      )}
    </View>
  );
}

// ── Donut (pure View, no SVG) ─────────────────────────────────────────────
function Donut({ percent = 0 }) {
  // Two halves rotated to create a donut. Cap at 100.
  const p = Math.max(0, Math.min(100, percent));
  // Right half: rotation maps 0..50 % => 0..180°
  const rightDeg = p <= 50 ? (p / 50) * 180 : 180;
  // Left half: rotation maps 50..100 % => 0..180°
  const leftDeg  = p <= 50 ? 0 : ((p - 50) / 50) * 180;

  return (
    <View style={donutStyles.outer}>
      <View style={donutStyles.bg} />
      {/* Right half */}
      <View style={[donutStyles.halfWrap, { transform: [{ rotate: `${rightDeg}deg` }] }]}>
        <View style={donutStyles.half} />
      </View>
      {/* Left half (only animates after 50%) */}
      <View style={[donutStyles.halfWrap, { transform: [{ rotate: "180deg" }] }]}>
        <View style={[donutStyles.halfWrap, { transform: [{ rotate: `${leftDeg}deg` }] }]}>
          <View style={donutStyles.half} />
        </View>
      </View>
      {/* Inner mask */}
      <View style={donutStyles.inner} />
    </View>
  );
}

function Segment({ value, total, color }) {
  if (total === 0 || value === 0) return null;
  const flex = value / total;
  return <View style={{ flex, backgroundColor: color }} />;
}

function Legend({ color, label, value }) {
  return (
    <View style={legendStyles.row}>
      <View style={[legendStyles.dot, { backgroundColor: color }]} />
      <Text style={legendStyles.label}>{label}</Text>
      <Text style={legendStyles.value}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { ...CARD },
  title: { ...TYPE.body, fontWeight: "700", marginBottom: S.md },
  row: { flexDirection: "row", alignItems: "center", marginBottom: S.md },
  metric: { fontSize: 32, fontWeight: "800", color: COG.primary, lineHeight: 36 },
  metricLabel: { fontSize: 13, fontWeight: "600", color: COG.grayDark, marginTop: 2 },
  metricSub: { fontSize: 11, color: COG.grayDark, marginTop: 4 },

  sectionLabel: {
    fontSize: 11, fontWeight: "700", color: COG.grayDark,
    textTransform: "uppercase", letterSpacing: 0.5, marginTop: S.sm, marginBottom: 6,
  },

  bar: { flexDirection: "row", height: 12, borderRadius: 6, overflow: "hidden", backgroundColor: COG.grayLighter },
  barEmpty: { flex: 1, backgroundColor: COG.grayLighter },
  legend: { flexDirection: "row", flexWrap: "wrap", marginTop: 8 },

  measureRow: { flexDirection: "row", alignItems: "center", paddingVertical: 6 },
  measureName: { fontSize: 12, fontWeight: "600", color: COG.primary, marginBottom: 4 },
  measureBar: { height: 6, backgroundColor: COG.grayLighter, borderRadius: 3, overflow: "hidden" },
  measureFill: { height: 6, backgroundColor: COG.tealLight },
  measureCount: { fontSize: 11, fontWeight: "700", color: COG.primary, marginLeft: 10, minWidth: 36, textAlign: "right" },
});

const donutStyles = StyleSheet.create({
  outer: { width: 88, height: 88, position: "relative" },
  bg: { position: "absolute", width: 88, height: 88, borderRadius: 44, backgroundColor: COG.grayLighter },
  halfWrap: { position: "absolute", width: 88, height: 88, borderRadius: 44, overflow: "hidden" },
  half: { position: "absolute", left: 44, width: 44, height: 88, backgroundColor: COG.tealLight },
  inner: { position: "absolute", left: 12, top: 12, width: 64, height: 64, borderRadius: 32, backgroundColor: COG.white },
});

const legendStyles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center", marginRight: 14, marginTop: 4 },
  dot: { width: 8, height: 8, borderRadius: 4, marginRight: 6 },
  label: { fontSize: 11, color: COG.grayDark, marginRight: 4 },
  value: { fontSize: 11, fontWeight: "700", color: COG.primary },
});
