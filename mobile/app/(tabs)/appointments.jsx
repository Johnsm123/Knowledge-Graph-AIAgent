import { useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, TextInput, TouchableOpacity, Alert, ActivityIndicator,
} from "react-native";
import { listAppointments, bookAppointment, getMe } from "../../src/lib/api";

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
      Alert.alert("Missing", "Please fill measure, date, and time");
      return;
    }
    setBooking(true);
    try {
      await bookAppointment({ measure_id: measureId, appointment_date: date, appointment_time: time });
      Alert.alert("Booked", "Your appointment is confirmed.");
      setMeasureId(""); setDate(""); setTime("");
      load();
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setBooking(false);
    }
  };

  if (loading) {
    return <View style={styles.center}><ActivityIndicator size="large" color="#0033a0" /></View>;
  }

  return (
    <ScrollView style={styles.container}>
      <View style={styles.card}>
        <Text style={styles.cardTitle}>Book Appointment</Text>
        <Text style={styles.hint}>Open gaps: {gaps.map(g => g.measure_id).join(", ") || "none"}</Text>
        <TextInput style={styles.input} placeholder="Measure ID (e.g. BCS)"
          value={measureId} onChangeText={setMeasureId} autoCapitalize="characters" />
        <TextInput style={styles.input} placeholder="Date (YYYY-MM-DD)"
          value={date} onChangeText={setDate} />
        <TextInput style={styles.input} placeholder="Time (HH:MM)"
          value={time} onChangeText={setTime} />
        <TouchableOpacity style={styles.button} onPress={handleBook} disabled={booking}>
          <Text style={styles.buttonText}>{booking ? "Booking..." : "Book"}</Text>
        </TouchableOpacity>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Your Appointments ({appts.length})</Text>
        {appts.length === 0 ? (
          <Text style={styles.row}>No appointments yet.</Text>
        ) : appts.map((a, i) => (
          <View key={i} style={styles.apptRow}>
            <Text style={styles.apptDate}>{a.appointment_date} {a.appointment_time}</Text>
            <Text style={styles.apptMeta}>{a.measure_id} · {a.status}</Text>
          </View>
        ))}
      </View>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f3f4f6" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#f3f4f6" },
  card: { margin: 16, padding: 16, backgroundColor: "#fff", borderRadius: 12, elevation: 2 },
  cardTitle: { fontSize: 16, fontWeight: "700", color: "#0033a0", marginBottom: 10 },
  hint: { fontSize: 12, color: "#6b7280", marginBottom: 10 },
  row: { fontSize: 14, color: "#374151" },
  input: {
    borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 8, padding: 12,
    fontSize: 14, backgroundColor: "#f9fafb", marginBottom: 10,
  },
  button: { backgroundColor: "#0033a0", paddingVertical: 12, borderRadius: 8, alignItems: "center", marginTop: 4 },
  buttonText: { color: "#fff", fontSize: 15, fontWeight: "700" },
  apptRow: { paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#f3f4f6" },
  apptDate: { fontSize: 14, fontWeight: "600", color: "#111827" },
  apptMeta: { fontSize: 12, color: "#6b7280", marginTop: 2 },
});
