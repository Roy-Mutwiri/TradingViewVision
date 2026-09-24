import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests/visual', workers: 1, fullyParallel: false,
  use: { baseURL: 'http://127.0.0.1:4173', viewport: {width: 1100, height: 850}, screenshot: 'off', video: 'off', trace: 'off', reducedMotion: 'reduce' },
  webServer: {command: 'npm run build && npm exec vite preview -- --host 127.0.0.1 --port 4173 --strictPort', url: 'http://127.0.0.1:4173', timeout: 120000, reuseExistingServer: false},
});
