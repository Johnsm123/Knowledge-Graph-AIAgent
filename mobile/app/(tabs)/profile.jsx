import { useEffect, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, ScrollView,
  ActivityIndicator, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { getMe, updateProfile } from "../../src/lib/api";
import { COG, TYPE, FORM, BTN_FILLED, BTN_HOLLOW, S, CARD } from "../../src/lib/brand";

export default function Profile() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [address, setAddress] = useState("");
  const [memberId, setMemberId] = useState("");
  const [name, setName] = useState("");

  useEffect(() => { load(); }, []);

  const load = async () => {
    try {
      setLoading(true);
      const data = await getMe();
      const p = data.profile || {};
      setMemberId(data.member_id || "");
      setName(p.name || "");
      setPhone(p.phone || "");
      setEmail(p.email || "");
      setAddress(p.address || "");
    } catch (_) {
      Alert.alert("Could not load profile", "Please try again shortly.");
    } finally {
      setLoading(false);
    }
  };

  const save = async () => {
    setSaving(true);
    try {
      await updateProfile({ phone, email, address });
      Alert.alert("Saved", "Your profile is updated. The care team has been notified.");
    } catch (e) {
      Alert.alert("Update failed", e.message);
    } finally {
      setSaving(false);
    }
  };

  if (loading) return (
    <View style={styles.center}><ActivityIndicator size="large" color={COG.primary} /></View>
  );

  return (
    <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <ScrollView style={styles.container} contentContainerStyle={{ paddingBottom: S.xxl }}>
        <View style={styles.banner}>
          <Text style={styles.name}>{name || "—"}</Text>
          <Text style={styles.memberId}>Member ID · {memberId}</Text>
        </View>

        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Contact information</Text>
          <View style={styles.card}>
            <Text style={FORM.label}>Phone</Text>
            <TextInput style={FORM.input} value={phone} onChangeText={setPhone}
              placeholder="e.g. 9884169146" placeholderTextColor={COG.grayMedium} keyboardType="phone-pad" />

            <Text style={[FORM.label, { marginTop: S.md }]}>Email</Text>
            <TextInput style={FORM.input} value={email} onChangeText={setEmail}
              placeholder="you@example.com" placeholderTextColor={COG.grayMedium}
              autoCapitalize="none" keyboardType="email-address" />

            <Text style={[FORM.label, { marginTop: S.md }]}>Address</Text>
            <TextInput
              style={[FORM.input, { minHeight: 80, textAlignVertical: "top" }]}
              value={address} onChangeText={setAddress}
              placeholder="Street, City, State, Postal code" placeholderTextColor={COG.grayMedium}
              multiline
            />

            <TouchableOpacity
              style={[BTN_FILLED.container, { marginTop: S.lg }, saving && { opacity: 0.6 }]}
              onPress={save} disabled={saving}
            >
              <Text style={BTN_FILLED.text}>{saving ? "Saving..." : "Save changes"}</Text>
            </TouchableOpacity>
          </View>
        </View>

        <Text style={styles.footnote}>
          Changes save instantly and appear in the care management portal.
        </Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.grayLightest },
  center: { flex: 1, justifyContent: "center", alignItems: "center", backgroundColor: COG.grayLightest },
  banner: { padding: S.xl, backgroundColor: COG.primary },
  name: { color: COG.white, fontSize: 22, fontWeight: "700" },
  memberId: { color: COG.blueLight, fontSize: 12, marginTop: 4, letterSpacing: 0.5 },
  section: { paddingHorizontal: S.lg, paddingTop: S.xl },
  sectionLabel: { ...TYPE.small, fontWeight: "700", color: COG.grayDark, marginBottom: S.sm, textTransform: "uppercase", letterSpacing: 0.5 },
  card: { ...CARD },
  footnote: { ...TYPE.tiny, textAlign: "center", marginTop: S.lg, paddingHorizontal: S.lg },
});
