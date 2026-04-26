import { useEffect, useRef, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, FlatList,
  KeyboardAvoidingView, Platform, ActivityIndicator, ScrollView, Keyboard,
} from "react-native";
import { useHeaderHeight } from "@react-navigation/elements";
import * as Location from "expo-location";
import { sendChat, fetchProactiveMessages } from "../../src/lib/api";
import { COG, TYPE, S } from "../../src/lib/brand";
import ChatAttachment from "../../src/components/ChatAttachment";
import CogMark from "../../src/components/CogMark";
import MarkdownText from "../../src/components/MarkdownText";

const QUICK_PROMPTS = [
  "Show my open care gaps",
  "Book a screening",
  "My upcoming appointments",
  "Who is my doctor?",
  "Update my phone number",
];

// Contextual quick-reply hints per attachment type OR recent bot keywords.
// These are rendered as tappable chips directly under the bot's reply.
function suggestedReplies({ attachment, botText }) {
  if (attachment?.type === "labs")             return ["Show me more labs", "Any with better ratings?"];
  if (attachment?.type === "slots")            return ["Show more times", "Prefer weekend slots"];
  if (attachment?.type === "booking_confirmed") return ["Thanks!", "Can I add directions to my calendar?"];
  if (attachment?.type === "location_prompt")   return ["Skip location — show any labs"];
  if (attachment?.type === "profile_summary")  return ["Update my phone", "Show my care gaps"];
  if (attachment?.type === "gap_list")         return ["Tell me about the most urgent", "Book the first one"];
  if (attachment?.type === "appointments_list") return ["Reschedule the next one", "Directions to next lab"];

  // Keyword-based fallback on bot text
  const t = (botText || "").toLowerCase();
  if (t.includes("care gap")) return ["Book my top care gap", "Why do I need this screening?"];
  if (t.includes("doctor") || t.includes("physician")) return ["How do I reach my doctor?", "Book with my doctor"];
  if (t.includes("book"))    return ["Book my BCS screening", "Book my CDC screening"];
  return ["Book a screening", "My care gaps", "Update my profile"];
}

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: "bot",
      text: "Hi! I'm your Cognizant Care assistant. I can book screenings at nearby labs, answer questions about your care gaps or profile, and update your contact details. What would you like to do?",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [userLocation, setUserLocation] = useState(null);
  const listRef = useRef(null);
  const headerHeight = useHeaderHeight();

  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") return;
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
      } catch (_) {}
    })();

    (async () => {
      const proactive = await fetchProactiveMessages();
      if (proactive.length) {
        setMessages(prev => [
          ...prev,
          ...proactive.map(m => ({ role: "bot", text: m.text, kind: m.kind })),
        ]);
        setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
      }
    })();
  }, []);

  const send = async (text) => {
    const msg = (text ?? input).trim();
    if (!msg || sending) return;
    Keyboard.dismiss();
    setMessages(prev => [...prev, { role: "user", text: msg }]);
    setInput("");
    setSending(true);
    try {
      const { reply, attachment } = await sendChat(msg, userLocation);
      setMessages(prev => [...prev, { role: "bot", text: reply, attachment }]);
    } catch (_) {
      setMessages(prev => [...prev, { role: "bot", text: "Something went wrong on my end. Please try again in a moment." }]);
    } finally {
      setSending(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 80);
    }
  };

  const renderItem = ({ item, index }) => {
    const isUser = item.role === "user";
    const isLatestBot = !isUser && index === messages.length - 1;

    return (
      <View>
        <View style={[styles.row, { justifyContent: isUser ? "flex-end" : "flex-start" }]}>
          {!isUser && <CogMark size={28} style={{ marginRight: 6 }} />}
          <View style={[styles.bubble, isUser ? styles.userBubble : styles.botBubble]}>
            {isUser ? (
              <Text style={styles.userText}>{item.text}</Text>
            ) : (
              <MarkdownText text={item.text} style={styles.botText} />
            )}
          </View>
        </View>

        {!isUser && item.attachment ? (
          <ChatAttachment attachment={item.attachment} onSelect={(msg) => send(msg)} />
        ) : null}

        {/* Contextual quick-reply chips under the latest bot message only */}
        {isLatestBot && !sending ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.chipRow}
          >
            {suggestedReplies({ attachment: item.attachment, botText: item.text }).map((c, i) => (
              <TouchableOpacity key={i} style={styles.chip} onPress={() => send(c)}>
                <Text style={styles.chipText}>{c}</Text>
              </TouchableOpacity>
            ))}
          </ScrollView>
        ) : null}
      </View>
    );
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : "height"}
      keyboardVerticalOffset={headerHeight + (Platform.OS === "android" ? 12 : 0)}
    >
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={{ padding: 14, paddingBottom: 24 }}
        renderItem={renderItem}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
        keyboardShouldPersistTaps="handled"
        ListFooterComponent={messages.length === 1 ? (
          <View style={styles.suggestWrap}>
            <Text style={styles.suggestLabel}>Try asking</Text>
            {QUICK_PROMPTS.map((p, i) => (
              <TouchableOpacity key={i} style={styles.suggestChip} onPress={() => send(p)}>
                <Text style={styles.suggestText}>{p}</Text>
              </TouchableOpacity>
            ))}
          </View>
        ) : null}
      />

      {sending && (
        <View style={styles.typing}>
          <ActivityIndicator size="small" color={COG.primary} />
          <Text style={styles.typingText}>Assistant is thinking...</Text>
        </View>
      )}

      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Ask about your care or book an appointment..."
          placeholderTextColor={COG.grayMedium}
          value={input}
          onChangeText={setInput}
          multiline
          blurOnSubmit={false}
        />
        <TouchableOpacity
          style={[styles.sendBtn, (!input.trim() || sending) && { opacity: 0.5 }]}
          onPress={() => send()}
          disabled={sending || !input.trim()}
        >
          <Text style={styles.sendText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.grayLightest },
  row: { flexDirection: "row", alignItems: "flex-end", marginVertical: 4 },
  bubble: { maxWidth: "78%", padding: 12, borderRadius: 14 },
  userBubble: { backgroundColor: COG.primary, borderBottomRightRadius: 4 },
  botBubble: {
    backgroundColor: COG.white, borderWidth: 1, borderColor: COG.grayLighter,
    borderBottomLeftRadius: 4,
  },
  userText: { color: COG.white, fontSize: 14, lineHeight: 20 },
  botText: { color: COG.primary, fontSize: 14, lineHeight: 20 },
  typing: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 6 },
  typingText: { marginLeft: 8, color: COG.grayDark, fontSize: 12 },
  inputRow: {
    flexDirection: "row", alignItems: "flex-end", padding: 10, backgroundColor: COG.white,
    borderTopWidth: 1, borderTopColor: COG.grayLighter,
  },
  input: {
    flex: 1, borderWidth: 1, borderColor: COG.grayLighter, borderRadius: 20,
    paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, color: COG.primary,
    backgroundColor: COG.grayLightest, maxHeight: 120,
  },
  sendBtn: {
    marginLeft: 8, backgroundColor: COG.tealLight, paddingHorizontal: 18, paddingVertical: 12,
    borderRadius: 999,
  },
  sendText: { color: COG.primary, fontWeight: "700", fontSize: 14 },

  // Initial full-screen "try asking" list (first open)
  suggestWrap: { marginTop: 10 },
  suggestLabel: { ...TYPE.tiny, color: COG.grayDark, marginBottom: 8, marginLeft: 4 },
  suggestChip: {
    backgroundColor: COG.white, borderWidth: 1, borderColor: COG.blueLight,
    borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, marginBottom: 6,
    alignSelf: "flex-start",
  },
  suggestText: { color: COG.blueDark, fontWeight: "600", fontSize: 13 },

  // Contextual quick-reply chip row (horizontal, under each bot reply)
  chipRow: { paddingLeft: 34, paddingVertical: 6, gap: 6 },
  chip: {
    backgroundColor: COG.grayLightest, borderWidth: 1, borderColor: COG.blueLight,
    borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6, marginRight: 6,
  },
  chipText: { color: COG.blueDark, fontWeight: "600", fontSize: 12 },
});
