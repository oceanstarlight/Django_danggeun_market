/**
 * 폴리마켓 Tailwind 설정: Hallmark Arcade 테마
 * 모든 색·폰트·그림자는 static/src/tokens.css 의 토큰(var)을 가리킨다.
 * Tailwind 기본 팔레트(neutral, red, violet ...)는 일부러 쓰지 않는다(colors 를 통째로 교체).
 * 토큰 색은 var() 라서 `bg-ink/50` 같은 투명도 수식어는 동작하지 않는다. 필요하면 CSS 에서 color-mix() 로.
 */

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
  darkMode: "class",
  theme: {
    colors: {
      transparent: "transparent",
      current: "currentColor",
      inherit: "inherit",
      paper: { DEFAULT: "var(--color-paper)", 2: "var(--color-paper-2)", 3: "var(--color-paper-3)" },
      ink: { DEFAULT: "var(--color-ink)", 2: "var(--color-ink-2)" },
      muted: "var(--color-muted)",
      rule: "var(--color-rule)",
      accent: { DEFAULT: "var(--color-accent)", 2: "var(--color-accent-2)", ink: "var(--color-accent-ink)" },
      focus: "var(--color-focus)",
      error: "var(--color-error)",
      success: "var(--color-success)",
      shade: "var(--color-shade)",
    },
    fontFamily: {
      display: "var(--font-display)",
      sans: "var(--font-body)",
      body: "var(--font-body)",
      figure: "var(--font-outlier)",
    },
    // 앱 화면용 고정 스케일(1.2 비율 근처). 본문은 16px 미만으로 내려가지 않는다.
    fontSize: {
      xs: ["13px", { lineHeight: "18px" }],
      sm: ["14px", { lineHeight: "20px" }],
      base: ["16px", { lineHeight: "26px" }],
      lg: ["18px", { lineHeight: "26px" }],
      xl: ["20px", { lineHeight: "28px" }],
      "2xl": ["24px", { lineHeight: "30px" }],
      "3xl": ["30px", { lineHeight: "34px" }],
      "4xl": ["36px", { lineHeight: "40px" }],
      "5xl": ["48px", { lineHeight: "50px" }],
      caption: ["13px", { lineHeight: "18px" }],
      body: ["16px", { lineHeight: "26px" }],
      "body-lg": ["17px", { lineHeight: "28px" }],
      h3: ["18px", { lineHeight: "24px", fontWeight: "900" }],
      h2: ["22px", { lineHeight: "26px", letterSpacing: "-0.02em", fontWeight: "900" }],
      h1: ["28px", { lineHeight: "32px" }],
      display: ["40px", { lineHeight: "44px" }],
    },
    borderRadius: {
      none: "0",
      sm: "2px",
      DEFAULT: "var(--radius-card)",
      md: "var(--radius-card)",
      lg: "var(--radius-card)",
      card: "var(--radius-card)",
      full: "9999px",
    },
    boxShadow: {
      none: "none",
      sm: "none",
      DEFAULT: "none",
      // 단단한 오프셋 그림자만 (흐림 0). press 는 누를 수 있는 것, slab 은 떠 있는 패널
      press: "4px 4px 0 var(--color-accent-2)",
      card: "var(--shadow-card)",
      slab: "6px 6px 0 var(--color-shade)",
      md: "6px 6px 0 var(--color-shade)",
      lg: "6px 6px 0 var(--color-shade)",
    },
    extend: {
      borderWidth: { bar: "var(--rule-bar)" },
      spacing: {
        "safe-b": "env(safe-area-inset-bottom)",
      },
      maxWidth: { page: "var(--container)" },
      transitionTimingFunction: {
        out: "var(--ease-out)",
      },
      transitionDuration: { micro: "120ms", short: "220ms" },
    },
  },
  plugins: [require("@tailwindcss/forms")({ strategy: "class" })],
};
