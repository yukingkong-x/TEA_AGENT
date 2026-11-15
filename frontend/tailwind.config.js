/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#E7EEE9',
        panel: '#FFFFFF',
        panel2: '#E8F6EE',
        tea: '#1F7A45',
        teaHover: '#2E9E5D',
        teaPress: '#155B32',
        leaf: '#3E9A62',
        warn: '#FF7D00',
        danger: '#F53F3F',
        paper: '#1D2129',
        dim: '#4E5969',
        mute: '#86909C',
        hold: '#C9CDD4',
        line: '#E3EBE6',
      },
      fontFamily: {
        sans: ['"PingFang SC"', '"Noto Sans SC"', 'sans-serif'],
        mono: ['DIN', '"DIN Alternate"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      borderRadius: {
        card: '22px',
        btn: '999px',
      },
    },
  },
  plugins: [],
}
