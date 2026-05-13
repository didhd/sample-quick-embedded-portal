/** @type {import('tailwindcss').Config} */
export default {
    content: ["./index.html", "./src/**/*.{js,jsx}"],
    theme: {
        extend: {
            colors: {
                ink: {
                    50: "#f8fafc",
                    100: "#f1f5f9",
                    200: "#e2e8f0",
                    300: "#cbd5e1",
                    400: "#94a3b8",
                    500: "#64748b",
                    600: "#475569",
                    700: "#334155",
                    800: "#1e293b",
                    900: "#0f172a",
                    950: "#030712",
                },
                brand: {
                    DEFAULT: "#ff9900",
                    50: "#fff8ed",
                    100: "#ffefd4",
                    200: "#ffdca8",
                    300: "#ffc171",
                    400: "#ff9f3a",
                    500: "#ff9900",
                    600: "#e67e00",
                    700: "#b25f00",
                    800: "#8a4a00",
                    900: "#6e3d00",
                },
                squid: "#232f3e",
                squidInk: "#161e2d",
            },
            fontFamily: {
                sans: [
                    "-apple-system",
                    "BlinkMacSystemFont",
                    "Segoe UI",
                    "Inter",
                    "system-ui",
                    "sans-serif",
                ],
            },
            boxShadow: {
                glow: "0 0 0 1px rgba(255,153,0,0.25), 0 8px 32px -8px rgba(255,153,0,0.25)",
                panel: "0 1px 2px rgba(15,23,42,0.04), 0 8px 24px -12px rgba(15,23,42,0.12)",
            },
            animation: {
                "slide-in": "slideIn 220ms cubic-bezier(0.16, 1, 0.3, 1)",
                "slide-out": "slideOut 180ms cubic-bezier(0.4, 0, 1, 1)",
                "fade-in": "fadeIn 180ms ease-out",
            },
            keyframes: {
                slideIn: {
                    from: { transform: "translateX(100%)" },
                    to: { transform: "translateX(0)" },
                },
                slideOut: {
                    from: { transform: "translateX(0)" },
                    to: { transform: "translateX(100%)" },
                },
                fadeIn: { from: { opacity: 0 }, to: { opacity: 1 } },
            },
        },
    },
    plugins: [],
};
