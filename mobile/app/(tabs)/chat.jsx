import { useRef, useState } from "react";
import {
  View, Text, TextInput, TouchableOpacity, StyleSheet, FlatList,
  KeyboardAvoidingView, Platform, ActivityIndicator,
} from "react-native";
import { sendChat } from "../../src/lib/api";

export default function Chat() {
  const [messages, setMessages] = useState([
    { role: "bot", text: "Hi — I'm your personal health assistant. Ask about your care gaps, appointments, or screenings." },
  ]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const listRef = useRef(null);

  const handleSend = async () => {
    const msg = input.trim();
    if (!msg || sending) return;
    setMessages(prev => [...prev, { role: "user", text: msg }]);
    setInput("");
    setSending(true);
    try {
      const reply = await sendChat(msg);
      setMessages(prev => [...prev, { role: "bot", text: reply }]);
    } catch (e) {
      setMessages(prev => [...prev, { role: "bot", text: "Sorry, something went wrong. Try again." }]);
    } finally {
      setSending(false);
      setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 100);
    }
  };

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      keyboardVerticalOffset={80}
    >
      <FlatList
        ref={listRef}
        data={messages}
        keyExtractor={(_, i) => String(i)}
        contentContainerStyle={{ padding: 12 }}
        renderItem={({ item }) => (
          <View style={[styles.bubble, item.role === "user" ? styles.userBubble : styles.botBubble]}>
            <Text style={item.role === "user" ? styles.userText : styles.botText}>{item.text}</Text>
          </View>
        )}
      />
      {sending && (
        <View style={styles.typing}>
          <ActivityIndicator size="small" color="#0033a0" />
          <Text style={styles.typingText}>Thinking...</Text>
        </View>
      )}
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Ask about your health..."
          placeholderTextColor="#9ca3af"
          value={input}
          onChangeText={setInput}
          multiline
        />
        <TouchableOpacity style={styles.sendBtn} onPress={handleSend} disabled={sending}>
          <Text style={styles.sendText}>Send</Text>
        </TouchableOpacity>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: "#f3f4f6" },
  bubble: { maxWidth: "80%", padding: 12, borderRadius: 14, marginVertical: 4 },
  userBubble: { alignSelf: "flex-end", backgroundColor: "#0033a0" },
  botBubble: { alignSelf: "flex-start", backgroundColor: "#fff", borderWidth: 1, borderColor: "#e5e7eb" },
  userText: { color: "#fff", fontSize: 14 },
  botText: { color: "#111827", fontSize: 14 },
  typing: { flexDirection: "row", alignItems: "center", paddingHorizontal: 16, paddingVertical: 4 },
  typingText: { marginLeft: 6, color: "#6b7280", fontSize: 12 },
  inputRow: {
    flexDirection: "row", alignItems: "flex-end", padding: 8, backgroundColor: "#fff",
    borderTopWidth: 1, borderTopColor: "#e5e7eb",
  },
  input: {
    flex: 1, borderWidth: 1, borderColor: "#e5e7eb", borderRadius: 20,
    paddingHorizontal: 14, paddingVertical: 10, fontSize: 14, backgroundColor: "#f9fafb",
    maxHeight: 120,
  },
  sendBtn: {
    marginLeft: 8, backgroundColor: "#0033a0", paddingHorizontal: 16,
    paddingVertical: 12, borderRadius: 20,
  },
  sendText: { color: "#fff", fontWeight: "700", fontSize: 14 },
});
