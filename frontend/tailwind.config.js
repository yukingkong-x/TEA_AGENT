/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#E7EEE9',
        panel: '#FFFFFF',
        panel2: '#E5F6EA',
        tea: '#1F7A45',
        leaf: '#3E9A62',
        warn: '#9A5B12',
        danger: '#B42318',
        mute: '#7D8A80',
        paper: '#17211B',
        dim: '#66756C',
        line: '#E3EBE6',
      },
      fontFamily: {
        sans: ['"Noto Sans SC"', 'sans-serif'],
        mono: ['"DIN Alternate"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        card: '22px',
        btn: '999px',
      },
    },
  },
  plugins: [],
}
