import { useEffect, useRef } from "react";
import { View, Text, StyleSheet, Animated, Easing, Dimensions } from "react-native";
import { useRouter } from "expo-router";
import { getSession } from "../src/lib/api";
import { COG } from "../src/lib/brand";

const { width: W } = Dimensions.get("window");

export default function SplashIndex() {
  const router = useRouter();

  const logoOpacity = useRef(new Animated.Value(0)).current;
  const logoScale   = useRef(new Animated.Value(0.85)).current;
  const wordOpacity = useRef(new Animated.Value(0)).current;
  const wordSlide   = useRef(new Animated.Value(30)).current;
  const shineX      = useRef(new Animated.Value(-W)).current;
  const taglineOp   = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.parallel([
      Animated.timing(logoOpacity, { toValue: 1, duration: 600, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
      Animated.spring(logoScale,   { toValue: 1, friction: 6, tension: 40, useNativeDriver: true }),
    ]).start();

    Animated.parallel([
      Animated.timing(wordOpacity, { toValue: 1, duration: 700, delay: 250, useNativeDriver: true }),
      Animated.timing(wordSlide,   { toValue: 0, duration: 700, delay: 250, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
    ]).start();

    Animated.loop(
      Animated.sequence([
        Animated.timing(shineX, { toValue: W,  duration: 1500, delay: 600, easing: Easing.inOut(Easing.cubic), useNativeDriver: true }),
        Animated.timing(shineX, { toValue: -W, duration: 0, useNativeDriver: true }),
        Animated.delay(400),
      ]),
      { iterations: 2 }
    ).start();

    Animated.timing(taglineOp, { toValue: 1, duration: 800, delay: 1200, useNativeDriver: true }).start();

    const t = setTimeout(async () => {
      const session = await getSession();
      if (session) router.replace("/(tabs)/home");
      else router.replace("/login");
    }, 2600);
    return () => clearTimeout(t);
  }, []);

  return (
    <View style={styles.container}>
      <Animated.View style={[styles.logoBlock, { opacity: logoOpacity, transform: [{ scale: logoScale }] }]}>
        <View style={styles.logoMark}>
          <View style={styles.logoInner} />
        </View>
      </Animated.View>

      <View style={styles.wordWrap}>
        <Animated.Text style={[styles.word, { opacity: wordOpacity, transform: [{ translateY: wordSlide }] }]}>
          Cognizant
        </Animated.Text>
        <Animated.View pointerEvents="none" style={[styles.shine, { transform: [{ translateX: shineX }, { skewX: "-20deg" }] }]} />
      </View>

      <Animated.Text style={[styles.tagline, { opacity: taglineOp }]}>
        Care  ·  Connected  ·  Cognizant
      </Animated.Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.primary, justifyContent: "center", alignItems: "center" },
  logoBlock: { marginBottom: 28 },
  logoMark: {
    width: 74, height: 74, borderRadius: 37, backgroundColor: COG.tealLight,
    justifyContent: "center", alignItems: "center", borderWidth: 3, borderColor: COG.white,
  },
  logoInner: { width: 28, height: 28, backgroundColor: COG.primary, borderRadius: 14 },
  wordWrap: { overflow: "hidden", paddingHorizontal: 8, paddingVertical: 2 },
  word: { fontSize: 42, fontWeight: "800", color: COG.white, letterSpacing: -0.8 },
  shine: {
    position: "absolute", top: -10, bottom: -10, width: 80,
    backgroundColor: "rgba(38,239,233,0.38)",
  },
  tagline: { marginTop: 18, fontSize: 12, color: COG.blueLight, letterSpacing: 3, textTransform: "uppercase" },
});
