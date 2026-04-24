import { useState } from "react";
import { View, Text, TextInput, TouchableOpacity, StyleSheet, Alert } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { verifyOtp } from "../src/lib/api";
import { COG, TYPE, FORM, BTN_FILLED, BTN_HOLLOW, S } from "../src/lib/brand";

export default function Verify() {
  const { memberId } = useLocalSearchParams();
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();

  const handleVerify = async () => {
    if (otp.length !== 6) {
      Alert.alert("Invalid code", "Please enter the 6-digit code from your email.");
      return;
    }
    setLoading(true);
    try {
      await verifyOtp(memberId, otp);
      router.replace("/(tabs)/home");
    } catch (e) {
      Alert.alert("Verification failed", e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <View style={styles.container}>
      <Text style={styles.heading}>Enter your code</Text>
      <Text style={styles.sub}>We emailed a 6-digit code to activate member {memberId}.</Text>

      <Text style={FORM.label}>6-digit code</Text>
      <TextInput
        style={styles.input}
        placeholder="000000"
        placeholderTextColor={COG.grayMedium}
        value={otp}
        onChangeText={setOtp}
        keyboardType="number-pad"
        maxLength={6}
      />

      <TouchableOpacity style={[BTN_FILLED.container, loading && { opacity: 0.6 }]} onPress={handleVerify} disabled={loading}>
        <Text style={BTN_FILLED.text}>{loading ? "Verifying..." : "Verify & continue"}</Text>
      </TouchableOpacity>

      <TouchableOpacity style={[BTN_HOLLOW.container, { marginTop: S.md }]} onPress={() => router.back()}>
        <Text style={BTN_HOLLOW.text}>Back to sign in</Text>
      </TouchableOpacity>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 28, backgroundColor: COG.white, justifyContent: "center" },
  heading: { ...TYPE.h3, marginBottom: 6 },
  sub: { ...TYPE.body, color: COG.grayDark, marginBottom: S.xxl },
  input: {
    ...FORM.input,
    marginBottom: S.xl,
    fontSize: 28, textAlign: "center", letterSpacing: 10,
  },
});
