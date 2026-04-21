import { Tabs } from "expo-router";
import { Text } from "react-native";

const icon = (emoji) => ({ color, size }) => (
  <Text style={{ fontSize: size ?? 20, color }}>{emoji}</Text>
);

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        tabBarActiveTintColor: "#0033a0",
        tabBarInactiveTintColor: "#9ca3af",
        headerStyle: { backgroundColor: "#0033a0" },
        headerTintColor: "#fff",
        headerTitleStyle: { fontWeight: "700" },
      }}
    >
      <Tabs.Screen
        name="home"
        options={{ title: "Home", tabBarIcon: icon("🏠") }}
      />
      <Tabs.Screen
        name="appointments"
        options={{ title: "Appointments", tabBarIcon: icon("📅") }}
      />
      <Tabs.Screen
        name="chat"
        options={{ title: "Assistant", tabBarIcon: icon("💬") }}
      />
    </Tabs>
  );
}
