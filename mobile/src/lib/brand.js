// Cognizant Web & Digital Applications brand tokens (Jan 2024 guide)
// Use these ONLY — never hardcode hex codes in screen files.

export const COG = {
  // Base
  primary:        "#000048",   // Midnight blue — headings, body text, primary surfaces
  white:          "#FFFFFF",

  // Accent 1 (plum) — secondary accents
  plumDark:       "#2E308E",
  plumMedium:     "#7373D8",
  plumLight:      "#85A0F9",

  // Accent 2 (blue) — links, form elements, tabs, hollow buttons
  blueDark:       "#2F78C4",
  blueMedium:     "#6AA2DC",
  blueLight:      "#92BBE6",

  // Accent 3 (teal) — filled button backgrounds, video blocks, CTAs on dark
  tealDark:       "#05819B",
  tealMedium:     "#06C7CC",
  tealLight:      "#26EFE9",   // default filled button bg

  // Neutral grays
  grayLight:      "#D0D0CE",
  grayLighter:    "#E8E8E6",
  grayLightest:   "#F7F7F5",
  grayDark:       "#53565A",
  grayMedium:     "#97999B",

  // Highlight — messages / notifications only
  red:            "#B81F2D",
  yellow:         "#E9C71D",
  green:          "#2DB81F",   // success confirmations ONLY
};

// Typographic scale — perfect-fourth ratio (1.333) with 20 base
export const TYPE = {
  h3:     { fontSize: 36, lineHeight: 42, fontWeight: "600", color: COG.primary },
  h4:     { fontSize: 28, lineHeight: 34, fontWeight: "300", color: COG.blueMedium },
  h5:     { fontSize: 22, lineHeight: 27, fontWeight: "300", color: COG.blueMedium },
  h6:     { fontSize: 18, lineHeight: 22, fontWeight: "300", color: COG.blueMedium },
  body:   { fontSize: 16, lineHeight: 22, color: COG.primary },
  small:  { fontSize: 13, lineHeight: 17, color: COG.primary },
  tiny:   { fontSize: 11, lineHeight: 14, color: COG.grayDark },
};

// Radius scale (0.5em base @ 16px = 8)
export const R = {
  input:  10,      // 0.5em-ish
  check:  4,       // checkboxes/radios = 0.2em
  modal:  10,
  card:   0,       // cards have NO rounding (per guide)
  pill:   999,     // buttons are pills
};

// Spacing
export const S = {
  xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32,
};

// Shared stylesheet fragments
export const FORM = {
  input: {
    backgroundColor: COG.grayLightest,
    borderWidth: 1,
    borderColor: COG.grayLighter,
    borderRadius: R.input,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 16,
    color: COG.primary,
  },
  label: {
    fontSize: 13,
    fontWeight: "600",
    color: COG.primary,
    marginBottom: 6,
  },
};

// Filled pill button (per guide: teal bg, midnight blue text)
export const BTN_FILLED = {
  container: {
    backgroundColor: COG.tealLight,
    paddingVertical: 14,
    paddingHorizontal: 24,
    borderRadius: R.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  text: {
    color: COG.primary,
    fontSize: 15,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
};

// Hollow pill button on light bg (dark blue border + text)
export const BTN_HOLLOW = {
  container: {
    borderWidth: 2,
    borderColor: COG.blueDark,
    backgroundColor: "transparent",
    paddingVertical: 12,
    paddingHorizontal: 22,
    borderRadius: R.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  text: {
    color: COG.blueDark,
    fontSize: 15,
    fontWeight: "700",
    letterSpacing: 0.2,
  },
};

// Header bar (midnight blue)
export const HEADER = {
  backgroundColor: COG.primary,
  tintColor: COG.white,
};

// Card (square corners, subtle border, white bg)
export const CARD = {
  backgroundColor: COG.white,
  borderWidth: 1,
  borderColor: COG.grayLighter,
  padding: S.lg,
  marginBottom: S.md,
};
