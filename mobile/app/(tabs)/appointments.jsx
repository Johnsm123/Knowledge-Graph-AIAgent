import { useEffect, useState, useCallback } from "react";
import {
  View, Text, ScrollView, StyleSheet, TouchableOpacity, Alert, ActivityIndicator, Modal, Platform,
} from "react-native";
import { useFocusEffect } from "expo-router";
import { listAppointments, bookAppointment, getMe, cancelAppointment } from "../../src/lib/api";
import { subscribeRealtime } from "../../src/lib/realtime";
import { COG, TYPE, FORM, BTN_FILLED, S, CARD } from "../../src/lib/brand";
import LabPickerModal from "../../src/components/LabPickerModal";

// Helper: build the next 30 calendar days (skipping past dates) for a simple
// in-app calendar grid. Avoids the native datetime-picker dependency so the
// build stays slim.
function buildDateGrid() {
  const out = [];
  const today = new Date();
  for (let i = 0; i < 30; i++) {
    const d = new Date(today);
    d.setDate(today.getDate() + i);
    out.push({
      iso: d.toISOString().slice(0, 10),
      label: d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" }),
      day: d.toLocaleDateString(undefined, { weekday: "short" }),
      dayNum: d.getDate(),
      monthShort: d.toLocaleDateString(undefined, { month: "short" }),
      isWeekend: d.getDay() === 0 || d.getDay() === 6,
    });
  }
  return out;
}

const TIME_SLOTS = [
  "09:00", "09:30", "10:00", "10:30", "11:00", "11:30",
  "12:00", "14:00", "14:30", "15:00", "15:30", "16:00", "16:30", "17:00",
];

function formatTimeAmPm(t) {
  const [h, m] = t.split(":");
  const hr = parseInt(h, 10);
  return `${hr > 12 ? hr - 12 : hr || 12}:${m} ${hr >= 12 ? "PM" : "AM"}`;
}

