import { contextBridge, ipcRenderer } from 'electron';
import type { GateBridge, ConnectInput } from '../src/auth/bridge';
const subscribe = (channel: string, callback: (data: any) => void) => {
  const listener = (_event: Electron.IpcRendererEvent, data: unknown) => callback(data);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
};
const invoke=async(channel:string,...args:any[])=>{const response=await ipcRenderer.invoke(channel,...args);if(response?.engineError)throw response.engineError;return response;};
const bridge: GateBridge = {
  livingConfig:()=>invoke('living:config'),
  streamConfig:()=>invoke('stream:config'),
  streamSave:config=>invoke('stream:save',config),
  streamTest:username=>invoke('stream:test',username),
  onStreamConfig:callback=>subscribe('stream:updated',callback),
  tikTokStatus:()=>invoke('stream:status'),
  onTikTokStatus:callback=>subscribe('stream:status-update',callback),
  onTikTokWelcome:callback=>subscribe('stream:welcome',callback),
  onTikTokComment:callback=>subscribe('stream:comment',callback),
  keyLevels:now_ms=>invoke('studio:key-levels',now_ms),
  speakerStatus:()=>invoke('speaker:status'),
  speakerIntent:()=>invoke('speaker:intent'),
  speakerConnect:(username:string,connect:boolean)=>invoke('speaker:connect',username,connect),
  speakerStop:(stopped:boolean)=>invoke('speaker:stop',stopped),
  mode: () => invoke('gate:mode'),
  settings: () => invoke('gate:settings'),
  connect: (request: ConnectInput) => {
    try { return invoke('gate:connect', request); }
    finally { request.password = ''; }
  },
  connectProfile: profile => invoke('gate:profile', profile),
  preflight: options => invoke('gate:preflight', options),
  enterStudio: () => invoke('gate:enter'),
  session: () => invoke('gate:session'),
  switchAccount: () => invoke('gate:switch'),
  copyDiagnostics: () => invoke('gate:diagnostics'),
  pickTerminal: () => invoke('gate:pick-terminal'),
  openExternal: kind => invoke('gate:external', kind),
  openTerminal: () => invoke('gate:open-terminal'),
  onProgress: callback => subscribe('gate:progress', callback),
  onSession: callback => subscribe('gate:session-update', callback),
  chartSubscribe: tf => invoke('chart:subscribe', tf),
  chartDebug: () => invoke('chart:debug'),
  chartIndicator: options => invoke('chart:indicator',options),
  onChart: callback => subscribe('chart:frame', callback),
  onQuote: callback => subscribe('chart:quote',callback),
  studioSettings:()=>invoke('studio:settings'),
  retentionState:()=>invoke('retention:state'),
  onRetention:callback=>subscribe('retention:frame',callback),
  onChartError: callback => subscribe('chart:error', callback),
};
contextBridge.exposeInMainWorld('oracle', bridge);
