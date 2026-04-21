import { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, Alert, KeyboardAvoidingView, Platform,
} from "react-native";
import { useRouter } from "expo-router";
import { requestOtp } from "../src/lib/api";

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
      Alert.alert("Code Sent", `We sent a 6-digit code to ${res.email_hint || "your email"}.`);
      router.push({ pathname: "/verify", params: { memberId: trimmed } });
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
    >
      <Text style={styles.title}>Cognizant Care</Text>
      <Text style={styles.subtitle}>Enter your Member ID to get started</Text>
      <TextInput
        style={styles.input}
        placeholder="M0001"
        placeholderTextColor="#9ca3af"
        value={memberId}
        onChangeText={setMemberId}
        autoCapitalize="characters"
        autoCorrect={false}
      />
      <TouchableOpacity style={styles.button} onPress={handleSubmit} disabled={loading}>
        <Text style={styles.buttonText}>{loading ? "Sending..." : "Send Code"}</Text>
      </TouchableOpacity>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: "#fff", justifyContent: "center" },
  title: { fontSize: 28, fontWeight: "700", color: "#0033a0", textAlign: "center", marginBottom: 8 },
  subtitle: { fontSize: 14, color: "#6b7280", textAlign: "center", marginBottom: 32 },
  input: {
    borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 8, padding: 14,
    fontSize: 16, backgroundColor: "#f9fafb", marginBottom: 18,
  },
  button: {
    backgroundColor: "#0033a0", paddingVertical: 14, borderRadius: 8, alignItems: "center",
  },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "700" },
});
