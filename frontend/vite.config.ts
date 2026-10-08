import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  base: '/app/',
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(
      [
        '/status',
        '/roles',
        '/agents',
        '/missions',
        '/workflows',
        '/memory',
        '/approvals',
        '/artifacts',
      ].map((path) => [path, { target: 'http://127.0.0.1:8000', changeOrigin: false }]),
    ),
  },
  test: { environment: 'jsdom', setupFiles: ['./src/test-setup.ts'], restoreMocks: true },
});
