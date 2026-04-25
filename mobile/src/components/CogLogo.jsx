import { Image, View, Text, StyleSheet } from "react-native";
import { COG } from "../lib/brand";

const LOGO = require("../../assets/ct-logo.png");

/**
 * Cognizant brand mark + wordmark.
 *
 * Variants:
 *   - "dark"  (default)   for light backgrounds (logo + dark wordmark)
 *   - "light"             for dark backgrounds (logo + white wordmark)
 *   - "iconOnly"          just the logo without the "Cognizant" word
 *
 * size: pixel height of the logo image. The wordmark scales relative to it.
 */
// Default: image-only (the PNG is a horizontal Cognizant logo that already includes the wordmark).
// Pass `showWord` only if your asset is the symbol-only mark.
export default function CogLogo({ variant = "dark", size = 28, showWord = false, style }) {
  const isLight = variant === "light";
  const wordColor = isLight ? COG.white : COG.primary;
  const fontSize = Math.round(size * 0.75);

  return (
    <View style={[styles.row, style]}>
      <Image source={LOGO} style={{ height: size, width: size * (1545 / 277), resizeMode: "contain" }} />
      {showWord && variant !== "iconOnly" && (
        <Text
          style={[
            styles.word,
            {
              color: wordColor,
              fontSize,
              lineHeight: size,
              marginLeft: Math.max(8, size * 0.3),
            },
          ]}
        >
          Cognizant
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", alignItems: "center" },
  word: { fontWeight: "700", letterSpacing: -0.3 },
});
