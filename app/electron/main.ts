import { app, BrowserWindow, ipcMain, shell, dialog, clipboard, powerMonitor } from 'electron';
import { resolve, basename } from 'node:path';
import { EngineClient, EngineBoundaryError, faultOf } from './engine';
const handle=(channel:string,handler:(event:Electron.IpcMainInvokeEvent,...args:any[])=>any)=>ipcMain.handle(channel,async(event,...args)=>{try{return await handler(event,...args);}catch(error){return {engineError:faultOf(error)};}});
import type { ConnectInput } from '../src/auth/bridge';
import type { ConnectResult, GateSettings, SessionStatus } from '../src/net/auth';
import {readStream,saveStream,readLiving} from './stream-config';
import {testTikTok,TikTokService} from './tiktok';
import {readKeyLevels,captureHistory} from './key-levels';
import {readSpeakerStatus,writeSpeakerIntent,readSpeakerIntent,setSpeakerStop} from './speaker';

app.setName('TradeFix Studio');
app.commandLine.appendSwitch('disable-breakpad');
const root = app.isPackaged ? process.resourcesPath : resolve(__dirname, "../..");
const appRoot = app.isPackaged ? app.getAppPath() : resolve(root, "app");
let loginWindow: BrowserWindow | null = null;
let studioWindow: BrowserWindow | null = null;
let engine: EngineClient;
let session: SessionStatus | null = null;
let settings: GateSettings | null = null;
let connecting = false;
let selectedTerminal: string | null = null;
let quitting = false;
let chartPolling = false;
let chartSubscribed = false;
let backgroundAt = 0;
let tiktok:TikTokService;
let activeProfile:{login:number;server:string}|null=null;

