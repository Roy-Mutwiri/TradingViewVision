import { spawnSync } from 'node:child_process';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { existsSync } from 'node:fs';
import { compile } from 'json-schema-to-typescript';

const root = resolve(import.meta.dirname, '../..');
const envDir = existsSync(resolve(root, '.venv312')) ? '.venv312' : '.venv';
const python = process.env.ORACLE_PYTHON ?? resolve(root, process.platform === 'win32' ? `${envDir}/Scripts/python.exe` : `${envDir}/bin/python`);
for (const [stem, module, title, source] of [
  ['protocol', 'oracle.transport.protocol', 'OracleProtocol', 'engine/oracle/models.py'],
  ['auth', 'oracle.auth.schema', 'OracleAuth', 'engine/oracle/auth/contracts.py'],
  ['chart', 'oracle.transport.chart', 'OracleChart', 'engine/oracle/transport/chart.py'],
  ['retention', 'oracle.director.contracts', 'OracleRetention', 'engine/oracle/director/contracts.py'],
]) {
  const schemaPath = resolve(root, `app/src/net/${stem}.schema.json`);
  const checking = process.argv.includes('--check');
  const oldSchema = checking && existsSync(schemaPath) ? await readFile(schemaPath, 'utf8') : null;
  const result = spawnSync(python, ['-m', module, schemaPath], { cwd: resolve(root, 'engine'), encoding: 'utf8' });
  if (result.status !== 0) throw new Error('Schema exporter failed');
  if (checking && (oldSchema === null || oldSchema !== await readFile(schemaPath, 'utf8'))) {
    if (oldSchema !== null) await writeFile(schemaPath, oldSchema);
    throw new Error(`${stem} JSON Schema drift: run npm run protocol:generate`);
  }
  const schema = JSON.parse(await readFile(schemaPath, 'utf8'));
  const output = await compile(schema, title, {
    bannerComment: `/* Generated from ${source}. Do not edit. */`,
    additionalProperties: false, enableConstEnums: false,
  });
  const target = resolve(root, `app/src/net/${stem}.ts`);
  await mkdir(resolve(root, 'app/src/net'), { recursive: true });
  if (checking) {
    if (!existsSync(target) || await readFile(target, 'utf8') !== output) throw new Error(`${stem} protocol drift: run npm run protocol:generate`);
  } else await writeFile(target, output);
}
