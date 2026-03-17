/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        // ── Exact Claude.ai colour tokens ──────────────────────────────────
        claude: {
          // Page backgrounds
          bg:          '#F4F0E6',   // warm parchment — main page background
          sidebar:     '#F4F0E6',   // sidebar matches page (no heavy contrast)
          
          // Surfaces
          surface:     '#FFFFFF',   // cards, input, artifact panel
          'surface-2': '#F9F7F3',   // slightly elevated surface (header bars)

          // Borders
          border:      '#E8E3D9',   // standard divider
          'border-2':  '#D9D3C8',   // stronger divider / focus ring base

          // Brand
          orange:      '#C96A42',   // Claude's terracotta send-button orange
          'orange-dim':'#E8D5C8',   // very light orange tint for hover states

          // Text hierarchy
          dark:        '#1A1410',   // primary text — near-black warm
          body:        '#3D3530',   // body / secondary text
          muted:       '#8A7F72',   // muted / meta text
          placeholder: '#B5ADA4',   // input placeholder

          // Interactive states
          hover:       '#EEEAD E',  // subtle hover (used inline, see below)
          active:      '#E8E3D9',   // active / selected row
        },
      },
      // Use exact pixel values to match Claude's spacing feel
      spacing: {
        '4.5': '1.125rem',
        '13':  '3.25rem',
        '15':  '3.75rem',
        '18':  '4.5rem',
      },
      borderRadius: {
        'xl':  '0.75rem',
        '2xl': '1rem',
        '3xl': '1.5rem',
      },
      fontSize: {
        '2xs': ['0.625rem', { lineHeight: '0.875rem' }],
        xs:    ['0.75rem',  { lineHeight: '1.1rem'   }],
        sm:    ['0.8125rem',{ lineHeight: '1.375rem' }],
        base:  ['0.875rem', { lineHeight: '1.5rem'   }],
        lg:    ['1rem',     { lineHeight: '1.5rem'   }],
        xl:    ['1.125rem', { lineHeight: '1.625rem' }],
        '2xl': ['1.375rem', { lineHeight: '1.875rem' }],
      },
      boxShadow: {
        'xs':    '0 1px 2px rgba(0,0,0,0.05)',
        'sm':    '0 1px 3px rgba(0,0,0,0.07), 0 1px 2px rgba(0,0,0,0.04)',
        'input': '0 0 0 3px rgba(201,106,66,0.12)',
      },
      // Claude uses SF Pro / system font stack with geometric proportions
      fontFamily: {
        sans: [
          '-apple-system', 'BlinkMacSystemFont', '"Segoe UI"',
          'system-ui', 'sans-serif',
        ],
        mono: [
          '"Fira Code"', '"Cascadia Code"', 'Menlo',
          'Monaco', 'Consolas', 'monospace',
        ],
      },
    },
  },
  plugins: [],
}