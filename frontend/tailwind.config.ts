import type { Config } from 'tailwindcss';

const config: Config = {
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Pretendard', '-apple-system', 'BlinkMacSystemFont', 'system-ui', 'sans-serif'],
      },
      colors: {
        paper: '#F7F5F2',
        surface: '#FFFFFF',
        ink: '#1F1E1D',
        muted: '#6B6862',
        border: '#E9E4DD',
        primary: {
          DEFAULT: '#D97757',
          hover: '#C2603F',
          soft: '#F6E9E2',
        },
        secondary: {
          DEFAULT: '#3B6CFF',
          soft: '#EAF0FF',
        },
        success: {
          DEFAULT: '#2F9E68',
          soft: '#E7F4EC',
        },
        warning: {
          DEFAULT: '#C98A14',
          soft: '#FBF1DC',
        },
        danger: {
          DEFAULT: '#D14343',
          soft: '#FBE9E9',
        },
      },
      borderRadius: {
        '2xl': '16px',
        xl: '12px',
      },
      boxShadow: {
        card: '0 1px 3px 0 rgba(31,30,29,0.06), 0 1px 2px -1px rgba(31,30,29,0.04)',
        elevated: '0 4px 12px 0 rgba(31,30,29,0.10), 0 1px 3px 0 rgba(31,30,29,0.06)',
      },
    },
  },
  plugins: [],
};

export default config;
