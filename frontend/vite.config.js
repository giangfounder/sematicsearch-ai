import { defineConfig } from 'vite';
import { svelte } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  resolve: {conditions:['browser']},
  build: { outDir: '../app/static', emptyOutDir: false, manifest: true },
  server: { proxy: { '/v1': 'http://127.0.0.1:8000', '/health': 'http://127.0.0.1:8000', '/logo.png': 'http://127.0.0.1:8000' } },
  test: { environment: 'jsdom', setupFiles: ['./src/test/setup.js'], clearMocks: true, restoreMocks: true },
});
