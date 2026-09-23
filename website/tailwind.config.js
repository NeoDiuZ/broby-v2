/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        // Primary colors - New Design System
        'primary': {
          DEFAULT: '#17A2B8',  // Brand Teal (was #2EC4B6)
          dark: '#138496',      // Hover state (was #25A69A)
          light: '#4DD0C3',
        },
        // Text colors
        'text': {
          primary: '#1A1A1A',     // Headlines (was #121A2B)
          secondary: '#5A5A5A',   // Body text (was #6B7280)
        },
        // Background colors
        'background': {
          DEFAULT: '#FFFFFF',
          secondary: '#F8F9FA',  // Alternate sections (was #F5F6FA)
        },
        // Border colors
        'border': {
          DEFAULT: '#E0E0E0',
        },
        // Button colors
        'button': {
          primary: '#17A2B8',      // (was #2EC4B6)
          secondary: '#F5F6FA',
          danger: '#E57373',
        },
        // Additional colors
        'brand-teal': '#17A2B8',
        'video-placeholder': '#E5E5E5',

        // ── Broby Design System tokens (BROBY_DESIGN_SYSTEM.md §1) ──
        // Used on legal/policy pages so they match the SaaS app brand,
        // not the marketing-site aqua. Additive only — existing tokens above untouched.
        'ds-primary': {
          DEFAULT: '#0D9488',     // Design system primary (teal-600)
          hover: '#0F766E',        // Design system primary-hover (teal-700)
        },
        'ds-bg': '#F5F3EF',         // Warm cream page background
        'ds-surface': '#FFFFFF',    // Cards / inputs
        'ds-text': {
          dark: '#1C1917',          // Headings, primary content
          muted: '#78716C',         // Secondary info
          light: '#A8A29E',         // Tertiary, helper text
        },
        'ds-border': {
          DEFAULT: '#E7E5E4',
        },
        'ds-staging': '#F59E0B',    // Warning amber for staging banner
      },
      fontFamily: {
        sans: ['Inter', 'Roboto', 'system-ui', 'sans-serif'],
        // Design system body font (BROBY_DESIGN_SYSTEM.md §2) — opt-in via class.
        'plus-jakarta': ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
      },
      fontSize: {
        'body': ['16px', '1.5'],
      },
      boxShadow: {
        // Design system shadow tokens (BROBY_DESIGN_SYSTEM.md §9)
        'ds-card': '0 1px 2px rgba(0,0,0,0.04)',
        'ds-focus': '0 0 0 2px rgba(13,148,136,0.1)',
      },
      borderRadius: {
        // Design system radius (BROBY_DESIGN_SYSTEM.md §10)
        'ds-xl': '16px',  // Cards
        'ds-lg': '10px',  // Inputs
      },
    },
  },
  plugins: [],
}