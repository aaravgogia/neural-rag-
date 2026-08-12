import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Vendor splitting: framework/animation/charts libraries change far
        // less often than app code, so isolating them into their own chunks
        // means a deploy that only touches app code doesn't invalidate the
        // browser cache for React/Framer Motion/Recharts on every visit.
        manualChunks: {
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          'vendor-motion': ['framer-motion'],
          'vendor-charts': ['recharts'],
          // Three.js lives behind the landing-route hero's dynamic import.
          'vendor-three': ['three', '@react-three/fiber', '@react-three/drei'],
          'vendor-cmdk': ['cmdk'],
        },
      },
    },
  },
});
