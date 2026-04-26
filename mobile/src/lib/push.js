import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";
import { registerPushToken } from "./api";

// SDK 49+ split shouldShowAlert into shouldShowBanner + shouldShowList.
// Set both so the heads-up banner shows AND the notification persists in the
// Android system drawer (the "drop-down" the user wants).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,    // legacy SDKs
    shouldShowBanner: true,   // SDK 49+
    shouldShowList: true,     // SDK 49+ — keeps it in the system tray list
    shouldPlaySound: true,
    shouldSetBadge: true,
  }),
});

/** Request notification permission and send the device FCM token to the backend. */
export async function setupPushNotifications() {
  if (!Device.isDevice) return;  // no push on simulators

  const { status: existing } = await Notifications.getPermissionsAsync();
  let status = existing;
  if (existing !== "granted") {
    const asked = await Notifications.requestPermissionsAsync();
    status = asked.status;
  }
  if (status !== "granted") return;

  if (Platform.OS === "android") {
    // MAX importance => heads-up banner over apps + lock-screen visibility.
    // This is what guarantees the notification appears in the Android
    // system drawer (the drop-down) for missed / day-of appointments.
    await Notifications.setNotificationChannelAsync("default", {
      name: "Cognizant Care",
      importance: Notifications.AndroidImportance.MAX,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#000048",
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      sound: "default",
      enableLights: true,
      enableVibrate: true,
      showBadge: true,
    });
    await Notifications.setNotificationChannelAsync("appointments", {
      name: "Appointment reminders",
      importance: Notifications.AndroidImportance.MAX,
      description: "Day-before, day-of, and missed appointment alerts",
      vibrationPattern: [0, 300, 200, 300],
      lightColor: "#26EFE9",
      lockscreenVisibility: Notifications.AndroidNotificationVisibility.PUBLIC,
      sound: "default",
      enableVibrate: true,
      showBadge: true,
    });
  }

  try {
    // Expo devicePushToken returns the raw FCM token on Android (when google-services.json is in the build)
    const tokenRes = await Notifications.getDevicePushTokenAsync();
    if (tokenRes?.data) {
      await registerPushToken(tokenRes.data);
    }
  } catch (_) {
    // Fail silently — reminders still work via email + in-app proactive messages
  }
}
