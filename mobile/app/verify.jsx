import { useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, Alert,
} from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { verifyOtp } from "../src/lib/api";

export default function Verify() {
  const { memberId } = useLocalSearchParams();
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleVerify = async () => {
    if (otp.length !== 6) {
      Alert.alert("Invalid", "Please enter the 6-digit code");
      return;
    }
    setLoading(true);
    try {
      await verifyOtp(memberId, otp);
      router.replace("/(tabs)/home");
    } catch (e) {
      Alert.alert("Error", e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.title}>Enter the 6-digit code</Text>
      <Text style={styles.subtitle}>We emailed a code to activate {memberId}</Text>
      <TextInput
        style={styles.input}
        placeholder="123456"
        placeholderTextColor="#9ca3af"
        value={otp}
        onChangeText={setOtp}
        keyboardType="number-pad"
        maxLength={6}
      />
      <TouchableOpacity style={styles.button} onPress={handleVerify} disabled={loading}>
        <Text style={styles.buttonText}>{loading ? "Verifying..." : "Verify"}</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 24, backgroundColor: "#fff", justifyContent: "center" },
  title: { fontSize: 22, fontWeight: "700", color: "#0033a0", textAlign: "center", marginBottom: 8 },
  subtitle: { fontSize: 14, color: "#6b7280", textAlign: "center", marginBottom: 32 },
  input: {
    borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 8, padding: 14,
    fontSize: 22, textAlign: "center", letterSpacing: 6, backgroundColor: "#f9fafb", marginBottom: 18,
  },
  button: {
    backgroundColor: "#0033a0", paddingVertical: 14, borderRadius: 8, alignItems: "center",
  },
  buttonText: { color: "#fff", fontSize: 16, fontWeight: "700" },
});