function windowFor(mode: 'login' | 'studio') {
  const window = new BrowserWindow({ width: mode === 'login' ? 1100 : 1440, height: 850, minWidth: 760, minHeight: 650,
    show: false, backgroundColor: '#0b0d12', title: 'TradeFix Studio', autoHideMenuBar: true,
    webPreferences: { preload: resolve(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false,
      sandbox: true, webSecurity: true, devTools: false },
  });
  window.setMenu(null);
  window.webContents.setWindowOpenHandler(() => ({action: 'deny'}));
  window.webContents.on('will-navigate', event => event.preventDefault());
  window.webContents.session.setPermissionRequestHandler((_contents, _permission, callback) => callback(false));
  window.once('ready-to-show', () => window.show());
  void window.loadFile(resolve(appRoot, "dist/index.html"));
  return window;
}
function login() {
  if (loginWindow && !loginWindow.isDestroyed()) { loginWindow.show(); loginWindow.focus(); return; }
  const created = windowFor('login');
  loginWindow = created;
  created.on('closed', () => { if (loginWindow === created) loginWindow = null; });
}
function guard(event: Electron.IpcMainInvokeEvent, role: 'login' | 'studio') {
  const window = role === 'login' ? loginWindow : studioWindow;
  if (!window || event.sender !== window.webContents || event.senderFrame !== window.webContents.mainFrame) throw new Error('Unauthorized IPC');
}
async function reconnect(state: 'reconnecting' | 'locked' = 'reconnecting') {
  if (session && studioWindow) studioWindow.webContents.send('gate:session-update', {...session, state});
  session = null;
  chartSubscribed = false;
  await engine.stop();
  login();
}
async function connect(command: 'connect' | 'connect_profile', fields: Record<string, unknown>): Promise<ConnectResult> {
  if (connecting) return {error: {code: 'BUSY', message: 'A connection is already in progress.', field: 'login', actions: []}};
  connecting = true;
  try { await engine.restart();const profile=(fields.profile??fields.request) as {login:number;server:string};await captureHistory(root,{login:profile.login,server:profile.server});const result=await engine.command<ConnectResult>(command, fields);if(!result.error){activeProfile={login:profile.login,server:profile.server};}return result; }
  catch(error) { const fault=faultOf(error);return {error:{code:fault.code,message:fault.message,field:'terminalPath',actions:['retry']}}; }
  finally { connecting = false; }
}

app.whenReady().then(() => {
  saveStream(root,readStream(root));
  tiktok=new TikTokService(
    root,
    status=>studioWindow?.webContents.send('stream:status-update',status),
    welcome=>studioWindow?.webContents.send('stream:welcome',welcome),
    comment=>studioWindow?.webContents.send('stream:comment',comment)
  );
  tiktok.configure(readStream(root));
  handle('stream:status',event=>{guard(event,'studio');return tiktok.status;});
  handle('studio:key-levels',(event,now_ms)=>{guard(event,'studio');if(!session||!activeProfile)return {pdh:null,pdl:null,weekly_open:null};return readKeyLevels(root,activeProfile,Number(now_ms)||Date.now());});
  // The speaker owns the TikTok connection; ORACLE only asks and displays (app/electron/speaker.ts).
  handle('speaker:status',()=>readSpeakerStatus(root));
  handle('speaker:intent',()=>readSpeakerIntent(root));
  handle('speaker:connect',(_e,username:string,connect:boolean)=>writeSpeakerIntent(root,username,connect));
  handle('speaker:stop',(_e,stopped:boolean)=>setSpeakerStop(root,stopped));
  handle('stream:config',event=>{guard(event,'studio');return readStream(root);});
  handle('living:config',event=>{guard(event,'studio');return readLiving(root);});
  handle('stream:save',(event,config)=>{guard(event,'studio');const saved=saveStream(root,config);studioWindow?.webContents.send('stream:updated',saved);tiktok.configure(saved);return saved;});
  handle('stream:test',(event,username)=>{guard(event,'studio');return testTikTok(root,String(username));});
  engine = new EngineClient(root, resolve(app.getPath('userData'), 'profiles.json'),
    progress => loginWindow?.webContents.send('gate:progress', progress),
    () => { if (!quitting && session) void reconnect(); },
    quote => {if(session)studioWindow?.webContents.send('chart:quote',quote);},
    frame => {if(session)studioWindow?.webContents.send('retention:frame',frame);});
  handle('gate:mode', event => {
    if (loginWindow && event.sender === loginWindow.webContents) { guard(event, 'login'); return 'login'; }
    guard(event, 'studio'); return 'studio';
  });
  handle('gate:settings', async event => { guard(event, 'login'); settings = await engine.command<GateSettings>('settings'); return settings; });
  handle('gate:connect', async (event, request: ConnectInput) => {
    guard(event, 'login');
    try { return await connect('connect', {request}); }
    finally { request.password = ''; }
  });
  handle('gate:profile', async (event, profile) => { guard(event, 'login'); return connect('connect_profile', {profile}); });
  handle('gate:preflight', async (event, options) => { guard(event, 'login'); return engine.command('preflight', options); });
  handle('gate:enter', async event => {
    guard(event, 'login');
    if (connecting) throw new Error('Connection pending');
    const active = await engine.command<SessionStatus>('enter');
    // Explicit broadcast allow-list. Account metadata and money never enter this window.
    session = {tradeMode: active.tradeMode, clockProven: active.clockProven, tradingCapable: active.tradingCapable, state: 'connected'};
    if (studioWindow) studioWindow.close();
    const created = windowFor('studio');
    studioWindow = created;
    created.on('closed', () => { if (studioWindow === created) studioWindow = null; });
    loginWindow?.close();
  });
  handle('gate:session', event => { guard(event, 'studio'); return session; });
  handle('chart:subscribe', async (event, tf: string) => {
    guard(event, 'studio');
    if (!session) throw new EngineBoundaryError({code:'TERMINAL_DETACHED',message:'Authenticate an account before loading chart candles.',detail:{},recoverable:true});
    if (!['M1','M5','M15','M30','H1','H4','D1','W1'].includes(tf)) throw new EngineBoundaryError({code:'TF_UNSUPPORTED',message:'Select a supported chart timeframe.',detail:{tf},recoverable:true});
    chartSubscribed = false;
    const frame = await engine.command('chart_subscribe', {tf});
    chartSubscribed = true;
    return frame;
  });
  handle('chart:debug', event => { guard(event, 'studio'); if (!session) throw new Error('Session required'); return engine.command('chart_debug'); });
  handle('studio:settings',event=>{guard(event,'studio');if(!session)throw new Error('Session required');return engine.command('ui_settings');});
  handle('retention:state',event=>{guard(event,'studio');if(!session)throw new Error('Session required');return engine.command('retention_state');});
  handle('chart:indicator', (event, options) => {guard(event,'studio');return engine.command('chart_indicator',{options});});
  setInterval(async () => {
    if (!chartSubscribed || !session || chartPolling) return;
    chartPolling = true;
    try {
      const frames = await engine.command<unknown[]>('chart_poll');
      if (chartSubscribed && session) for (const frame of frames) studioWindow?.webContents.send('chart:frame', frame);
      if(Date.now()-backgroundAt>100){backgroundAt=Date.now();const frame=await engine.command('chart_background');if(frame&&session&&chartSubscribed)studioWindow?.webContents.send('chart:frame',frame);}
    } catch(error) { chartSubscribed = false; studioWindow?.webContents.send('chart:error',faultOf(error)); }
    finally { chartPolling = false; }
  }, 33).unref();
  handle('gate:switch', async event => { guard(event, 'studio'); await reconnect(); });
  handle('gate:diagnostics', async event => { guard(event, 'login'); const text = await engine.command<string>('diagnostics'); clipboard.writeText(text); });
  handle('gate:pick-terminal', async event => {
    guard(event, 'login');
    const picked = await dialog.showOpenDialog(loginWindow!, {title: 'Locate MetaTrader 5 terminal64.exe', properties: ['openFile'], filters: [{name: 'MetaTrader terminal', extensions: ['exe']}]});
    const path = picked.filePaths[0];
    if (picked.canceled || !path || !['terminal64.exe', 'terminal.exe'].includes(basename(path).toLowerCase())) return null;
    selectedTerminal = path; return path;
  });
  handle('gate:external', async (event, kind: string) => {
    guard(event, 'login');
    settings ??= await engine.command<GateSettings>('settings');
    const url = kind === 'signup' ? settings.signupUrl : kind === 'download' ? settings.downloadUrl : kind === 'forgot' ? 'https://my.exness.com/' : null;
    if (!url || new URL(url).protocol !== 'https:') throw new Error('Invalid external destination');
    await shell.openExternal(url);
  });
  handle('gate:open-terminal', async event => {
    guard(event, 'login');
    settings ??= await engine.command<GateSettings>('settings');
    const path = selectedTerminal ?? settings?.terminalPath;
    if (!path) throw new Error('MetaTrader 5 terminal was not found. Locate terminal or install MT5.');
    const error = await shell.openPath(path);
    if (error) throw new Error(error);
  });
  setInterval(() => { if (session && settings?.idleLockMin && powerMonitor.getSystemIdleTime() >= settings.idleLockMin * 60) void reconnect('locked'); }, 10000).unref();
  login();
});
app.on('window-all-closed', () => app.quit());
app.on('before-quit', event => {
  tiktok?.stop();
  if (!quitting) { event.preventDefault(); quitting = true; void engine?.stop().finally(() => app.quit()); }
});

