/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Three background tiers instead of two. V2 had a page colour and a
        // panel colour, so a panel inside a panel was invisible - and this UI
        // nests constantly (a chart inside a stage inside a page).
        ink: "#070A12",
        "ink-soft": "#0B0F1A",
        panel: "#0E1320",
        "panel-2": "#141B2B",
        "panel-3": "#1A2334",

        edge: "#1D2536",
        "edge-strong": "#2C3A52",

        accent: "#F0B429",
        "accent-bright": "#FFCF5C",
        "accent-dim": "#8A6A1C",

        // Data colours. Deliberately distinguishable in the three common
        // colour-vision deficiencies as well as by position in every chart
        // that uses them - nothing here is encoded by colour alone.
        positive: "#34D399",
        negative: "#FB7185",
        caution: "#FBBF24",
        info: "#60A5FA",
        violet: "#A78BFA",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      fontSize: {
        // An explicit scale, so "slightly smaller" stops being a judgement call.
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],   // 11px
        xs: ["0.75rem", { lineHeight: "1.125rem" }],    // 12px
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],   // 13px
        base: ["0.9375rem", { lineHeight: "1.5rem" }],  // 15px
        lg: ["1.0625rem", { lineHeight: "1.5rem" }],
        xl: ["1.3125rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.625rem", { lineHeight: "2rem" }],
        "3xl": ["2rem", { lineHeight: "2.25rem" }],
      },
      letterSpacing: {
        label: "0.12em",
      },
      borderRadius: {
        xl: "0.75rem",
        "2xl": "1rem",
      },
      boxShadow: {
        // One elevation scale, used consistently. Random shadow values are the
        // fastest way to make a dark UI look muddy.
        panel: "0 1px 2px rgba(0,0,0,0.6), 0 8px 24px -12px rgba(0,0,0,0.8)",
        raised: "0 2px 6px rgba(0,0,0,0.5), 0 16px 40px -16px rgba(0,0,0,0.9)",
        glow: "0 0 0 1px rgba(240,180,41,0.25), 0 0 24px -4px rgba(240,180,41,0.35)",
      },
      backgroundImage: {
        "panel-sheen":
          "linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0) 40%)",
        "accent-fill": "linear-gradient(180deg, #FFCF5C 0%, #F0B429 100%)",
      },
      keyframes: {
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
      },
      animation: {
        "fade-up": "fade-up 220ms cubic-bezier(0.16, 1, 0.3, 1) both",
      },
    },
  },
  plugins: [],
};
