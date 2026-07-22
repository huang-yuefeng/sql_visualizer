import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';
import { copyFileSync, existsSync } from 'fs';

const __dirname = dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [
    react(),
    {
      name: 'copy-elk-bundled',
      writeBundle() {
        const src = resolve(__dirname, 'node_modules/elkjs/lib/elk.bundled.js');
        const dest = resolve(__dirname, 'dist/elk.bundled.js');
        if (existsSync(src)) {
          copyFileSync(src, dest);
          console.log('  ✅ Copied elk.bundled.js to dist/');
        } else {
          console.warn('  ⚠ elk.bundled.js not found at', src);
        }
      },
    },
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://backend:8000',
        changeOrigin: true,
      },
    },
  },
});
