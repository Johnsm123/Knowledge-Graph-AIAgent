import { Text, View, StyleSheet } from "react-native";
import { COG } from "../lib/brand";

/**
 * Lightweight inline-markdown renderer for chatbot responses.
 *
 * Supports — without any external dependency:
 *   **bold**        → bold weight
 *   *italic*        → italic style
 *   `code`          → mono background pill
 *   - bullet lines  → rendered with a coloured bullet
 *   1. numbered    → rendered with the number left-aligned
 *   blank line      → vertical space
 *
 * Unsupported tokens (HTML, tables, headings >####) are stripped of their
 * markers and rendered as plain text — never leaked as raw `**` to the user.
 */
export default function MarkdownText({ text, style }) {
  const cleaned = (text || "")
    // Drop any leaked <thinking>...</thinking> blocks just in case
    .replace(/<thinking>[\s\S]*?<\/thinking>/gi, "")
    .replace(/<\/?[a-z][^>]*>/gi, "")
    // Normalise CRLF
    .replace(/\r\n/g, "\n")
    .trim();

  const lines = cleaned.split("\n");
  const elements = [];

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];
    const line = raw.replace(/\s+$/, "");

    // blank line → small vertical gap
    if (!line.trim()) {
      elements.push(<View key={`sp-${i}`} style={styles.gap} />);
      continue;
    }

    // bullet:  - foo   or   * foo
    const bullet = line.match(/^\s*[-*]\s+(.*)$/);
    if (bullet) {
      elements.push(
        <View key={i} style={styles.bulletRow}>
          <Text style={styles.bullet}>•</Text>
          <Text style={[styles.line, style]}>{renderInline(bullet[1])}</Text>
        </View>
      );
      continue;
    }

    // numbered:  1. foo   2. foo
    const num = line.match(/^\s*(\d+)\.\s+(.*)$/);
    if (num) {
      elements.push(
        <View key={i} style={styles.bulletRow}>
          <Text style={styles.numberToken}>{num[1]}.</Text>
          <Text style={[styles.line, style]}>{renderInline(num[2])}</Text>
        </View>
      );
      continue;
    }

    // heading-ish:  #### foo  → render bold, no hash chars
    const heading = line.match(/^#{1,6}\s+(.*)$/);
    if (heading) {
      elements.push(
        <Text key={i} style={[styles.heading, style]}>{renderInline(heading[1])}</Text>
      );
      continue;
    }

    // plain paragraph line
    elements.push(
      <Text key={i} style={[styles.line, style]}>{renderInline(line)}</Text>
    );
  }

  return <View>{elements}</View>;
}

/**
 * Parse inline markdown spans (bold / italic / code) inside a single line
 * and return an array of styled <Text> children.
 */
function renderInline(text) {
  if (!text) return null;

  // Tokenise on `**bold**`, `*italic*`, `` `code` `` — preserve order.
  const re = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\*[^*\n]+\*)/g;
  const out = [];
  let last = 0;
  let match;
  let key = 0;

  while ((match = re.exec(text)) !== null) {
    if (match.index > last) {
      out.push(<Text key={key++}>{text.slice(last, match.index)}</Text>);
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      out.push(<Text key={key++} style={styles.bold}>{token.slice(2, -2)}</Text>);
    } else if (token.startsWith("`") && token.endsWith("`")) {
      out.push(<Text key={key++} style={styles.code}>{token.slice(1, -1)}</Text>);
    } else if (token.startsWith("*") && token.endsWith("*")) {
      out.push(<Text key={key++} style={styles.italic}>{token.slice(1, -1)}</Text>);
    } else {
      out.push(<Text key={key++}>{token}</Text>);
    }
    last = re.lastIndex;
  }
  if (last < text.length) {
    out.push(<Text key={key++}>{text.slice(last)}</Text>);
  }
  return out;
}

const styles = StyleSheet.create({
  line:        { fontSize: 14, lineHeight: 20, color: COG.primary },
  heading:     { fontSize: 15, fontWeight: "800", color: COG.primary, marginTop: 4, marginBottom: 2, lineHeight: 21 },
  bullet:      { fontSize: 14, fontWeight: "700", color: COG.tealLight, marginRight: 8, marginTop: 1 },
  numberToken: { fontSize: 13, fontWeight: "800", color: COG.blueDark, marginRight: 8, minWidth: 20 },
  bulletRow:   { flexDirection: "row", alignItems: "flex-start", marginVertical: 2 },
  bold:        { fontWeight: "800" },
  italic:      { fontStyle: "italic" },
  code:        {
    fontFamily: "monospace",
    backgroundColor: COG.grayLighter,
    fontSize: 13,
    paddingHorizontal: 4,
    borderRadius: 4,
  },
  gap:         { height: 6 },
});
