import { useEffect, useState, useCallback } from "react";
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity, RefreshControl,
} from "react-native";
import { useRouter, useFocusEffect } from "expo-router";
import { getMe, clearSession, listAppointments, resetChat } from "../../src/lib/api";
import { setupPushNotifications } from "../../src/lib/push";
import { subscribeRealtime } from "../../src/lib/realtime";
import { COG, TYPE, S, CARD, BTN_HOLLOW, BTN_FILLED } from "../../src/lib/brand";
import HealthInsights from "../../src/components/HealthInsights";

export default function Home() {
  const [data, setData]             = useState(null);
  const [appts, setAppts]           = useState([]);
  const [loading, setLoading]       = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const router = useRouter();

  const load = async () => {
    try {
      const [me, apptRes] = await Promise.all([getMe(), listAppointments().catch(() => ({ appointments: [] }))]);
      setData(me);
      setAppts(apptRes.appointments || []);
    } catch (_) {
      await clearSession();
      router.replace("/login");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    load();
    setupPushNotifications();
    const unsub = subscribeRealtime((event, payload) => {
      // Refresh home whenever this member's data changes server-side
      const mid = data?.member_id;
      if (!payload || payload.member_id === mid || !mid) load();
    });
    return () => unsub();
  }, []);

  // Re-fetch whenever this tab regains focus — keeps Home fresh after book/cancel on other tabs
  useFocusEffect(useCallback(() => { load(); }, []));

  const handleSignOut = async () => {
    try { await resetChat(); } catch (_) {}
    await clearSession();
    router.replace("/login");
  };

  if (loading) return (
    <View style={styles.center}><ActivityIndicator size="large" color={COG.primary} /></View>
  );

  const profile = data?.profile || {};
  const gaps    = data?.open_gaps || [];

  // Appointments that need member attention
  const now = Date.now();
  const missed = appts.filter((a) => {
    if (a.status !== "No Show") return false;
    return true;
  });
  const upcoming = appts
    .filter((a) => a.status === "Scheduled")
    .filter((a) => {
      const t = Date.parse(`${a.appointment_date}T${a.appointment_time || "00:00"}:00`);
      return !isNaN(t) && t > now;
    })
    .sort((x, y) => Date.parse(`${x.appointment_date}T${x.appointment_time}`) - Date.parse(`${y.appointment_date}T${y.appointment_time}`));
  const nextUp = upcoming[0] || null;

  const age  = profile.age || profile.age_str;
  const plan = profile.plan_name || profile.plan || profile.plan_id;

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl tintColor={COG.primary} refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <View style={styles.banner}>
        <Text style={styles.bannerHi}>Hello, {profile.name || data?.member_id}</Text>
        <Text style={styles.bannerSub}>Member ID · {data?.member_id}</Text>
      </View>

      {/* Alert: missed appointment needs attention */}
      {missed.length > 0 && (
        <View style={styles.alertBox}>
          <Text style={styles.alertTitle}>⚠ Missed appointment</Text>
          <Text style={styles.alertBody}>
            You missed {missed.length === 1 ? "an" : `${missed.length}`} appointment. Tap the Assistant tab to reschedule.
          </Text>
          <TouchableOpacity
            style={styles.alertBtn}
            onPress={() => router.push("/(tabs)/chat")}
          >
            <Text style={styles.alertBtnText}>Reschedule now</Text>
          </TouchableOpacity>
        </View>
      )}

      {/* Upcoming next appointment */}
      {nextUp && (
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Next appointment</Text>
          <View style={[styles.card, { borderLeftWidth: 4, borderLeftColor: COG.tealLight }]}>
            <Text style={styles.upName}>{nextUp.screening_name || nextUp.measure_id}</Text>
            <Text style={styles.upMeta}>{nextUp.appointment_date} · {nextUp.appointment_time}</Text>
            {nextUp.lab_location ? <Text style={styles.upLoc}>{nextUp.lab_location}</Text> : null}
          </View>
        </View>
      )}

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Health insights</Text>
        <HealthInsights profile={profile} gaps={gaps} appointments={appts} />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Profile</Text>
        <View style={styles.card}>
          <Row label="Age"    value={age} />
          <Row label="Gender" value={profile.gender} />
          <Row label="Email"  value={profile.email} />
          <Row label="Phone"  value={profile.phone} />
          <Row label="Doctor" value={profile.pcp_name} />
          <Row label="Plan"   value={plan} last />
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Open care gaps <Text style={styles.count}>({gaps.length})</Text></Text>
        <View style={styles.card}>
          {gaps.length === 0 ? (
            <Text style={TYPE.body}>You have no open care gaps right now. Great job staying on top of your health.</Text>
          ) : gaps.map((g, i) => (
            <View key={i} style={[styles.gapRow, i === gaps.length - 1 && { borderBottomWidth: 0 }]}>
              <View style={{ flex: 1 }}>
                <Text style={styles.gapName}>{g.measure_name || g.measure_id}</Text>
                <Text style={styles.gapMeasure}>{g.measure_id}</Text>
              </View>
              <View style={styles.pill}>
                <Text style={styles.pillText}>{g.status || "Open"}</Text>
              </View>
            </View>
          ))}
          {gaps.length > 0 && (
            <TouchableOpacity
              style={[BTN_FILLED.container, { marginTop: S.md }]}
              onPress={() => router.push("/(tabs)/chat")}
            >
              <Text style={BTN_FILLED.text}>Book with assistant</Text>
            </TouchableOpacity>
          )}
        </View>
      </View>

      <TouchableOpacity style={[BTN_HOLLOW.container, styles.signOut]} onPress={handleSignOut}>
        <Text style={BTN_HOLLOW.text}>Sign Out</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

function Row({ label, value, last }) {
  return (
    <View style={[styles.row, last && { borderBottomWidth: 0 }]}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value || "—"}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.grayLightest },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: COG.grayLightest },
  banner: { padding: S.xl, backgroundColor: COG.primary },
  bannerHi: { color: COG.white, fontSize: 24, fontWeight: "700" },
  bannerSub: { color: COG.blueLight, fontSize: 13, marginTop: 4 },

  alertBox: {
    margin: S.lg, marginBottom: 0,
    backgroundColor: "#FDECEC", borderLeftWidth: 4, borderLeftColor: COG.red,
    padding: S.md,
  },
  alertTitle: { color: COG.red, fontWeight: "800", fontSize: 14 },
  alertBody:  { color: COG.grayDark, fontSize: 13, marginTop: 4, marginBottom: 8 },
  alertBtn:   { alignSelf: "flex-start", backgroundColor: COG.red, paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999 },
  alertBtnText: { color: COG.white, fontWeight: "700", fontSize: 12 },

  section: { paddingHorizontal: S.lg, paddingTop: S.xl },
  sectionLabel: { ...TYPE.small, fontWeight: "700", color: COG.grayDark, marginBottom: S.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  count: { color: COG.grayDark, fontWeight: "400" },
  card: { ...CARD },
  row: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  rowLabel: { ...TYPE.small, color: COG.grayDark },
  rowValue: { ...TYPE.small, color: COG.primary, fontWeight: "600", maxWidth: "60%", textAlign: "right" },
  gapRow: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  gapName:    { fontSize: 15, fontWeight: "600", color: COG.primary },
  gapMeasure: { fontSize: 11, color: COG.grayDark, marginTop: 2, letterSpacing: 0.5 },
  pill:       { backgroundColor: COG.red, paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999 },
  pillText:   { color: COG.white, fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },

  upName: { fontSize: 15, fontWeight: "700", color: COG.primary },
  upMeta: { fontSize: 12, color: COG.grayDark, marginTop: 3 },
  upLoc:  { fontSize: 11, color: COG.blueDark, marginTop: 2 },

  signOut: { margin: S.lg, marginTop: S.xl },
});
