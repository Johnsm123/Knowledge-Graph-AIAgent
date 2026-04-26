import { useMemo, useState } from "react";
import { View, Text, TouchableOpacity, StyleSheet, ScrollView, Platform, Linking } from "react-native";
import * as Location from "expo-location";
import { COG, TYPE, S } from "../lib/brand";

// NOTE: react-native-maps is intentionally NOT imported here.
// In the EAS production APK the native module isn't linked (no Google Maps API key
// + no config plugin in app.json), and rendering <MapView> would force-close
// the app on Android. The labs flow uses a clean list + "Open in Google Maps"
// CTA per lab card, which delegates to Linking.openURL — guaranteed to work.

// ── Public entry ────────────────────────────────────────────────────────────

export default function ChatAttachment({ attachment, onSelect }) {
  if (!attachment) return null;
  if (attachment.type === "labs")               return <LabsAttachment    data={attachment} onSelect={onSelect} />;
  if (attachment.type === "slots")              return <SlotsAttachment   data={attachment} onSelect={onSelect} />;
  if (attachment.type === "booking_confirmed")  return <BookingConfirmed  data={attachment} />;
  if (attachment.type === "location_prompt")    return <LocationPrompt    data={attachment} onSelect={onSelect} />;
  if (attachment.type === "profile_summary")    return <ProfileSummary    data={attachment} onSelect={onSelect} />;
  if (attachment.type === "gap_list")           return <GapList           data={attachment} onSelect={onSelect} />;
  if (attachment.type === "appointments_list") return <AppointmentsList   data={attachment} onSelect={onSelect} />;
  return null;
}

// ── Profile summary: tappable card grid ─────────────────────────────────────

function ProfileSummary({ data, onSelect }) {
  const p = data.profile || {};
  const fields = [
    { key: "name",    label: "Name",       value: p.name },
    { key: "age",     label: "Age",        value: p.age  != null ? String(p.age) : null },
    { key: "gender",  label: "Gender",     value: p.gender },
    { key: "plan",    label: "Plan",       value: p.plan },
    { key: "doctor",  label: "Doctor",     value: p.primary_care_physician },
    { key: "phone",   label: "Phone",      value: p.phone,   drill: "Update my phone number" },
    { key: "email",   label: "Email",      value: p.email,   drill: "Update my email" },
    { key: "address", label: "Address",    value: p.address, drill: "Update my address" },
  ];
  return (
    <View style={styles.attachment}>
      <Text style={styles.sectionHdr}>Your profile</Text>
      <View style={styles.grid}>
        {fields.map((f) => (
          <TouchableOpacity
            key={f.key}
            style={styles.gridCell}
            activeOpacity={f.drill ? 0.6 : 1}
            onPress={() => f.drill && onSelect?.(f.drill)}
          >
            <Text style={styles.gridLabel}>{f.label}</Text>
            <Text style={styles.gridValue} numberOfLines={2}>{f.value || "—"}</Text>
            {f.drill ? <Text style={styles.gridDrill}>Tap to update</Text> : null}
          </TouchableOpacity>
        ))}
      </View>
    </View>
  );
}

// ── Gap list: tappable cards with "Book this" button ────────────────────────

function GapList({ data, onSelect }) {
  const items = data.items || [];
  if (!items.length) {
    return (
      <View style={styles.attachment}>
        <Text style={styles.sectionHdr}>Open care gaps</Text>
        <Text style={styles.emptyText}>You have no open care gaps. Great job staying on top of your health.</Text>
      </View>
    );
  }
  return (
    <View style={styles.attachment}>
      <Text style={styles.sectionHdr}>Open care gaps ({items.length})</Text>
      {items.map((g, i) => (
        <View key={i} style={[styles.gapCard, i === items.length - 1 && { borderBottomWidth: 0 }]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.gapName}>{g.measure_name || g.measure_id}</Text>
            <Text style={styles.gapMeasure}>{g.measure_id}</Text>
            {g.description ? <Text style={styles.gapDesc} numberOfLines={2}>{g.description}</Text> : null}
          </View>
          <TouchableOpacity
            style={styles.gapBtn}
            onPress={() => onSelect?.(`Book my ${g.measure_name || g.measure_id} screening`)}
          >
            <Text style={styles.gapBtnText}>Book</Text>
          </TouchableOpacity>
        </View>
      ))}
    </View>
  );
}

// ── Appointments list ───────────────────────────────────────────────────────

