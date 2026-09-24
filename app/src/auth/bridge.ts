import type { ConnectProgress, ConnectRequest, ConnectResult, GateSettings, Profile, SessionStatus } from '../net/auth';
import type { ChartFrame, ChartDebug } from '../net/chart';
export type ConnectInput = ConnectRequest & { passwordType: 'investor' | 'master'; remember: boolean };
export interface GateBridge {
  livingConfig?():Promise<import('../living/types').LivingConfig>;
  streamConfig?():Promise<import('../stream/types').StreamConfig>;
  streamSave?(config:import('../stream/types').StreamConfig):Promise<import('../stream/types').StreamConfig>;
  streamTest?(username:string):Promise<import('../stream/types').ConnectionTest>;
  onStreamConfig?(callback:(config:import('../stream/types').StreamConfig)=>void):()=>void;
  tikTokStatus?():Promise<import('../stream/types').TikTokStatus>;
  onTikTokStatus?(callback:(status:import('../stream/types').TikTokStatus)=>void):()=>void;
  onTikTokWelcome?(callback:(welcome:import('../stream/types').TikTokWelcome)=>void):()=>void;
  onTikTokComment?(callback:(comment:import('../stream/types').TikTokComment)=>void):()=>void;
  keyLevels?(now_ms:number):Promise<import('../stream/types').KeyLevelContext>;
  /** The speaker's TikTok input. ORACLE asks and displays; the connection lives in the speaker process. */
  speakerStatus?():Promise<import('../net/speaker').SpeakerStatus>;
  speakerIntent?():Promise<{username:string;connect:boolean}>;
  speakerConnect?(username:string,connect:boolean):Promise<import('../net/speaker').SpeakerStatus>;
  speakerStop?(stopped:boolean):Promise<boolean>;
  mode(): Promise<'login' | 'studio'>;
  settings(): Promise<GateSettings>;
  connect(request: ConnectInput): Promise<ConnectResult>;
  connectProfile(profile: Pick<Profile, 'login' | 'server' | 'passwordType'>): Promise<ConnectResult>;
  preflight(options: { symbol?: string; download?: boolean }): Promise<ConnectResult>;
  enterStudio(): Promise<void>;
  session(): Promise<SessionStatus | null>;
  switchAccount(): Promise<void>;
  copyDiagnostics(): Promise<void>;
  pickTerminal(): Promise<string | null>;
  openExternal(kind: 'signup' | 'download' | 'forgot'): Promise<void>;
  openTerminal(): Promise<void>;
  onProgress(callback: (progress: ConnectProgress) => void): () => void;
  onSession(callback: (status: SessionStatus) => void): () => void;
  chartSubscribe(tf: import('../net/protocol').Bar['tf']): Promise<ChartFrame>;
  chartDebug(): Promise<ChartDebug>;
  chartIndicator(options:{enabled?:boolean;key?:number;atr_period?:number;show_stop_line?:boolean;color_bars?:boolean}): Promise<ChartFrame>;
  onChart(callback: (frame: ChartFrame) => void): () => void;
  onQuote(callback: (quote:import('../net/chart').TickQuote)=>void):()=>void;
  studioSettings():Promise<{mode:'broadcast'|'operator';language:string}>;
  retentionState():Promise<import('../net/retention').RetentionFrame>;
  onRetention(callback:(frame:import('../net/retention').RetentionFrame)=>void):()=>void;
  onChartError(callback: (fault: {code:string;message:string;detail:Record<string,unknown>;recoverable:boolean}) => void): () => void;
}
declare global { interface Window { oracle?: GateBridge } }
