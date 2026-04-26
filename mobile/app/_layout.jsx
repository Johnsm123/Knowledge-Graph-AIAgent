import { useEffect, useState } from "react";
import { Stack, router } from "expo-router";
import { StatusBar } from "expo-status-bar";
import * as Notifications from "expo-notifications";
import AnimatedSplash from "../src/components/AnimatedSplash";
import CogLogo from "../src/components/CogLogo";
import { COG } from "../src/lib/brand";
import { setupPushNotifications } from "../src/lib/push";

export default function RootLayout() {
  const [splashDone, setSplashDone] = useState(false);

  // Register for push tokens once on app boot (not just when /home opens),
  // and route taps from the system notification tray to the right tab.
  useEffect(() => {
    setupPushNotifications().catch(() => {});

    // When the user taps a notification in the Android system drawer, jump
    // straight to Appointments (for missed/scheduled) or Chat (for proactive).
    const tapSub = Notifications.addNotificationResponseReceivedListener((res) => {
      try {
        const kind = res?.notification?.request?.content?.data?.kind || "";
        if (kind === "missed" || kind === "day_before" || kind === "morning_of") {
          router.push("/(tabs)/appointments");
        } else {
          router.push("/(tabs)/chat");
        }
      } catch (_) {}
    });

    // While the app is in the foreground, ensure the heads-up banner still
    // displays (setNotificationHandler in push.js already returns shouldShowAlert: true,
    // this listener is just for any side-effects we want).
    const fgSub = Notifications.addNotificationReceivedListener(() => {});

    return () => { tapSub.remove(); fgSub.remove(); };
  }, []);

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