export default function Appointments() {
  const [appts, setAppts] = useState([]);
  const [gaps, setGaps] = useState([]);
  const [measureId, setMeasureId] = useState("");
  const [date, setDate] = useState("");
  const [time, setTime] = useState("");
  const [showMeasurePicker, setShowMeasurePicker] = useState(false);
  const [showDatePicker, setShowDatePicker]       = useState(false);
  const [showTimePicker, setShowTimePicker]       = useState(false);
  const [showLabPicker, setShowLabPicker]         = useState(false);
  const [pickedLab, setPickedLab]                 = useState(null);   // { place_id, name, address, lat, lng }
  const [loading, setLoading] = useState(true);
  const [booking, setBooking] = useState(false);
  const dateGrid = buildDateGrid();
  const selectedGap = gaps.find(g => g.measure_id === measureId);

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

  useEffect(() => {
    load();
    const unsub = subscribeRealtime(() => load());
    return () => unsub();
  }, []);

  useFocusEffect(useCallback(() => { load(); }, []));

  const handleBook = async () => {
    if (!measureId || !date || !time || !pickedLab) {
      Alert.alert("Missing info", "Please pick a screening, date, time, and lab before confirming.");
      return;
    }
    setBooking(true);
    try {
      await bookAppointment({
        measure_id:       measureId.toUpperCase(),
        appointment_date: date,
        appointment_time: time,
        lab_place_id:     pickedLab.place_id,
        lab_location:     `${pickedLab.name}${pickedLab.address ? " — " + pickedLab.address : ""}`,
        lab_name:         pickedLab.name,
        lab_address:      pickedLab.address || "",
        lab_lat:          pickedLab.lat,
        lab_lng:          pickedLab.lng,
      });
      Alert.alert("Booking confirmed", "A confirmation email has been sent to you.");
      setMeasureId(""); setDate(""); setTime(""); setPickedLab(null);
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

  const measureLabel = (g) => `${g.measure_id} · ${g.measure_name || g.measure_id}`;
  const dateLabel = date
    ? new Date(date).toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" })
    : "";

  return (
    <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: S.xl }}>
      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Book a screening</Text>
        <View style={styles.card}>
          <Text style={styles.cardHint}>
            Want a guided chat flow with nearby labs? Open the <Text style={{ fontWeight: "700" }}>Assistant</Text> tab.
          </Text>

          {/* Measure dropdown */}
          <Text style={[FORM.label, { marginTop: S.md }]}>Screening</Text>
          <TouchableOpacity
            style={styles.dropdownBtn}
            onPress={() => gaps.length > 0 ? setShowMeasurePicker(true) : Alert.alert("No open gaps", "You have no open care gaps right now — you're all caught up!")}
          >
            <Text style={[styles.dropdownText, !measureId && styles.dropdownPlaceholder]}>
              {selectedGap ? measureLabel(selectedGap) : (gaps.length === 0 ? "No open care gaps" : "Tap to select a screening")}
            </Text>
            <Text style={styles.dropdownCaret}>▾</Text>
          </TouchableOpacity>

          {/* Date dropdown */}
          <Text style={[FORM.label, { marginTop: S.md }]}>Date</Text>
          <TouchableOpacity style={styles.dropdownBtn} onPress={() => setShowDatePicker(true)}>
            <Text style={[styles.dropdownText, !date && styles.dropdownPlaceholder]}>
              {dateLabel || "Tap to pick a date"}
            </Text>
            <Text style={styles.dropdownCaret}>📅</Text>
          </TouchableOpacity>

          {/* Time dropdown */}
          <Text style={[FORM.label, { marginTop: S.md }]}>Time slot</Text>
          <TouchableOpacity style={styles.dropdownBtn} onPress={() => setShowTimePicker(true)}>
            <Text style={[styles.dropdownText, !time && styles.dropdownPlaceholder]}>
              {time ? formatTimeAmPm(time) : "Tap to pick a time"}
            </Text>
            <Text style={styles.dropdownCaret}>🕐</Text>
          </TouchableOpacity>

          {/* Lab picker — required */}
          <Text style={[FORM.label, { marginTop: S.md }]}>Lab <Text style={{ color: COG.red }}>*</Text></Text>
          <TouchableOpacity
            style={[styles.dropdownBtn, !measureId && { opacity: 0.5 }]}
            disabled={!measureId}
            onPress={() => setShowLabPicker(true)}
          >
            <Text style={[styles.dropdownText, !pickedLab && styles.dropdownPlaceholder]} numberOfLines={2}>
              {pickedLab
                ? pickedLab.name + (pickedLab.address ? ` — ${pickedLab.address}` : "")
                : (measureId ? "Tap to find nearby labs (within 25 km)" : "Pick a screening first")}
            </Text>
            <Text style={styles.dropdownCaret}>📍</Text>
          </TouchableOpacity>
          {pickedLab && (
            <TouchableOpacity onPress={() => setPickedLab(null)} style={{ alignSelf: "flex-end", marginTop: 4 }}>
              <Text style={{ color: COG.red, fontSize: 11, fontWeight: "700" }}>Change lab</Text>
            </TouchableOpacity>
          )}

          <TouchableOpacity
            style={[BTN_FILLED.container, { marginTop: S.lg }, (booking || !measureId || !date || !time || !pickedLab) && { opacity: 0.5 }]}
            onPress={handleBook}
            disabled={booking || !measureId || !date || !time || !pickedLab}
          >
            <Text style={BTN_FILLED.text}>
              {booking
                ? "Booking..."
                : (!pickedLab ? "Pick a lab to continue" : "Confirm booking")}
            </Text>
          </TouchableOpacity>
        </View>
      </View>

      {/* ── LAB PICKER (interactive map) ──────────────────── */}
      <LabPickerModal
        visible={showLabPicker}
        measureId={measureId}
        onClose={() => setShowLabPicker(false)}
        onPicked={(lab) => { setPickedLab(lab); setShowLabPicker(false); }}
      />

      {/* ── MEASURE PICKER MODAL ──────────────────────────── */}
      <Modal visible={showMeasurePicker} transparent animationType="slide" onRequestClose={() => setShowMeasurePicker(false)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setShowMeasurePicker(false)}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Choose a screening</Text>
            <ScrollView>
              {gaps.map((g) => (
                <TouchableOpacity
                  key={g.measure_id}
                  style={[styles.optionRow, measureId === g.measure_id && styles.optionRowActive]}
                  onPress={() => { setMeasureId(g.measure_id); setShowMeasurePicker(false); }}
                >
                  <View style={{ flex: 1 }}>
                    <Text style={styles.optionTitle}>{g.measure_name || g.measure_id}</Text>
                    <Text style={styles.optionSub}>{g.measure_id}{g.description ? ` — ${g.description.slice(0, 60)}…` : ""}</Text>
                  </View>
                  {measureId === g.measure_id ? <Text style={styles.optionCheck}>✓</Text> : null}
                </TouchableOpacity>
              ))}
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>

      {/* ── DATE PICKER MODAL (calendar grid) ─────────────── */}
      <Modal visible={showDatePicker} transparent animationType="slide" onRequestClose={() => setShowDatePicker(false)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setShowDatePicker(false)}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Pick a date</Text>
            <ScrollView>
              <View style={styles.dateGrid}>
                {dateGrid.map((d) => (
                  <TouchableOpacity
                    key={d.iso}
                    style={[styles.dateCell, date === d.iso && styles.dateCellActive, d.isWeekend && styles.dateCellWeekend]}
                    onPress={() => { setDate(d.iso); setShowDatePicker(false); }}
                  >
                    <Text style={[styles.dateDay, date === d.iso && styles.dateActiveText]}>{d.day}</Text>
                    <Text style={[styles.dateNum, date === d.iso && styles.dateActiveText]}>{d.dayNum}</Text>
                    <Text style={[styles.dateMonth, date === d.iso && styles.dateActiveText]}>{d.monthShort}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>

      {/* ── TIME SLOT PICKER MODAL ────────────────────────── */}
      <Modal visible={showTimePicker} transparent animationType="slide" onRequestClose={() => setShowTimePicker(false)}>
        <TouchableOpacity style={styles.modalBackdrop} activeOpacity={1} onPress={() => setShowTimePicker(false)}>
          <View style={styles.modalSheet}>
            <Text style={styles.modalTitle}>Pick a time</Text>
            <ScrollView>
              <View style={styles.timeGrid}>
                {TIME_SLOTS.map((t) => (
                  <TouchableOpacity
                    key={t}
                    style={[styles.timeCell, time === t && styles.timeCellActive]}
                    onPress={() => { setTime(t); setShowTimePicker(false); }}
                  >
                    <Text style={[styles.timeCellText, time === t && styles.timeCellTextActive]}>
                      {formatTimeAmPm(t)}
                    </Text>
                  </TouchableOpacity>
                ))}
              </View>
            </ScrollView>
          </View>
        </TouchableOpacity>
      </Modal>

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
                {(a.status === "No Show" || a.status === "Cancelled_NoShow") && (
                  <TouchableOpacity
                    style={styles.rebookBtn}
                    onPress={() => {
                      setMeasureId(a.measure_id || "");
                      setDate(""); setTime("");
                      Alert.alert("Rebook this screening", "Pick a new date and time below.");
                    }}
                  >
                    <Text style={styles.rebookText}>Rebook</Text>
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
  rebookBtn: {
    marginTop: 6, paddingHorizontal: 10, paddingVertical: 4,
    backgroundColor: COG.tealLight, borderRadius: 999,
  },
  rebookText: { color: COG.primary, fontSize: 11, fontWeight: "800" },

  // ── dropdown buttons ────────────────────────────────────────────
  dropdownBtn: {
    marginTop: 4, paddingHorizontal: 12, paddingVertical: 14,
    borderWidth: 1, borderColor: COG.grayLighter,
    backgroundColor: COG.white,
    flexDirection: "row", alignItems: "center", justifyContent: "space-between",
  },
  dropdownText:        { fontSize: 14, color: COG.primary, fontWeight: "600", flex: 1 },
  dropdownPlaceholder: { color: COG.grayMedium, fontWeight: "400" },
  dropdownCaret:       { fontSize: 14, color: COG.grayDark, marginLeft: 8 },

  // ── modal sheet ──────────────────────────────────────────────────
  modalBackdrop: {
    flex: 1, backgroundColor: "rgba(0,0,0,0.45)",
    justifyContent: "flex-end",
  },
  modalSheet: {
    backgroundColor: COG.white, padding: S.lg,
    borderTopLeftRadius: 16, borderTopRightRadius: 16,
    maxHeight: "75%",
  },
  modalTitle: {
    fontSize: 16, fontWeight: "800", color: COG.primary,
    marginBottom: S.md, textAlign: "center", letterSpacing: 0.3,
  },
  optionRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, paddingHorizontal: 4,
    borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  optionRowActive: { backgroundColor: "rgba(38,239,233,0.12)" },
  optionTitle: { fontSize: 14, fontWeight: "700", color: COG.primary },
  optionSub:   { fontSize: 11, color: COG.grayDark, marginTop: 2 },
  optionCheck: { fontSize: 18, color: COG.green, fontWeight: "800", marginLeft: 8 },

  // ── date grid ────────────────────────────────────────────────────
  dateGrid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
  dateCell: {
    width: "23%", marginVertical: 4, paddingVertical: 8,
    borderWidth: 1, borderColor: COG.grayLighter,
    alignItems: "center", backgroundColor: COG.white,
  },
  dateCellWeekend: { backgroundColor: COG.grayLightest },
  dateCellActive:  { backgroundColor: COG.primary, borderColor: COG.primary },
  dateDay:   { fontSize: 10, color: COG.grayDark, fontWeight: "700", letterSpacing: 0.5 },
  dateNum:   { fontSize: 18, color: COG.primary, fontWeight: "800", marginVertical: 2 },
  dateMonth: { fontSize: 9,  color: COG.grayDark, textTransform: "uppercase", letterSpacing: 0.5 },
  dateActiveText: { color: COG.white },

  // ── time grid ────────────────────────────────────────────────────
  timeGrid: { flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" },
  timeCell: {
    width: "31%", marginVertical: 4, paddingVertical: 12,
    borderWidth: 1, borderColor: COG.blueDark, borderRadius: 999,
    alignItems: "center", backgroundColor: COG.white,
  },
  timeCellActive:    { backgroundColor: COG.blueDark, borderColor: COG.blueDark },
  timeCellText:      { fontSize: 12, fontWeight: "700", color: COG.blueDark, letterSpacing: 0.3 },
  timeCellTextActive:{ color: COG.white },
});
