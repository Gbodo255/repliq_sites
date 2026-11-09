/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Tessel brand tokens
        bg: "var(--bg)",
        ink: "var(--ink)",
        faint: "var(--faint)",
        accent: { DEFAULT: "var(--accent)", 600: "var(--accent-600)", ink: "var(--accent-ink)" },
        panel: { DEFAULT: "var(--panel)", 2: "var(--panel-2)" },
        border: { DEFAULT: "var(--border)", strong: "var(--border-strong)" },
        // Shadcn-compatible aliases (mapped to Tessel values) so the in-app
        // screens keep rendering; `muted` is gray so text-muted == text-muted-foreground.
        muted: { DEFAULT: "var(--muted)", foreground: "var(--muted)" },
        background: "var(--bg)",
        foreground: "var(--ink)",
        card: { DEFAULT: "var(--bg)", foreground: "var(--ink)" },
        primary: { DEFAULT: "var(--accent)", foreground: "var(--accent-ink)" },
        secondary: { DEFAULT: "var(--panel)", foreground: "var(--ink)" },
        destructive: { DEFAULT: "#d23b3b", foreground: "#ffffff" },
        input: "var(--border-strong)",
        ring: "var(--accent)",
      },
      borderRadius: {
        xl: "var(--radius)",
        "2xl": "calc(var(--radius) + 6px)",
        "3xl": "calc(var(--radius) + 14px)",
      },
      fontFamily: {
        display: ['"Space Grotesk"', '"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ['"Inter"', "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      maxWidth: { content: "1180px" },
      keyframes: {
        "fade-in": { from: { opacity: "0", transform: "translateY(6px)" }, to: { opacity: "1", transform: "none" } },
      },
      animation: { "fade-in": "fade-in 0.4s ease-out both" },
    },
  },
  plugins: [],
};
