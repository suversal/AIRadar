export type ThemePreference = "dark" | "system" | "light";
export type ColorPalette = "original" | "radar" | "instrument" | "indigo";

export const THEME_STORAGE_KEY = "ai-radar-theme";
export const PALETTE_STORAGE_KEY = "ai-radar-color-palette";
export const DEFAULT_COLOR_PALETTE: ColorPalette = "instrument";

export const PALETTE_CANVAS_COLORS: Record<
  Exclude<ColorPalette, "original">,
  { dark: string; light: string }
> = {
  radar: { dark: "#171923", light: "#eef0f6" },
  instrument: { dark: "#181b1a", light: "#efeee8" },
  indigo: { dark: "#19191d", light: "#efedf6" },
};

export const COLOR_PALETTES: ReadonlyArray<{
  value: ColorPalette;
  label: string;
  swatch: string;
}> = [
  { value: "instrument", label: "仪器青", swatch: "#0e746d" },
  { value: "original", label: "经典橙", swatch: "#b94f2f" },
  { value: "radar", label: "雷达蓝", swatch: "#3157c8" },
  { value: "indigo", label: "墨靛紫", swatch: "#514596" },
];

export function isColorPalette(value: string | null): value is ColorPalette {
  return COLOR_PALETTES.some((palette) => palette.value === value);
}