function AppointmentsList({ data, onSelect }) {
  const items = data.items || [];
  if (!items.length) {
    return (
      <View style={styles.attachment}>
        <Text style={styles.sectionHdr}>Appointments</Text>
        <Text style={styles.emptyText}>No appointments yet. Ask me to book one.</Text>
      </View>
    );
  }
  return (
    <View style={styles.attachment}>
      <Text style={styles.sectionHdr}>Your appointments ({items.length})</Text>
      {items.map((a, i) => (
        <View key={i} style={[styles.apptCard, i === items.length - 1 && { borderBottomWidth: 0 }]}>
          <View style={{ flex: 1 }}>
            <Text style={styles.apptName}>{a.screening_name || a.measure_id}</Text>
            <Text style={styles.apptMeta}>{a.appointment_date} · {a.appointment_time}</Text>
            {a.lab_location ? <Text style={styles.apptLoc} numberOfLines={1}>{a.lab_location}</Text> : null}
          </View>
          <View style={[
            styles.apptStatus,
            a.status === "Completed" && { backgroundColor: COG.green },
            a.status === "Cancelled" && { backgroundColor: COG.grayMedium },
            a.status === "No Show"   && { backgroundColor: COG.red },
          ]}>
            <Text style={styles.apptStatusText}>{a.status || "Scheduled"}</Text>
          </View>
        </View>
      ))}
    </View>
  );
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

  const openMapList = () => {
    // Build a Google Maps search URL pre-populated with all returned labs near the user.
    if (userLoc?.lat) {
      Linking.openURL(`https://www.google.com/maps/search/diagnostic+lab/@${userLoc.lat},${userLoc.lng},14z`);
    } else {
      Linking.openURL("https://www.google.com/maps/search/diagnostic+lab/");
    }
  };

  return (
    <View style={styles.attachment}>
      <View style={styles.mapBanner}>
        <View style={{ flex: 1 }}>
          <Text style={styles.mapBannerTitle}>📍 Nearby diagnostic labs</Text>
          <Text style={styles.mapBannerSub}>
            {userLoc?.lat ? "We found these near your current location." : "Tap a lab below or open Google Maps for a visual view."}
          </Text>
        </View>
        <TouchableOpacity style={styles.mapBannerBtn} onPress={openMapList}>
          <Text style={styles.mapBannerBtnText}>Open in Maps</Text>
        </TouchableOpacity>
      </View>

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
            <View style={styles.labMetaRow}>
              {l.rating != null && (
                <Text style={styles.labRating}>
                  {"★".repeat(Math.round(Number(l.rating)))}
                  <Text style={styles.labRatingNum}> {Number(l.rating).toFixed(1)}</Text>
                </Text>
              )}
              {l.open_now === true  && <Text style={styles.openTag}>Open now</Text>}
              {l.open_now === false && <Text style={styles.closedTag}>Closed</Text>}
              <TouchableOpacity
                onPress={() => {
                  const url = l.lat && l.lng
                    ? `https://www.google.com/maps/dir/?api=1&destination=${l.lat},${l.lng}`
                    : `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(l.name + " " + (l.address || ""))}`;
                  Linking.openURL(url);
                }}
              >
                <Text style={styles.directionsLink}>Directions →</Text>
              </TouchableOpacity>
            </View>
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
  mapBanner: {
    flexDirection: "row", alignItems: "center",
    backgroundColor: COG.grayLightest,
    borderWidth: 1, borderColor: COG.grayLighter,
    padding: 10, marginBottom: 10, gap: 10,
  },
  mapBannerTitle: { fontSize: 13, fontWeight: "700", color: COG.primary },
  mapBannerSub:   { fontSize: 11, color: COG.grayDark, marginTop: 2, lineHeight: 14 },
  mapBannerBtn: {
    backgroundColor: COG.tealLight, borderRadius: 999,
    paddingHorizontal: 12, paddingVertical: 7,
  },
  mapBannerBtnText: { color: COG.primary, fontSize: 11, fontWeight: "800", letterSpacing: 0.3 },
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

  // Lab card meta row (stars, open/closed, directions)
  labMetaRow: { flexDirection: "row", alignItems: "center", flexWrap: "wrap", marginTop: 3, gap: 8 },
  labRatingNum: { color: COG.grayDark, fontWeight: "400" },
  openTag:   { fontSize: 10, fontWeight: "700", color: COG.green, letterSpacing: 0.3 },
  closedTag: { fontSize: 10, fontWeight: "700", color: COG.red,   letterSpacing: 0.3 },
  directionsLink: { fontSize: 11, fontWeight: "700", color: COG.blueDark, textDecorationLine: "underline" },

  // Profile grid
  grid: { flexDirection: "row", flexWrap: "wrap" },
  gridCell: {
    width: "50%",
    paddingVertical: 10, paddingRight: 6,
    borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  gridLabel: { fontSize: 10, color: COG.grayDark, textTransform: "uppercase", letterSpacing: 0.5, fontWeight: "700" },
  gridValue: { fontSize: 13, color: COG.primary, fontWeight: "600", marginTop: 3 },
  gridDrill: { fontSize: 10, color: COG.blueDark, marginTop: 2 },

  // Gap card
  gapCard: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 12, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  gapName:   { fontSize: 14, fontWeight: "700", color: COG.primary },
  gapMeasure:{ fontSize: 10, color: COG.grayDark, marginTop: 2, letterSpacing: 0.5 },
  gapDesc:   { fontSize: 12, color: COG.grayDark, marginTop: 4, lineHeight: 16 },
  gapBtn: {
    backgroundColor: COG.tealLight,
    paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999,
    marginLeft: 8,
  },
  gapBtnText: { color: COG.primary, fontSize: 12, fontWeight: "800" },

  emptyText: { fontSize: 13, color: COG.grayDark, paddingVertical: 6 },

  // Appointment card
  apptCard: {
    flexDirection: "row", alignItems: "center",
    paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: COG.grayLighter,
  },
  apptName: { fontSize: 13, fontWeight: "700", color: COG.primary },
  apptMeta: { fontSize: 11, color: COG.grayDark, marginTop: 2 },
  apptLoc:  { fontSize: 10, color: COG.blueDark, marginTop: 2 },
  apptStatus: {
    backgroundColor: COG.blueDark, paddingHorizontal: 8, paddingVertical: 3,
    borderRadius: 999,
  },
  apptStatusText: { color: COG.white, fontSize: 9, fontWeight: "800", letterSpacing: 0.3 },
});
