import { build } from 'esbuild';
await build({entryPoints: ['electron/main.ts'], outfile: 'electron-dist/main.cjs', bundle: true, platform: 'node', format: 'cjs', external: ['electron'], target: 'node22'});
await build({entryPoints: ['electron/preload.ts'], outfile: 'electron-dist/preload.cjs', bundle: true, platform: 'node', format: 'cjs', external: ['electron'], target: 'node22'});
