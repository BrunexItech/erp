import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["'Inter Variable'", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        navy: {
          950: "#0a1322",
          900: "#0f1b2d",
          800: "#16243d",
          700: "#1c2f4d",
          600: "#2a4166",
        },
        brand: {
          DEFAULT: "#1a7a8c",
          light: "#22909f",
          50: "#effafb",
          100: "#d5f1f4",
          200: "#aee2e9",
          500: "#1a7a8c",
          600: "#156676",
          700: "#125361",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 27, 45, 0.04), 0 1px 3px rgba(15, 27, 45, 0.06)",
        lift: "0 10px 30px -12px rgba(15, 27, 45, 0.25)",
      },
    },
  },
  plugins: [],
};

export default config;
