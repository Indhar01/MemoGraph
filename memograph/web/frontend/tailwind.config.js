/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#f0f9ff',
          100: '#e0f2fe',
          200: '#bae6fd',
          300: '#7dd3fc',
          400: '#38bdf8',
          500: '#0ea5e9',
          600: '#0284c7',
          700: '#0369a1',
          800: '#075985',
          900: '#0c4a6e',
        },
        accent: {
          50: '#faf5ff',
          100: '#f3e8ff',
          200: '#e9d5ff',
          300: '#d8b4fe',
          400: '#c084fc',
          500: '#a855f7',
          600: '#9333ea',
          700: '#7e22ce',
          800: '#6b21a8',
          900: '#581c87',
        },
        // Semantic, theme-aware tokens (driven by CSS vars in index.css)
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-solid': 'rgb(var(--surface-solid) / <alpha-value>)',
        'surface-elevated': 'rgb(var(--surface-elevated) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        'border-strong': 'rgb(var(--border-strong) / <alpha-value>)',
        fg: 'rgb(var(--fg) / <alpha-value>)',
        'muted-fg': 'rgb(var(--muted-fg) / <alpha-value>)',
        // Memory-type tokens (kept stable across themes for graph-canvas use)
        mem: {
          episodic: '#3b82f6',
          'episodic-2': '#06b6d4',
          semantic: '#10b981',
          'semantic-2': '#84cc16',
          procedural: '#f59e0b',
          'procedural-2': '#ef4444',
          fact: '#8b5cf6',
          'fact-2': '#ec4899',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        display: ['"Space Grotesk"', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        sm: '8px',
        md: '12px',
        lg: '16px',
        xl: '24px',
      },
      boxShadow: {
        'glass-sm': '0 4px 16px 0 rgba(17, 24, 39, 0.06), 0 0 0 1px rgba(255, 255, 255, 0.08) inset',
        'glass-md': '0 8px 32px 0 rgba(17, 24, 39, 0.12), 0 0 0 1px rgba(255, 255, 255, 0.10) inset',
        'glass-lg': '0 16px 48px 0 rgba(17, 24, 39, 0.18), 0 0 0 1px rgba(255, 255, 255, 0.12) inset',
        'glow-primary': '0 0 24px 0 rgba(14, 165, 233, 0.45)',
        'glow-accent': '0 0 24px 0 rgba(168, 85, 247, 0.45)',
        'glow-soft': '0 0 32px 0 rgba(14, 165, 233, 0.18)',
      },
      backgroundImage: {
        'gradient-primary': 'linear-gradient(135deg, #0ea5e9 0%, #06b6d4 100%)',
        'gradient-accent': 'linear-gradient(135deg, #a855f7 0%, #ec4899 100%)',
        'gradient-brand': 'linear-gradient(135deg, #0ea5e9 0%, #a855f7 60%, #ec4899 100%)',
        'gradient-mem-episodic': 'linear-gradient(135deg, #3b82f6 0%, #06b6d4 100%)',
        'gradient-mem-semantic': 'linear-gradient(135deg, #10b981 0%, #84cc16 100%)',
        'gradient-mem-procedural': 'linear-gradient(135deg, #f59e0b 0%, #ef4444 100%)',
        'gradient-mem-fact': 'linear-gradient(135deg, #8b5cf6 0%, #ec4899 100%)',
        'mesh-light':
          'radial-gradient(at 20% 10%, rgba(14, 165, 233, 0.22) 0px, transparent 50%), radial-gradient(at 80% 30%, rgba(168, 85, 247, 0.20) 0px, transparent 50%), radial-gradient(at 50% 90%, rgba(236, 72, 153, 0.16) 0px, transparent 50%)',
        'mesh-dark':
          'radial-gradient(at 20% 10%, rgba(14, 165, 233, 0.28) 0px, transparent 50%), radial-gradient(at 80% 30%, rgba(168, 85, 247, 0.26) 0px, transparent 50%), radial-gradient(at 50% 90%, rgba(236, 72, 153, 0.20) 0px, transparent 50%)',
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'drift': 'drift 24s ease-in-out infinite',
        'fade-up': 'fade-up 220ms cubic-bezier(0.34, 1.56, 0.64, 1)',
        'glow-pulse': 'glow-pulse 2.4s ease-in-out infinite',
        'shimmer': 'shimmer 1.6s linear infinite',
      },
      keyframes: {
        drift: {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '33%': { transform: 'translate3d(2%, -1%, 0) scale(1.04)' },
          '66%': { transform: 'translate3d(-2%, 1%, 0) scale(0.98)' },
        },
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(8px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        'glow-pulse': {
          '0%, 100%': { opacity: '0.45' },
          '50%': { opacity: '0.85' },
        },
        shimmer: {
          '0%': { backgroundPosition: '-200% 0' },
          '100%': { backgroundPosition: '200% 0' },
        },
      },
      transitionTimingFunction: {
        spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
  plugins: [],
};
