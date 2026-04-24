import { useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TextInput, TouchableOpacity, Alert, ActivityIndicator,
} from "react-native";
import { listAppointments, bookAppointment, getMe, cancelAppointment } from "../../src/lib/api";
import { COG, TYPE, FORM, BTN_FILLED, S, CARD } from "../../src/lib/brand";

export default function Appointments() {
  const [appts, setAppts] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [measureId, setMeasureId] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);

  const load = async () => {
    try {
      const [apptRes, meRes] = await Promise.all([listAppointments(), getMe()]);
      setAppts(apptRes.appointments || []);
      setGaps(meRes.open_gaps || []);
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const handleBook = async () => {
    if (!measureId || !date || !time) {
      Alert.alert("Missing info", "Please pick a screening, date, and time.");
      return;
    }
    setBooking(true);
    try {
      await bookAppointment({ measure_id: measureId.toUpperCase(), appointment_date: date, appointment_time: time });
      Alert.alert("Booking confirmed", "A confirmation email has been sent to you.");
      setMeasureId(""); setDate(""); setTime("");
      load();
    } catch (e) {
      Alert.alert("Unable to book", e.message);
    } finally {
      setBooking(false);
    }
  };

  if (loading) return (
    <View style={styles.center}><ActivityIndicator size="large" color={COG.primary} /></View>
  );

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: S.xl }}>
      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Manual booking</Text>
        <View style={styles.card}>
          <Text style={styles.cardHint}>
            Prefer a guided flow with map + nearby labs? Open the <Text style={{ fontWeight: "700" }}>Assistant</Text> tab.
          </Text>

          <Text style={[FORM.label, { marginTop: S.md }]}>Open care gaps</Text>
          <View style={styles.gapChips}>
            {gaps.length === 0
              ? <Text style={TYPE.tiny}>No open gaps</Text>
              : gaps.map((g, i) => (
                <TouchableOpacity
                  key={i}
                  style={[styles.chip, measureId === g.measure_id && styles.chipActive]}
                  onPress={() => setMeasureId(g.measure_id)}
                >
                  <Text style={[styles.chipText, measureId === g.measure_id && styles.chipTextActive]}>
                    {g.measure_id}
                  </Text>
                </TouchableOpacity>
              ))}
          </View>

          <Text style={[FORM.label, { marginTop: S.md }]}>Measure ID</Text>
          <TextInput style={FORM.input} placeholder="e.g. BCS" placeholderTextColor={COG.grayMedium}
            value={measureId} onChangeText={setMeasureId} autoCapitalize="characters" />

          <Text style={[FORM.label, { marginTop: S.md }]}>Date</Text>
          <TextInput style={FORM.input} placeholder="YYYY-MM-DD" placeholderTextColor={COG.grayMedium}
            value={date} onChangeText={setDate} />

          <Text style={[FORM.label, { marginTop: S.md }]}>Time</Text>
          <TextInput style={FORM.input} placeholder="HH:MM (24-hour)" placeholderTextColor={COG.grayMedium}
            value={time} onChangeText={setTime} />

          <TouchableOpacity
            style={[BTN_FILLED.container, { marginTop: S.lg }, booking && { opacity: 0.6 }]}
            onPress={handleBook} disabled={booking}
          >
            <Text style={BTN_FILLED.text}>{booking ? "Booking..." : "Confirm booking"}</Text>
          </TouchableOpacity>
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Your appointments <Text style={{ color: COG.grayDark, fontWeight: "400" }}>({appts.length})</Text></Text>
        <View style={styles.card}>
          {appts.length === 0 ? (
            <Text style={TYPE.body}>No appointments yet. Book one above or ask the assistant.</Text>
          ) : appts.map((a, i) => (
            <View key={i} style={[styles.apptRow, i === appts.length - 1 && { borderBottomWidth: 0 }]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.apptTitle}>{a.screening_name || a.measure_id}</Text>
                <Text style={styles.apptMeta}>{a.appointment_date} · {a.appointment_time}</Text>
                {a.lab_location ? <Text style={styles.apptLoc}>{a.lab_location}</Text> : null}
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <View style={[
                  styles.statusPill,
                  a.status === "Completed" && { backgroundColor: COG.green },
                  a.status === "Cancelled" && { backgroundColor: COG.grayMedium },
                  a.status === "No Show"   && { backgroundColor: COG.red },
                ]}>
                  <Text style={styles.statusText}>{a.status || "Scheduled"}</Text>
                </View>
                {(a.status === "Scheduled" || !a.status) && (
                  <TouchableOpacity
                    style={styles.cancelBtn}
                    onPress={() => {
                      Alert.alert(
                        "Cancel appointment?",
                        `${a.screening_name || a.measure_id} on ${a.appointment_date} at ${a.appointment_time}`,
                        [
                          { text: "Keep it", style: "cancel" },
                          { text: "Cancel", style: "destructive", onPress: async () => {
                            try {
                              await cancelAppointment(a.appointment_id);
                              load();
                            } catch (e) { Alert.alert("Error", e.message); }
                          }},
                        ]
                      );
                    }}
                  >
                    <Text style={styles.cancelText}>Cancel</Text>
                  </TouchableOpacity>
                )}
              </View>
            </View>
          ))}
        </View>
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.grayLightest },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: COG.grayLightest },
  section: { paddingHorizontal: S.lg, paddingTop: S.xl },
  sectionLabel: { ...TYPE.small, fontWeight: "700", color: COG.grayDark, marginBottom: S.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  card: { ...CARD },
  cardHint: { ...TYPE.tiny, color: COG.grayDark, lineHeight: 16 },
  gapChips: { flexDirection: "row", flexWrap: "wrap", gap: 6 },
  chip: {
    paddingHorizontal: 12, paddingVertical: 6,
    borderRadius: 999, borderWidth: 1, borderColor: COG.blueDark,
    backgroundColor: COG.white,
  },
  chipActive: { backgroundColor: COG.blueDark },
  chipText: { fontSize: 12, fontWeight: "700", color: COG.blueDark, letterSpacing: 0.3 },
  chipTextActive: { color: COG.white },
  apptRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  apptTitle: { fontSize: 15, fontWeight: "600", color: COG.primary },
  apptMeta: { fontSize: 12, color: COG.grayDark, marginTop: 2 },
  apptLoc: { fontSize: 11, color: COG.blueDark, marginTop: 2 },
  statusPill: {
    backgroundColor: COG.blueDark, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
  },
  statusText: { color: COG.white, fontSize: 10, fontWeight: "700", letterSpacing: 0.3 },
  cancelBtn: { marginTop: 6, paddingHorizontal: 8, paddingVertical: 2 },
  cancelText: { color: COG.red, fontSize: 11, fontWeight: "700" },
});
