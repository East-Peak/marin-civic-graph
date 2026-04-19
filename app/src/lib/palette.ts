export const palette = {
  background: "#07090d",
  panel: "#0b0d11",
  surface: "#14171d",
  borderPrimary: "#1f232b",
  borderHairline: "#1a1d24",
  bodyText: "#c2c8d2",
  dimText: "#7b8494",
  hairlineText: "#5e6573",
  node: {
    focus: "#ffffff",
    decision: "#a4e8bf",
    money: "#f2c77a",
    person: "#8db8ff",
    legal: "#e27a7a",
    organization: "#b8a8d9",
    projectProgram: "#d9a88d",
    generic: "#e8ecf3",
  },
  edge: {
    governance: "rgba(150, 180, 220, 0.22)",
    money: "rgba(220, 200, 140, 0.55)",
    legalConstrains: "rgba(226, 122, 122, 0.45)",
  },
} as const;

export type Palette = typeof palette;
