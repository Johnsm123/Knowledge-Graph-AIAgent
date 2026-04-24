import { Tabs } from "expo-router";
import { Text } from "react-native";
import { COG } from "../../src/lib/brand";

const icon = (emoji) => ({ color, size }) => (
  <Text style={{ fontSize: size ?? 20, color }}>{emoji}</Text>
);

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: COG.primary,
        tabBarInactiveTintColor: COG.grayMedium,
        tabBarStyle: { backgroundColor: COG.white, borderTopColor: COG.grayLighter },
        tabBarLabelStyle: { fontSize: 11, fontWeight: "600" },
        headerStyle: { backgroundColor: COG.primary },
        headerTintColor: COG.white,
        headerTitleStyle: { fontWeight: "700", letterSpacing: 0.3 },
      }}
    >
      <Tabs.Screen name="home"         options={{ title: "Home",         tabBarIcon: icon("🏠") }} />
      <Tabs.Screen name="appointments" options={{ title: "Appointments", tabBarIcon: icon("📅") }} />
      <Tabs.Screen name="chat"         options={{ title: "Assistant",    tabBarIcon: icon("💬") }} />
      <Tabs.Screen name="profile"      options={{ title: "Profile",      tabBarIcon: icon("👤") }} />
    </Tabs>
  );
}
