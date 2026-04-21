import { useEffect, useState } from "react";
import {
  View, Text, ScrollView, StyleSheet, ActivityIndicator, TouchableOpacity, RefreshControl,
} from "react-native";
import { useRouter } from "expo-router";
import { getMe, clearSession } from "../../src/lib/api";

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
  }, []);

  const handleSignOut = async () => {
    await clearSession();
    router.replace("/login");
  };

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#0033a0" />
      </View>
    );
  }

  const profile = data?.profile || {};
  const gaps = data?.open_gaps || [];

  return (
    <ScrollView
      style={styles.container}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={() => { setRefreshing(true); load(); }} />}
    >
      <View style={styles.header}>
        <Text style={styles.greeting}>Hi, {profile.name || data?.member_id}</Text>
        <Text style={styles.subtext}>Member ID: {data?.member_id}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Profile</Text>
        <Text style={styles.row}>Age: {profile.age || "—"}</Text>
        <Text style={styles.row}>Gender: {profile.gender || "—"}</Text>
        <Text style={styles.row}>Email: {profile.email || "—"}</Text>
      </View>

      <View style={styles.card}>
        <Text style={styles.cardTitle}>Open Care Gaps ({gaps.length})</Text>
        {gaps.length === 0 ? (
          <Text style={styles.row}>You have no open care gaps. </Text>
        ) : (
          gaps.map((g, i) => (
            <View key={i} style={styles.gapRow}>
              <Text style={styles.gapName}>{g.measure_name || g.measure_id}</Text>
              <Text style={styles.gapStatus}>{g.status || "Open"}</Text>
            </View>
          ))
        )}
      </View>

      <TouchableOpacity style={styles.signOut} onPress={handleSignOut}>
        <Text style={styles.signOutText}>Sign Out</Text>
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f3f4f6" },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: "#f3f4f6" },
  header: { padding: 20, backgroundColor: "#0033a0" },
  greeting: { color: "#fff", fontSize: 22, fontWeight: "700" },
  subtext: { color: "#cbd5e1", fontSize: 13, marginTop: 4 },
  card: { margin: 16, padding: 16, backgroundColor: "#fff", borderRadius: 12, elevation: 2 },
  cardTitle: { fontSize: 16, fontWeight: "700", color: "#0033a0", marginBottom: 10 },
  row: { fontSize: 14, color: "#374151", paddingVertical: 4 },
  gapRow: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#f3f4f6",
  },
  gapName: { fontSize: 14, color: "#111827", fontWeight: "600" },
  gapStatus: { fontSize: 13, color: "#ef4444", fontWeight: "600" },
  signOut: { margin: 16, padding: 12, alignItems: "center" },
  signOutText: { color: "#6b7280", fontSize: 14, fontWeight: "600" },
});
