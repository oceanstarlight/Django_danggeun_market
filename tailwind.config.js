/** 폴리마켓 Tailwind 설정 — 디자인 토큰은 design_brief 기준 */
const defaultTheme = require("tailwindcss/defaultTheme");

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./templates/**/*.html",
    "./apps/**/*.py",
    "./apps/**/templates/**/*.html",
    "./static/js/**/*.js",
  ],
  // 템플릿/JS에서 문자열 조합으로 만들어지는 클래스 + 보조 컴포넌트는 항상 포함
  safelist: [
    "toast-success", "toast-info", "toast-warning", "toast-danger",
    "badge-selling", "badge-reserved", "badge-sold", "badge-neutral", "badge-ai",
    "form-stack", "modal-footer", "text-content", "thumb", "scrollbar-none", "pb-safe",
    "bubble", "bubble-me", "bubble-other", "bubble-meta", "preview-grid", "preview-item", "preview-item-badge",
    "animate-pop", "card-interactive", "alert-accent", "spinner",
  ],
  // 다크모드는 토큰만 준비 (class 전략, 현재 미사용)
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 딥 틸 브랜드
        brand: {
          50: "#F0FDFA",
          100: "#CCFBF1",
          200: "#99F6E4",
          300: "#5EEAD4",
          400: "#2DD4BF",
          500: "#14B8A6",
          600: "#0D9488",
          700: "#0F766E",
          800: "#115E59",
          900: "#134E4A",
          DEFAULT: "#0F766E",
        },
        // 따뜻한 스톤 뉴트럴
        neutral: {
          0: "#FFFFFF",
          50: "#FAFAF9",
          100: "#F5F5F4",
          200: "#E7E5E4",
          300: "#D6D3D1",
          400: "#A8A29E",
          500: "#78716C",
          600: "#57534E",
          700: "#44403C",
          800: "#292524",
          900: "#1C1917",
        },
        success: { DEFAULT: "#15803D", soft: "#F0FDF4" },
        warning: { DEFAULT: "#B45309", soft: "#FFFBEB" },
        danger: { DEFAULT: "#B91C1C", soft: "#FEF2F2" },
        info: { DEFAULT: "#1D4ED8", soft: "#EFF6FF" },
      },
      fontFamily: {
        sans: [
          "Pretendard Variable",
          "Pretendard",
          "-apple-system",
          "BlinkMacSystemFont",
          "system-ui",
          "Apple SD Gothic Neo",
          "Noto Sans KR",
          "Malgun Gothic",
          ...defaultTheme.fontFamily.sans,
        ],
      },
      fontSize: {
        caption: ["13px", { lineHeight: "18px" }],
        body: ["15px", { lineHeight: "24px" }],
        "body-lg": ["16px", { lineHeight: "28px" }],
        h3: ["17px", { lineHeight: "24px", fontWeight: "600" }],
        h2: ["20px", { lineHeight: "28px", letterSpacing: "-0.01em", fontWeight: "700" }],
        h1: ["24px", { lineHeight: "32px", letterSpacing: "-0.015em", fontWeight: "700" }],
        display: ["32px", { lineHeight: "40px", letterSpacing: "-0.02em", fontWeight: "700" }],
      },
      borderRadius: {
        sm: "6px",
        md: "10px",
        lg: "16px",
      },
      boxShadow: {
        sm: "0 1px 2px 0 rgb(28 25 23 / 0.05)",
        md: "0 4px 12px -2px rgb(28 25 23 / 0.08), 0 2px 4px -2px rgb(28 25 23 / 0.04)",
        lg: "0 16px 32px -8px rgb(28 25 23 / 0.14), 0 4px 8px -4px rgb(28 25 23 / 0.06)",
      },
      spacing: {
        "safe-b": "env(safe-area-inset-bottom)",
      },
      keyframes: {
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        pop: {
          "0%": { transform: "scale(1)" },
          "40%": { transform: "scale(1.25)" },
          "100%": { transform: "scale(1)" },
        },
        "fade-up": {
          "0%": { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
      },
      animation: {
        shimmer: "shimmer 1.5s linear infinite",
        pop: "pop 250ms ease-out",
        "fade-up": "fade-up 200ms ease-out both",
        "fade-in": "fade-in 150ms ease-out both",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
    },
  },
  plugins: [require("@tailwindcss/forms")({ strategy: "class" })],
};
