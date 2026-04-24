import { useMemo, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Platform, Linking } from "react-native";
import * as Location from "expo-location";
import { COG, TYPE, S } from "../lib/brand";

// Lazy-require react-native-maps so missing native module doesn't crash the whole app
let MapView = null;
let Marker = null;
try {
  const maps = require("react-native-maps");
  MapView = maps.default;
  Marker = maps.Marker;
} catch (_) {}

// ── Public entry ────────────────────────────────────────────────────────────

export default function ChatAttachment({ attachment, onSelect }) {
  if (!attachment) return null;
  if (attachment.type === "labs")               return <LabsAttachment  data={attachment} onSelect={onSelect} />;
  if (attachment.type === "slots")              return <SlotsAttachment data={attachment} onSelect={onSelect} />;
  if (attachment.type === "booking_confirmed")  return <BookingConfirmed data={attachment} />;
  if (attachment.type === "location_prompt")    return <LocationPrompt   data={attachment} onSelect={onSelect} />;
  return null;
}

// ── Location permission prompt ──────────────────────────────────────────────

function LocationPrompt({ data, onSelect }) {
  const [requesting, setRequesting] = useState(false);

  const handleEnable = async () => {
    setRequesting(true);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status === "granted") {
        onSelect?.("I've enabled location — please find nearby labs now.");
      } else {
        // Permission denied persistently; open Settings
        Linking.openSettings();
      }
    } catch (_) {
      Linking.openSettings();
    } finally {
      setRequesting(false);
    }
  };

  return (
    <View style={[styles.attachment, { backgroundColor: "#FFF8E1", borderColor: COG.yellow }]}>
      <Text style={styles.locTitle}>📍 Location access needed</Text>
      <Text style={styles.locBody}>{data.message || "Enable location to find nearby labs."}</Text>
      <TouchableOpacity style={styles.confirmBtn} onPress={handleEnable} disabled={requesting}>
        <Text style={styles.confirmText}>{requesting ? "Requesting..." : "Enable location"}</Text>
      </TouchableOpacity>
    </View>
  );
}

// ── Labs: mini map + list of cards ──────────────────────────────────────────

