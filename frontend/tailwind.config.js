/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        display:   ["Oswald", "system-ui", "sans-serif"],
        body:      ["Barlow", "system-ui", "sans-serif"],
        serif:     ["'Playfair Display'", "Georgia", "serif"],
        editorial: ["Lora", "Georgia", "serif"],
      },
      colors: {
        pi: {
          bg:        "#070c19",
          surface:   "#0d1527",
          card:      "#111f38",
          "card-2":  "#0f1b32",
          border:    "rgba(79,90,132,0.22)",
          "border-active": "rgba(99,102,241,0.45)",
          indigo:    "#6366f1",
          violet:    "#8b5cf6",
          "indigo-light": "#818cf8",
          emerald:   "#10b981",
          rose:      "#f43f5e",
          amber:     "#f59e0b",
          sky:       "#38bdf8",
          muted:     "#4a5878",
          secondary: "#8892b0",
          primary:   "#e8eeff",
        },
      },
      boxShadow: {
        "glow-indigo": "0 0 24px rgba(99,102,241,0.18), 0 0 8px rgba(99,102,241,0.12)",
        "glow-green":  "0 0 20px rgba(16,185,129,0.15), 0 0 6px rgba(16,185,129,0.1)",
        "glow-rose":   "0 0 20px rgba(244,63,94,0.15)",
        "card-hover":  "0 8px 32px rgba(0,0,0,0.4), 0 2px 8px rgba(99,102,241,0.08)",
        "card":        "0 2px 12px rgba(0,0,0,0.3)",
      },
      backgroundImage: {
        "gradient-indigo": "linear-gradient(135deg, #6366f1, #8b5cf6)",
        "gradient-play":   "linear-gradient(135deg, #10b981, #059669)",
        "gradient-amber":  "linear-gradient(135deg, #f59e0b, #d97706)",
      },
      keyframes: {
        "float": {
          "0%, 100%": { transform: "translateY(0px)" },
          "50%":       { transform: "translateY(-4px)" },
        },
        "glow-pulse": {
          "0%, 100%": { boxShadow: "0 0 12px rgba(99,102,241,0.2)" },
          "50%":       { boxShadow: "0 0 24px rgba(99,102,241,0.45), 0 0 8px rgba(139,92,246,0.3)" },
        },
        "fade-up": {
          from: { opacity: "0", transform: "translateY(10px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "shimmer": {
          "0%":   { backgroundPosition: "-200% center" },
          "100%": { backgroundPosition: "200% center" },
        },
      },
      animation: {
        "float":      "float 3s ease-in-out infinite",
        "glow-pulse": "glow-pulse 2.5s ease-in-out infinite",
        "fade-up":    "fade-up 0.35s ease-out both",
        "shimmer":    "shimmer 2s linear infinite",
      },
    },
  },
  plugins: [],
};
