/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        surface: { 0: "#0f0f0e", 1: "#1a1a19", 2: "#242422", 3: "#2f2f2c" },
        ink: { 1: "#f0efec", 2: "#c3c2b7", 3: "#8d8c84" },
        series: { 1: "#3987e5", 2: "#d95926", 3: "#199e70" },
        good: "#0ca30c",
        warn: "#fab219",
        bad: "#e66767",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"], mono: ["JetBrains Mono", "ui-monospace", "monospace"] },
    },
  },
  plugins: [],
};
