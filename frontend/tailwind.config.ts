import type { Config } from "tailwindcss";

// Dark mode follows the OS (prefers-color-scheme).
const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: { extend: {} },
  plugins: [],
};

export default config;
