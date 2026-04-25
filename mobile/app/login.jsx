import { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, Alert,
  KeyboardAvoidingView, Platform, Image,
} from "react-native";
import { useRouter } from "expo-router";
import { requestOtp } from "../src/lib/api";
import { COG, TYPE, FORM, BTN_FILLED, S } from "../src/lib/brand";
import CogLogo from "../src/components/CogLogo";

export default function Login() {
  const [memberId, setMemberId] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleSubmit = async () => {
    const trimmed = memberId.trim();
    if (!trimmed) {
      Alert.alert("Missing", "Please enter your Member ID");
      return;
    }
    setLoading(true);
    try {
      const res = await requestOtp(trimmed);
      Alert.alert("Code sent", `A 6-digit code was emailed to ${res.email_hint || "your registered email"}.`);
      router.push({ pathname: "/verify", params: { memberId: trimmed } });
    } catch (e) {
      Alert.alert("Unable to send", e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined}>
      <View style={styles.brandRow}>
        <CogLogo variant="dark" size={36} />
      </View>
      <Text style={styles.heading}>Welcome back.</Text>
      <Text style={styles.sub}>Sign in with your Member ID to access your care plan.</Text>

      <Text style={FORM.label}>Member ID</Text>
      <TextInput
        style={styles.input}
        placeholder="e.g. M0011"
        placeholderTextColor={COG.grayMedium}
        value={memberId}
        onChangeText={setMemberId}
        autoCapitalize="characters"
        autoCorrect={false}
      />

      <TouchableOpacity style={[styles.cta, loading && { opacity: 0.6 }]} onPress={handleSubmit} disabled={loading}>
        <Text style={styles.ctaText}>{loading ? "Sending..." : "Send activation code"}</Text>
      </TouchableOpacity>

      <Text style={styles.footnote}>
        Your code is delivered to the email on your member record. Codes expire in 10 minutes.
      </Text>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 28, backgroundColor: COG.white, justifyContent: "center" },
  brandRow: { alignItems: "flex-start", marginBottom: S.xxl },
  heading: { ...TYPE.h3, marginBottom: 6 },
  sub: { ...TYPE.body, color: COG.grayDark, marginBottom: S.xxl },
  input: { ...FORM.input, marginBottom: S.xl, fontSize: 18, letterSpacing: 0.5 },
  cta: { ...BTN_FILLED.container },
  ctaText: { ...BTN_FILLED.text },
  footnote: { ...TYPE.tiny, textAlign: "center", marginTop: S.xl, paddingHorizontal: 8 },
});
