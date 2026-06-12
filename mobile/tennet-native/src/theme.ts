export const colors = {
  ink: "#13231F",
  inkMuted: "#5F6F69",
  canvas: "#F6F3ED",
  surface: "#FFFFFF",
  surfaceWarm: "#FDF9F1",
  line: "#E2DDD2",
  primary: "#0D5B46",
  primaryDark: "#0A3C31",
  primarySoft: "#DDEDE7",
  gold: "#CBA35A",
  blue: "#2D6CDF",
  orange: "#C46C2D",
  red: "#B64236",
  green: "#1F7A50",
  gray: "#8A918D",
  black: "#000000",
  white: "#FFFFFF",
};

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
};

export const radius = {
  sm: 8,
  md: 14,
  lg: 20,
  pill: 999,
};

export const shadow = {
  shadowColor: "#0A241C",
  shadowOffset: { width: 0, height: 10 },
  shadowOpacity: 0.08,
  shadowRadius: 18,
  elevation: 4,
};

export const statusColors: Record<string, string> = {
  ready_to_send: colors.green,
  payment_confirmed: colors.green,
  accepted: colors.green,
  completed: colors.green,
  uploaded: colors.green,
  pending: colors.blue,
  sent: colors.blue,
  needs_evidence: colors.orange,
  missing_evidence: colors.orange,
  manual_review: colors.orange,
  refused: colors.red,
  urgent: colors.red,
  ignored: colors.gray,
  skipped: colors.gray,
};
