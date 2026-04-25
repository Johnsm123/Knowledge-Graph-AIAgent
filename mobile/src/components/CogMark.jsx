import { View, Text, StyleSheet } from "react-native";
import { COG } from "../lib/brand";

/**
 * Symbol-only Cognizant brand mark — for tight circular spaces (avatars, badges).
 * Renders a midnight-blue disc with a stylised teal arc cutaway, evoking the
 * Cognizant brand symbol without depending on a square-cropped asset.
 *
 * Pass `size` to set diameter. Default 32.
 */
export default function CogMark({ size = 32, style }) {
  const r = size / 2;
  return (
    <View
      style={[
        styles.disc,
        { width: size, height: size, borderRadius: r },
        style,
      ]}
    >
      {/* Subtle teal sweep evokes the Cognizant brand symbol */}
      <View
        style={{
          position: "absolute",
          width: size * 0.85,
          height: size * 0.85,
          borderRadius: size,
          borderWidth: size * 0.18,
          borderColor: "transparent",
          borderTopColor: COG.tealLight,
          borderRightColor: COG.tealLight,
          transform: [{ rotate: "-35deg" }],
        }}
      />
      <Text
        style={{
          color: COG.white,
          fontSize: size * 0.42,
          fontWeight: "800",
          letterSpacing: -0.5,
        }}
      >
        c
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  disc: {
    backgroundColor: COG.primary,
    alignItems: "center",
    justifyContent: "center",
    overflow: "hidden",
  },
});
