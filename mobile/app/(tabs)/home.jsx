import { useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity, RefreshControl,
} from "react-native";
import { useRouter } from "expo-router";
import { getMe, clearSession } from "../../src/lib/api";
import { setupPushNotifications } from "../../src/lib/push";
import { COG, TYPE, S, CARD, BTN_HOLLOW, BTN_FILLED } from "../../src/lib/brand";

export default function Home() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const router = useRouter();

  const load = async () => {
    try {
      const res = await getMe();
      setData(res);
    } catch (e) {
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
  }, []);

  const handleSignOut = async () => { await clearSession(); router.replace("/login"); };

  if (loading) return (
    <View style={styles.center}>
      <ActivityIndicator size="large" color={COG.primary} />
    </View>
  );

  const profile = data?.profile || {};
  const gaps = data?.open_gaps || [];

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl tintColor={COG.primary} refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <View style={styles.banner}>
        <Text style={styles.bannerHi}>Hello, {profile.name || data?.member_id}</Text>
        <Text style={styles.bannerSub}>Member ID · {data?.member_id}</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Profile</Text>
        <View style={styles.card}>
          <Row label="Age" value={profile.age} />
          <Row label="Gender" value={profile.gender} />
          <Row label="Email" value={profile.email} />
          <Row label="Phone" value={profile.phone} />
          <Row label="Plan" value={profile.plan_name || profile.plan} last />
        </View>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionLabel}>Open care gaps <Text style={styles.count}>({gaps.length})</Text></Text>
        <View style={styles.card}>
          {gaps.length === 0 ? (
            <Text style={TYPE.body}>You have no open care gaps right now. </Text>
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
  gapName: { fontSize: 15, fontWeight: "600", color: COG.primary },
  gapMeasure: { fontSize: 11, color: COG.grayDark, marginTop: 2, letterSpacing: 0.5 },
  pill: {
    backgroundColor: COG.red, paddingHorizontal: 10, paddingVertical: 4,
    borderRadius: 999,
  },
  pillText: { color: COG.white, fontSize: 11, fontWeight: "700", letterSpacing: 0.3 },
  signOut: { margin: S.lg, marginTop: S.xl },
});
