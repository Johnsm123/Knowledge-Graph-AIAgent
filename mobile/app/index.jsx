import { useEffect } from "react";
import { View, ActivityIndicator, StyleSheet } from "react-native";
import { useRouter } from "expo-router";
import { getSession } from "../src/lib/api";

export default function Index() {
  const router = useRouter();

  useEffect(() => {
    (async () => {
      const session = await getSession();
      if (session) router.replace("/(tabs)/home");
      else router.replace("/login");
    })();
  }, []);

  return (
    <View style={styles.container}>
      <ActivityIndicator size="large" color="#fff" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#0033a0",
    justifyContent: "center",
    alignItems: "center",
  },
});
