import * as Notifications from "expo-notifications";
import * as Device from "expo-device";
import { Platform } from "react-native";
import { registerPushToken } from "./api";

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
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
    await Notifications.setNotificationChannelAsync("default", {
      name: "default",
      importance: Notifications.AndroidImportance.HIGH,
      vibrationPattern: [0, 250, 250, 250],
      lightColor: "#000048",
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
