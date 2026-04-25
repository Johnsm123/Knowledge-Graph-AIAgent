import { Tabs } from "expo-router";
import { Text, View } from "react-native";
import { COG } from "../../src/lib/brand";
import CogLogo from "../../src/components/CogLogo";

const icon = (emoji) => ({ color, size }) => (
  <Text style={{ fontSize: size ?? 20, color }}>{emoji}</Text>
);

const cogHeader = (label) => () => (
  <View style={{ flexDirection: "row", alignItems: "center" }}>
    <CogLogo variant="light" size={22} />
    <Text style={{ color: COG.white, fontWeight: "700", fontSize: 16, marginLeft: 12, letterSpacing: 0.3 }}>
      {label}
    </Text>
  </View>
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
      <Tabs.Screen name="home"         options={{ headerTitle: cogHeader("Home"),         title: "Home",         tabBarIcon: icon("🏠") }} />
      <Tabs.Screen name="appointments" options={{ headerTitle: cogHeader("Appointments"), title: "Appointments", tabBarIcon: icon("📅") }} />
      <Tabs.Screen name="chat"         options={{ headerTitle: cogHeader("Assistant"),    title: "Assistant",    tabBarIcon: icon("💬") }} />
      <Tabs.Screen name="profile"      options={{ headerTitle: cogHeader("Profile"),      title: "Profile",      tabBarIcon: icon("👤") }} />
    </Tabs>
  );
}
