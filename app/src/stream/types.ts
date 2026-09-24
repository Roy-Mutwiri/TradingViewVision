export interface StreamConfig {
  tiktok: {username:string;poll_interval_s:number;show_viewer_count:boolean;show_follower_count:boolean;auto_connect_comments:boolean;sessionid?:string;tt_target_idc?:string};
  watermark: {text:string;enabled:boolean;opacity:number;scale:number;position:'center'|'bottom_right'|'tiled'};
  brand: {handle:string};
}
export interface ConnectionTest {outcome:'LIVE'|'OFFLINE'|'NOT_FOUND'|'UNREACHABLE';message:string;profile_name:string|null;error?:string}
export interface TikTokStatus {state:'LIVE'|'OFFLINE'|'CONNECTING'|'UNKNOWN'|'NOT_CONFIGURED';username:string|null;viewers:number|null;live_since_ms:number|null;last_checked_ms:number;error:string|null}
export interface TikTokWelcome {name:string;at_ms:number;returning?:boolean;join_count?:number;first_seen_ms?:number}
export interface TikTokWelcomeMemory {name:string;first_seen_ms:number;last_seen_ms:number;join_count:number}
export interface TikTokComment {name:string;user_id?:string;text:string;at_ms:number}
export interface KeyLevelContext {pdh:number|null;pdl:number|null;weekly_open:number|null;as_of_ms?:number;error?:string}
export const defaultStream:StreamConfig={tiktok:{username:'xauusa2',poll_interval_s:30,show_viewer_count:true,show_follower_count:false,auto_connect_comments:true,sessionid:'',tt_target_idc:''},watermark:{text:'TradeFix',enabled:true,opacity:.05,scale:.55,position:'center'},brand:{handle:'@xauusa2'}};