function LabsAttachment({ data, onSelect }) {
  const items = data.items || [];
  const userLoc = data.user_location;
  const [active, setActive] = useState(null);

  const region = useMemo(() => {
    if (!userLoc?.lat) return null;
    return { latitude: userLoc.lat, longitude: userLoc.lng, latitudeDelta: 0.045, longitudeDelta: 0.045 };
  }, [userLoc]);

  return (
    <View style={styles.attachment}>
      {MapView && region ? (
        <MapView style={styles.map} initialRegion={region}>
          <Marker coordinate={{ latitude: userLoc.lat, longitude: userLoc.lng }} title="You" pinColor={COG.tealLight} />
          {items.map((l) => (l.lat && l.lng ? (
            <Marker
              key={l.place_id}
              coordinate={{ latitude: l.lat, longitude: l.lng }}
              title={l.name}
              description={l.address}
              pinColor={active === l.place_id ? COG.red : COG.primary}
              onPress={() => setActive(l.place_id)}
            />
          ) : null))}
        </MapView>
      ) : (
        <View style={styles.mapFallback}>
          <Text style={TYPE.tiny}>
            {MapView ? "Share location to see the map" : "Map preview unavailable in Expo Go. Labs list below works either way."}
          </Text>
        </View>
      )}

      <Text style={styles.sectionHdr}>Nearby labs ({items.length})</Text>
      {items.map((l) => (
        <TouchableOpacity
          key={l.place_id}
          style={[styles.labCard, active === l.place_id && styles.labCardActive]}
          onPress={() => setActive(l.place_id)}
        >
          <View style={{ flex: 1 }}>
            <Text style={styles.labName}>{l.name}</Text>
            {!!l.address && <Text style={styles.labAddr}>{l.address}</Text>}
            {l.rating != null && (
              <Text style={styles.labRating}>
                ★ {Number(l.rating).toFixed(1)}
                {l.open_now === true  ? "  ·  Open now"  : ""}
                {l.open_now === false ? "  ·  Closed"   : ""}
              </Text>
            )}
          </View>
          <View style={[styles.pickBtn, active === l.place_id && styles.pickBtnActive]}>
            <Text style={[styles.pickText, active === l.place_id && styles.pickTextActive]}>
              {active === l.place_id ? "Selected" : "Pick"}
            </Text>
          </View>
        </TouchableOpacity>
      ))}

      {active && (
        <TouchableOpacity
          style={styles.confirmBtn}
          onPress={() => {
            const sel = items.find((x) => x.place_id === active);
            if (sel) onSelect?.(`I choose ${sel.name} at ${sel.address || ""}`.trim());
          }}
        >
          <Text style={styles.confirmText}>Confirm this lab</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

// ── Slot picker ─────────────────────────────────────────────────────────────

function SlotsAttachment({ data, onSelect }) {
  const items = data.items || [];
  const [pick, setPick] = useState(null);

  // Group slots by date
  const grouped = useMemo(() => {
    const m = new Map();
    for (const s of items) {
      const key = s.date;
      if (!m.has(key)) m.set(key, { display: s.display_date, times: [] });
      m.get(key).times.push(s);
    }
    return [...m.entries()];
  }, [items]);

  return (
    <View style={styles.attachment}>
      <Text style={styles.sectionHdr}>Pick a date & time</Text>
      {grouped.map(([date, info]) => (
        <View key={date} style={styles.slotBlock}>
          <Text style={styles.slotDate}>{info.display}</Text>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={{ paddingVertical: 4 }}>
            {info.times.map((s, i) => {
              const id = `${s.date}|${s.time}`;
              const selected = pick === id;
              return (
                <TouchableOpacity
                  key={i}
                  style={[styles.timeChip, selected && styles.timeChipActive]}
                  onPress={() => setPick(id)}
                >
                  <Text style={[styles.timeText, selected && styles.timeTextActive]}>
                    {s.display_time || s.time}
                  </Text>
                </TouchableOpacity>
              );
            })}
          </ScrollView>
        </View>
      ))}
      {pick && (
        <TouchableOpacity
          style={styles.confirmBtn}
          onPress={() => {
            const s = items.find((x) => `${x.date}|${x.time}` === pick);
            if (s) onSelect?.(`I'll take ${s.display_date || s.date} at ${s.display_time || s.time}`);
          }}
        >
          <Text style={styles.confirmText}>Confirm this slot</Text>
        </TouchableOpacity>
      )}
    </View>
  );
}

// ── Booking confirmed summary ───────────────────────────────────────────────

function BookingConfirmed({ data }) {
  const a = data.appointment || {};
  return (
    <View style={[styles.attachment, { backgroundColor: COG.white, borderColor: COG.green, borderWidth: 2 }]}>
      <View style={styles.confirmedHdr}>
        <Text style={styles.confirmedTitle}>✓ Appointment confirmed</Text>
      </View>
      <Row label="Screening"  value={a.measure_name || a.measure_id} />
      <Row label="Date"       value={a.friendly_date || a.appointment_date} />
      <Row label="Time"       value={a.friendly_time || a.appointment_time} />
      {a.lab_location ? <Row label="Location" value={a.lab_location} /> : null}
      {a.appointment_id ? <Row label="Reference" value={a.appointment_id} last /> : null}
      <Text style={styles.confirmedNote}>A confirmation email has been sent to you.</Text>
    </View>
  );
}

function Row({ label, value, last }) {
  return (
    <View style={[styles.row, last && { borderBottomWidth: 0 }]}>
      <Text style={styles.rowLabel}>{label}</Text>
      <Text style={styles.rowValue}>{value}</Text>
    </View>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  attachment: {
    marginTop: 8,
    marginLeft: 34,         // align with bot bubble (avatar width + gap)
    marginRight: S.sm,
    backgroundColor: COG.white,
    borderWidth: 1,
    borderColor: COG.grayLighter,
    padding: 10,
  },
  map: { width: "100%", height: 180, marginBottom: 8, borderRadius: 0 },
  mapFallback: {
    width: "100%", height: 80, backgroundColor: COG.grayLightest,
    justifyContent: "center", alignItems: "center", marginBottom: 8,
  },
  sectionHdr: {
    fontSize: 11, fontWeight: "700", color: COG.grayDark,
    textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 6,
  },
  labCard: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  labCardActive: { backgroundColor: "rgba(38,239,233,0.08)" },
  labName:   { fontSize: 14, fontWeight: "700", color: COG.primary },
  labAddr:   { fontSize: 12, color: COG.grayDark, marginTop: 2 },
  labRating: { fontSize: 11, color: COG.blueDark, marginTop: 2 },
  pickBtn: {
    borderWidth: 1, borderColor: COG.blueDark,
    paddingHorizontal: 14, paddingVertical: 6, borderRadius: 999,
    marginLeft: 8,
  },
  pickBtnActive: { backgroundColor: COG.blueDark },
  pickText: { fontSize: 11, fontWeight: "700", color: COG.blueDark, letterSpacing: 0.3 },
  pickTextActive: { color: COG.white },

  slotBlock: { marginBottom: 10 },
  slotDate: { fontSize: 13, fontWeight: "700", color: COG.primary, marginBottom: 4 },
  timeChip: {
    borderWidth: 1, borderColor: COG.blueDark, backgroundColor: COG.white,
    paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, marginRight: 6,
  },
  timeChipActive: { backgroundColor: COG.blueDark },
  timeText: { fontSize: 12, fontWeight: "600", color: COG.blueDark, letterSpacing: 0.2 },
  timeTextActive: { color: COG.white },

  confirmBtn: {
    backgroundColor: COG.tealLight,
    paddingVertical: 12, borderRadius: 999,
    alignItems: "center", marginTop: 8,
  },
  confirmText: { color: COG.primary, fontWeight: "700", fontSize: 14 },

  confirmedHdr: { paddingVertical: 6, alignItems: "center", marginBottom: 4 },
  confirmedTitle: { color: COG.green, fontSize: 15, fontWeight: "800" },
  row: {
    flexDirection: "row", justifyContent: "space-between",
    paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  rowLabel: { fontSize: 12, color: COG.grayDark },
  rowValue: { fontSize: 13, fontWeight: "700", color: COG.primary, maxWidth: "60%", textAlign: "right" },
  confirmedNote: { fontSize: 11, color: COG.grayDark, textAlign: "center", marginTop: 8 },
  locTitle: { fontSize: 13, fontWeight: "700", color: COG.primary, marginBottom: 4 },
  locBody:  { fontSize: 12, color: COG.grayDark, marginBottom: 8 },
});
