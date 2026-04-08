import type { Config } from "tailwindcss"

const config: Config = {
  darkMode: ["class"],
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        // Health status colors — used throughout the app
        status: {
          normal:  { DEFAULT: "#22c55e", light: "#dcfce7", text: "#15803d" },
          watch:   { DEFAULT: "#f59e0b", light: "#fef3c7", text: "#92400e" },
          discuss: { DEFAULT: "#f97316", light: "#ffedd5", text: "#9a3412" },
          high:    { DEFAULT: "#ef4444", light: "#fee2e2", text: "#991b1b" },
          low:     { DEFAULT: "#3b82f6", light: "#dbeafe", text: "#1e40af" },
          critical:{ DEFAULT: "#7c3aed", light: "#ede9fe", text: "#4c1d95" },
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 4px)",
      },
      fontFamily: {
        sans: ["var(--font-geist-sans)"],
        mono: ["var(--font-geist-mono)"],
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
}

export default config
