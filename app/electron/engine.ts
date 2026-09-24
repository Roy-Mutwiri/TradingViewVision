import { spawn, type ChildProcessWithoutNullStreams } from 'node:child_process';
import { existsSync, writeFileSync } from 'node:fs';
import { createInterface } from 'node:readline';
import { resolve } from 'node:path';
import type { ConnectProgress } from '../src/net/auth';
import {engineConfigPath} from './stream-config';
export type EngineFault = {code:string;message:string;detail:Record<string,unknown>;recoverable:boolean};
export class EngineBoundaryError extends Error { constructor(public fault:EngineFault){super(fault.message);} }
export const faultOf=(error:unknown):EngineFault=>error instanceof EngineBoundaryError?error.fault:{code:'IPC_REJECTED',message:error instanceof Error?error.message:'The IPC response was invalid; reconnect the desktop.',detail:{},recoverable:true};
export class EngineClient {
  private child: ChildProcessWithoutNullStreams | null = null;
  private sequence = 0;
  private pending = new Map<number, { resolve: (data: any) => void; reject: (error: Error) => void; timer: ReturnType<typeof setTimeout> }>();
  constructor(private root: string, private profiles: string, private progress: (p: ConnectProgress) => void,
              private disconnected: () => void, private quote: (data: import('../src/net/chart').TickQuote)=>void = ()=>{},
              private retention:(data:import('../src/net/retention').RetentionFrame)=>void=()=>{}) {}
  private packagedPython() {
    if (process.env.ORACLE_PYTHON) return process.env.ORACLE_PYTHON;
    const bundledVenv = resolve(this.root, '.venv312');
    const bundledRuntime = resolve(this.root, 'runtime/python/cpython-3.12.14-windows-x86_64-none');
    const bundledPython = resolve(bundledVenv, process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');
    const runtimePython = resolve(bundledRuntime, process.platform === 'win32' ? 'python.exe' : 'bin/python');
    if (existsSync(bundledPython) && existsSync(runtimePython)) {
      try {
        const cfg = ['home = '+bundledRuntime, 'include-system-site-packages = false', 'version = 3.12.14', 'executable = '+runtimePython, ''].join('\n');
        writeFileSync(resolve(bundledVenv, 'pyvenv.cfg'), cfg, 'utf8');
      } catch { /* Some install locations may be read-only after first launch. */ }
      return bundledPython;
    }
    const local = resolve(this.root, process.platform === 'win32' ? '.venv312/Scripts/python.exe' : '.venv312/bin/python');
    if (existsSync(local)) return local;
    throw new EngineBoundaryError({code:'ENGINE_SETUP_FAILED',message:'TradeFix Studio is missing its bundled runtime. Reinstall TradeFix Studio using the latest installer.',detail:{},recoverable:true});
  }
  start() {
    if (this.child) return;
    const python = this.packagedPython();
    const enginePath = resolve(this.root, 'engine');
    const existingPythonPath = process.env.PYTHONPATH;
    const pythonPath = existingPythonPath ? `${enginePath}${process.platform === 'win32' ? ';' : ':'}${existingPythonPath}` : enginePath;
    const bootstrap = `import sys, runpy; sys.path.insert(0, ${JSON.stringify(enginePath)}); runpy.run_module('oracle.auth.worker', run_name='__main__')`;
    const child = spawn(python, ['-c', bootstrap, '--config', engineConfigPath(this.root), '--profiles', this.profiles], {
      cwd: this.root, windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'], env: { ...process.env, PYTHONPATH: pythonPath, PYTHONUNBUFFERED: '1', PYTHONIOENCODING: 'utf-8' },
    });
    this.child = child;
    // Raw SDK/process output is never forwarded to a renderer or recorded.
    child.stderr.resume();
    createInterface({input: child.stdout}).on('line', line => {
      if (child !== this.child) return;
      try {
        const packet = JSON.parse(line);
        if (packet.event === 'progress') { this.progress(packet.data); return; }
        if (packet.event === 'quote') { this.quote(packet.data); return; }
        if (packet.event === 'retention') { this.retention(packet.data); return; }
        const item = this.pending.get(packet.id);
        if (!item) return;
        clearTimeout(item.timer); this.pending.delete(packet.id);
        if (packet.error) item.reject(new EngineBoundaryError(packet.error));
        else item.resolve(packet.result);
      } catch { /* Ignore non-protocol stdout; never echo it. */ }
    });
    const lost = () => { if (this.child === child) { this.child = null; this.rejectPending(); this.disconnected(); } };
    child.on('error', lost); child.on('exit', lost);
  }
  private rejectPending() {
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new EngineBoundaryError({code:'TERMINAL_DETACHED',message:'The engine disconnected; reconnect your account.',detail:{},recoverable:true})); }
    this.pending.clear();
  }
  command<T>(command: string, fields: Record<string, any> = {}): Promise<T> {
    this.start();
    const id = ++this.sequence;
    const payload = JSON.stringify({id, command, ...fields}) + "\n";
    if (fields.request && typeof fields.request === 'object') fields.request.password = '';
    return new Promise<T>((resolveRequest, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new EngineBoundaryError({code:'ENGINE_TIMEOUT',message:`The ${command} request timed out; retry the connection.`,detail:{command},recoverable:true})); this.stop(); }, command === 'preflight' || command === 'chart_subscribe' || command === 'chart_background' ? 600000 : 120000);
      this.pending.set(id, { resolve: resolveRequest, reject, timer });
      const child = this.child;
      if (!child) { this.rejectPending(); return; }
      child.stdin.write(payload, 'utf8', error => { if (error) this.stop(); });
    });
  }
  async restart() { await this.stop(); this.start(); }
  stop(): Promise<void> {
    const child = this.child; this.child = null; this.rejectPending();
    if (!child) return Promise.resolve();
    return new Promise(resolveStop => {
      const timer = setTimeout(() => {
        if (process.platform === 'win32' && child.pid) {
          // python.exe in the embedded venv is a launcher. Killing only that
          // process leaves its runtime child alive and able to keep writing the
          // account ledger after the desktop has restarted.
          const killer = spawn('taskkill', ['/pid', String(child.pid), '/T', '/F'], {
            windowsHide: true, stdio: 'ignore',
          });
          killer.once('exit', resolveStop);
          killer.once('error', () => resolveStop());
        } else { child.kill('SIGKILL'); resolveStop(); }
      }, 10000);
      child.once('exit', () => { clearTimeout(timer); resolveStop(); });
      child.stdin.end(); // Worker finally shuts down MT5 and closes account-scoped stores.
    });
  }
}
