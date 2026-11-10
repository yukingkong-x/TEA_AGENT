/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#F4F7F2',
        panel: '#FFFFFF',
        panel2: '#E7F3EA',
        tea: '#2F7A4A',
        leaf: '#3E9A62',
        run: '#2F7A4A',
        warn: '#9A5B12',
        danger: '#B42318',
        mute: '#7D8A80',
        paper: '#1A1A1A',
        dim: '#5C675F',
        faint: '#8A948C',
        line: '#D5E6DA',
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', 'sans-serif'],
        serif: ['"Noto Serif SC"', 'serif'],
        mono: ['"DIN Alternate"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        card: '12px',
        btn: '8px',
      },
      boxShadow: {
        lift: '0 12px 32px rgba(11, 18, 32, 0.28)',
      },
    },
  },
  plugins: [],
}
