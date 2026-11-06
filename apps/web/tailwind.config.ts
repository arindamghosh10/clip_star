import type { Config } from "tailwindcss";

const c = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

export default {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: c("paper"),
        surface: c("surface"),
        ink: c("ink"),
        muted: c("muted"),
        line: c("line"),
        accent: { DEFAULT: c("accent"), soft: c("accent-soft") },
        rec: c("rec"),
        free: { DEFAULT: c("free"), soft: c("free-soft") },
        paid: { DEFAULT: c("paid"), soft: c("paid-soft") },
        gate: { DEFAULT: c("gate"), soft: c("gate-soft") },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SF Mono", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
} satisfies Config;
