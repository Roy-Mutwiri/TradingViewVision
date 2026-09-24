import {defaultCamera,type CameraConfig} from './Camera';
export interface LivingConfig {
  candidates_enabled:boolean;discard_fade_ms:number;draw_on_ms:number;
  attention_enabled:boolean;attention_move_ms:number;reeval_sweep_enabled:boolean;
  measurement_gesture:{enabled:boolean;max_per_3min:number;hold_ms:number};
  measurement_min_interval_s:number;
  session_scan_enabled:boolean;camera_drift_enabled:boolean;
  visual_events_per_minute:number;concurrent_animations:number;worklog_entries:number;
  camera:CameraConfig;
}
export const defaultLiving:LivingConfig={candidates_enabled:true,discard_fade_ms:600,draw_on_ms:450,attention_enabled:true,attention_move_ms:500,reeval_sweep_enabled:true,measurement_gesture:{enabled:true,max_per_3min:1,hold_ms:2500},measurement_min_interval_s:180,session_scan_enabled:true,camera_drift_enabled:true,visual_events_per_minute:12,concurrent_animations:3,worklog_entries:8,camera:defaultCamera};
