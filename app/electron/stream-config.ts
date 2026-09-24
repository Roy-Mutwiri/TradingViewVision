import {readFileSync,writeFileSync,renameSync} from 'node:fs';
import {resolve} from 'node:path';
import {parseDocument,stringify} from 'yaml';
import {defaultStream,type StreamConfig} from '../src/stream/types';
import {defaultLiving,type LivingConfig} from '../src/living/types';

export function readLiving(root:string):LivingConfig {
  const raw=parseDocument(readFileSync(resolve(root,'config/oracle.yaml'),'utf8')).toJS()?.living??{};
  const draw=Array.isArray(raw.draw_on_ms)?(Number(raw.draw_on_ms[0])+Number(raw.draw_on_ms[1]))/2:raw.draw_on_ms??defaultLiving.draw_on_ms;
  return {...defaultLiving,...raw,draw_on_ms:Math.max(350,Math.min(600,draw)),
    visual_events_per_minute:raw.budget_events_per_min??raw.visual_events_per_minute??12,
    concurrent_animations:raw.budget_concurrent??raw.concurrent_animations??3,
    session_scan_enabled:raw.session_scan??raw.session_scan_enabled??true,
    camera:{...defaultLiving.camera,...raw.camera,enabled:raw.camera?.enabled??raw.camera_drift_enabled??true},
    measurement_gesture:{...defaultLiving.measurement_gesture,...raw.measurement_gesture,hold_ms:2500}};
}

export function readStream(root:string):StreamConfig {
  const raw=parseDocument(readFileSync(resolve(root,'config/oracle.yaml'),'utf8')).toJS()?.stream??{};
  return {tiktok:{...defaultStream.tiktok,...raw.tiktok},watermark:{...defaultStream.watermark,...raw.watermark},brand:{...defaultStream.brand,...raw.brand}};
}
export function saveStream(root:string,config:StreamConfig):StreamConfig {
  const next:StreamConfig={tiktok:{...config.tiktok,username:config.tiktok.username.trim().replace(/^@/,'').trim(),sessionid:(config.tiktok.sessionid??'').trim(),tt_target_idc:(config.tiktok.tt_target_idc??'').trim()},watermark:{...config.watermark},brand:{handle:config.brand.handle.trim()}};
  if(!/^[\w.]*$/.test(next.tiktok.username))throw Error('Enter a TikTok username, without a URL or spaces.');
  if(!Number.isFinite(next.watermark.opacity)||next.watermark.opacity<0||next.watermark.opacity>1)throw Error('Watermark opacity must be between 0 and 1.');
  if(!['center','bottom_right','tiled'].includes(next.watermark.position))throw Error('Choose a watermark position.');
  const path=resolve(root,'config/oracle.yaml');
  const document=parseDocument(readFileSync(path,'utf8'));document.set('stream',next);
  writeFileSync(path+'.tmp',document.toString(),'utf8');renameSync(path+'.tmp',path);
  return next;
}
// The frozen analysis engine rejects unknown top-level keys. Keep UI config at
// the desktop boundary and give the unmodified engine an equivalent projection.
export function engineConfigPath(root:string):string {
  const document=parseDocument(readFileSync(resolve(root,'config/oracle.yaml'),'utf8')).toJS();
  delete document.stream;
  delete document.living;
  const path=resolve(root,'config/oracle.desktop.yaml');
  writeFileSync(path,stringify(document),'utf8');return path;
}
