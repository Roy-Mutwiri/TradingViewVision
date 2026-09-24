/** Browser proof of the Phase-0 dashboard; no desktop capture claim. */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
const root = resolve(import.meta.dirname, '../..');
const python = process.env.ORACLE_PYTHON ?? resolve(root, process.platform === 'win32' ? '.venv312/Scripts/python.exe' : '.venv312/bin/python');
const output = resolve(root, 'artifacts/phase0');
await mkdir(output, { recursive: true });
const server = spawn(python, ['-m', 'oracle.cli', 'dashboard'], { cwd: root, windowsHide: true });
server.stderr.on('data', data => process.stderr.write(data));
let browser;
try {
  let ready = false;
  for (let i = 0; i < 100; i++) {
    try { if ((await fetch('http://127.0.0.1:8765/health')).ok) { ready = true; break; } } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  if (!ready) throw new Error('Dashboard did not become ready');
  browser = await chromium.launch();
  const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: output, size: { width: 1920, height: 1080 } } });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:8765');
  await page.screenshot({ path: resolve(output, 'dashboard.png') });
  console.log('Recording 60 seconds of the Phase-0 dashboard.');
  await page.waitForTimeout(60000);
  const video = page.video();
  await context.close();
  await video.saveAs(resolve(output, 'dashboard-60s.webm'));
  await video.delete();
} finally {
  if (browser) await browser.close();
  server.kill();
}
