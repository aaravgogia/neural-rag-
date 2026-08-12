module.exports = {
  content: ["./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: '#0A0C10', 2: '#10131A' },
        paper: '#ECEAE3',
        mute: '#888E99',
        trace: '#4FD8C4',
        pulse: '#FF7A45',
        danger: '#FF5C5C',
      },
      fontFamily: {
        display: ['Space Grotesk', 'sans-serif'],
        sans: ['IBM Plex Sans', 'sans-serif'],
        mono: ['IBM Plex Mono', 'monospace'],
      },
      borderColor: {
        line: 'rgba(236, 234, 227, 0.10)',
      },
    },
  },
  plugins: [],
};
