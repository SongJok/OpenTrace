/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Söhne', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
      },
      colors: {
        // ChatGPT exact palette
        surface: {
          DEFAULT: '#212121',
          hover: '#2f2f2f',
          active: '#3d3d3d',
          light: '#424242',
        },
        sidebar: '#171717',
        border: '#3d3d3d',
        accent: '#10a37f',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0', transform: 'translateY(8px)' }, to: { opacity: '1', transform: 'translateY(0)' } },
        'slide-in': { from: { transform: 'translateX(-100%)' }, to: { transform: 'translateX(0)' } },
        blink: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0' } },
        'typing-dot': { '0%,80%,100%': { transform: 'scale(0.6)', opacity: '0.4' }, '40%': { transform: 'scale(1)', opacity: '1' } },
      },
      animation: {
        'fade-in': 'fade-in 0.2s ease-out',
        'slide-in': 'slide-in 0.25s ease-out',
        blink: 'blink 1s step-end infinite',
        'dot-1': 'typing-dot 1.2s 0s infinite',
        'dot-2': 'typing-dot 1.2s 0.2s infinite',
        'dot-3': 'typing-dot 1.2s 0.4s infinite',
      },
    },
  },
  plugins: [],
}
