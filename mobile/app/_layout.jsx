import { useState } from "react";
import { Stack } from "expo-router";
import { StatusBar } from "expo-status-bar";
import AnimatedSplash from "../src/components/AnimatedSplash";
import CogLogo from "../src/components/CogLogo";
import { COG } from "../src/lib/brand";

export default function RootLayout() {
  const [splashDone, setSplashDone] = useState(false);

  return (
    <>
      <StatusBar style="light" />
      <Stack
        screenOptions={{
          headerStyle: { backgroundColor: COG.primary },
          headerTintColor: COG.white,
          headerTitleStyle: { fontWeight: "700" },
          headerTitle: () => <CogLogo variant="light" size={26} />,
        }}
      >
        <Stack.Screen name="index"  options={{ headerShown: false }} />
        <Stack.Screen name="login"  options={{ title: "Activate" }} />
        <Stack.Screen name="verify" options={{ title: "Verify" }} />
        <Stack.Screen name="(tabs)" options={{ headerShown: false }} />
      </Stack>
      {!splashDone && <AnimatedSplash onFinish={() => setSplashDone(true)} />}
    </>
  );
}
