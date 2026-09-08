import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Zero OS desktop UI (React + Vite), served to the Tauri shell on :5173, built to dist/.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    watch: {
      ignored: ['**/src-tauri/target/**'],
    },
  },
  build: {
    outDir: 'dist',
    target: ['es2021', 'chrome105', 'safari13'],
    sourcemap: true,
  },
  base: './',
});
