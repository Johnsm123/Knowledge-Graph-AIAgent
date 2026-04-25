import { useEffect, useRef } from "react";
import { View, Animated, StyleSheet, Easing } from "react-native";
import CogLogo from "./CogLogo";
import { COG } from "../lib/brand";

/**
 * Branded animated splash:
 *   1. Slides logo in from the left
 *   2. Subtle shimmer sweep across the logo (lighter teal gradient bar)
 *   3. Fades out, then calls onFinish so the host can navigate away.
 *
 * Use as a full-screen overlay during initial app load.
 */
export default function AnimatedSplash({ onFinish }) {
  const slide   = useRef(new Animated.Value(-80)).current;  // logo X offset
  const fade    = useRef(new Animated.Value(0)).current;    // logo opacity
  const shimmer = useRef(new Animated.Value(-180)).current; // shimmer X position
  const out     = useRef(new Animated.Value(1)).current;    // whole-screen fade-out

  useEffect(() => {
    Animated.parallel([
      Animated.timing(slide, { toValue: 0,   duration: 800,  easing: Easing.out(Easing.cubic), useNativeDriver: true }),
      Animated.timing(fade,  { toValue: 1,   duration: 600,  useNativeDriver: true }),
    ]).start(() => {
      Animated.timing(shimmer, {
        toValue: 220, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true,
      }).start(() => {
        Animated.timing(out, { toValue: 0, duration: 400, useNativeDriver: true }).start(() => {
          onFinish?.();
        });
      });
    });
  }, []);

  return (
    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFillObject, styles.root, { opacity: out }]}>
      <Animated.View style={{ transform: [{ translateX: slide }], opacity: fade }}>
        <View style={styles.logoWrap}>
          <CogLogo variant="light" size={68} />
          <Animated.View
            style={[
              styles.shimmer,
              { transform: [{ translateX: shimmer }, { skewX: "-20deg" }] },
            ]}
          />
        </View>
      </Animated.View>
      <Animated.Text style={[styles.tagline, { opacity: fade }]}>
        Care, intelligently delivered.
      </Animated.Text>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  root: {
    backgroundColor: COG.primary,
    justifyContent: "center",
    alignItems: "center",
  },
  logoWrap: {
    overflow: "hidden",
    paddingHorizontal: 6,
    paddingVertical: 4,
  },
  shimmer: {
    position: "absolute",
    top: -20, bottom: -20, left: 0, width: 60,
    backgroundColor: "rgba(255,255,255,0.32)",
  },
  tagline: {
    color: COG.tealLight,
    marginTop: 18,
    fontSize: 14,
    letterSpacing: 1.5,
    fontWeight: "500",
    textTransform: "uppercase",
  },
});
