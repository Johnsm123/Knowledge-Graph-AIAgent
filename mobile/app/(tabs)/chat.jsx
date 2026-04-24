import { useEffect, useRef, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, FlatList,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import * as Location from "expo-location";
import { sendChat, fetchProactiveMessages } from "../../src/lib/api";
import { COG, TYPE, S } from "../../src/lib/brand";
import ChatAttachment from "../../src/components/ChatAttachment";

const QUICK_PROMPTS = [
  "Show my open care gaps",
  "Book a screening",
  "My upcoming appointments",
  "Update my phone number",
];

export default function Chat() {
  const [messages, setMessages] = useState([
    {
      role: "bot",
      text: "Hello — I'm your Cognizant Care assistant. I can book screenings at nearby labs, answer questions about your care gaps or profile, and update your contact details. What can I help with today?",
    },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [userLocation, setUserLocation] = useState(null);
  const listRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const { status } = await Location.requestForegroundPermissionsAsync();
        if (status !== "granted") return;
        const pos = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
        setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
      } catch (_) {}
    })();

    // Surface any queued proactive reminders as bot messages
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

  const renderItem = ({ item }) => {
    const isUser = item.role === "user";
    return (
      <View>
        <View style={[styles.row, { justifyContent: isUser ? "flex-end" : "flex-start" }]}>
          {!isUser && <View style={styles.avatar}><Text style={styles.avatarText}>C</Text></View>}
          <View style={[styles.bubble, isUser ? styles.userBubble : styles.botBubble]}>
            <Text style={isUser ? styles.userText : styles.botText}>{item.text}</Text>
          </View>
        </View>
        {!isUser && item.attachment ? (
          <ChatAttachment attachment={item.attachment} onSelect={(msg) => send(msg)} />
        ) : null}
      </View>
    );
  };

  return (
    <KeyboardAvoidingView style={styles.container} behavior={Platform.OS === "ios" ? "padding" : undefined} keyboardVerticalOffset={80}>
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={{ padding: 14, paddingBottom: 80 }}
        renderItem={renderItem}
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
        />
        <TouchableOpacity style={[styles.sendBtn, (!input.trim() || sending) && { opacity: 0.5 }]} onPress={() => send()} disabled={sending || !input.trim()}>
          <Text style={styles.sendText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: COG.grayLightest },
  row: { flexDirection: "row", alignItems: "flex-end", marginVertical: 4 },
  avatar: {
    width: 28, height: 28, borderRadius: 14,
    backgroundColor: COG.tealLight, alignItems: "center", justifyContent: "center",
    marginRight: 6, borderWidth: 2, borderColor: COG.primary,
  },
  avatarText: { color: COG.primary, fontSize: 12, fontWeight: "800" },
  bubble: { maxWidth: "78%", padding: 12, borderRadius: 14 },
  userBubble: {
    backgroundColor: COG.primary,
    borderBottomRightRadius: 4,
  },
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
  suggestWrap: { marginTop: 10 },
  suggestLabel: { ...TYPE.tiny, color: COG.grayDark, marginBottom: 8, marginLeft: 4 },
  suggestChip: {
    backgroundColor: COG.white, borderWidth: 1, borderColor: COG.blueLight,
    borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8, marginBottom: 6,
    alignSelf: "flex-start",
  },
  suggestText: { color: COG.blueDark, fontWeight: "600", fontSize: 13 },
});
