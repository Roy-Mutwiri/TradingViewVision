import type {DrawObject} from '../net/protocol';
import {fmt} from '../fmt';

export const CHART_FONT='Consolas, "Cascadia Mono", "Segoe UI Emoji", "Apple Color Emoji", monospace';
export const axisPrice=fmt.axis;
export const chipPrice=fmt.price;
export type Rect={x:number;y:number;width:number;height:number};
export type LabelCandidate={id:string;t:number;priority:number;x:number;anchor:number;below:boolean;lines:string[];width:number;height:number;color:string;opacity?:number;strikethrough?:boolean;pinnedLevel?:boolean;levelPrice?:number;token?:string};
export type LabelPlacement={candidate:LabelCandidate;box:Rect|null};
export const overlaps=(a:Rect,b:Rect,pad=0)=>a.x<b.x+b.width+pad&&a.x+a.width+pad>b.x&&a.y<b.y+b.height+pad&&a.y+a.height+pad>b.y;

/** Keep the ruler and its chip inside the plot, preferring free space near price. */
export function measurementColumn(preferred:number,ys:number[],bodies:Rect[],width:number,labelWidth:number):number {
  const maximum=Math.max(12,width-12),minimum=Math.min(maximum,labelWidth+30);
  const start=Math.max(minimum,Math.min(preferred,maximum));
  for(let column=start;column>=minimum;column-=32){
    const area={x:column-labelWidth-24,y:Math.min(...ys)-38,width:labelWidth+30,height:Math.max(...ys)-Math.min(...ys)+44};
    if(!bodies.some(body=>overlaps(area,body,2)))return column;
  }
  return start;
}

/** Deterministic placement pass. Reserve the right gutter for the price axis. */
export function placeLabels(candidates:LabelCandidate[],bodies:Rect[],width:number,height:number,limit=10,reserved:Rect[]=[]):LabelPlacement[] {
  const gutter=72,usableWidth=Math.max(80,width-gutter),placed:Rect[]=[...reserved],result:LabelPlacement[]=[],pinnedSlots=new Map<number,number>();let used=0;
  const offsets=[0,12,24,36];
  const ordered=[
    ...candidates.filter(c=>c.pinnedLevel).sort((a,b)=>b.priority-a.priority||Math.round(a.anchor)-Math.round(b.anchor)||a.id.localeCompare(b.id)),
    ...candidates.filter(c=>!c.pinnedLevel).sort((a,b)=>b.priority-a.priority||b.t-a.t||a.id.localeCompare(b.id)),
  ];
  for(const candidate of ordered){
    let box:Rect|null=null;
    if(used+candidate.lines.length<=limit&&candidate.width<=usableWidth-12){
      if(candidate.pinnedLevel){
        const key=Math.round(candidate.anchor/10)*10;
        const slot=pinnedSlots.get(key)??0;
        pinnedSlots.set(key,slot+1);
        const y=Math.max(0,Math.min(candidate.anchor-candidate.height-4,height-candidate.height));
        for(const offset of [slot,...Array.from({length:8},(_,i)=>i+slot+1)]){
          const x=Math.max(6,Math.min(candidate.x-candidate.width-offset*(candidate.width+8),usableWidth-6-candidate.width));
          const trial={x,y,width:candidate.width,height:candidate.height};
          if(placed.some(other=>overlaps(trial,other,4)))continue;
          box=trial;break;
        }
      }else{
      const horizontal=[candidate.below?'below':'above',candidate.below?'above':'below','right','left'] as const;
      outer: for(const side of horizontal){
        for(const offset of offsets){
          let x=candidate.x-candidate.width/2,y=candidate.anchor-candidate.height/2;
          if(side==='below'){y=candidate.anchor+8+offset;}
          else if(side==='above'){y=candidate.anchor-8-candidate.height-offset;}
          else if(side==='right'){x=candidate.x+10+offset;y=candidate.anchor-candidate.height/2;}
          else {x=candidate.x-candidate.width-10-offset;y=candidate.anchor-candidate.height/2;}
          x=Math.max(6,Math.min(x,usableWidth-6-candidate.width));
          y=Math.max(6,Math.min(y,height-6-candidate.height));
          const trial={x,y,width:candidate.width,height:candidate.height};
          if(trial.x+trial.width>usableWidth)continue;
          if(placed.some(other=>overlaps(trial,other,4))||bodies.some(body=>overlaps(trial,body,2)))continue;
          box=trial;break outer;
        }
      }
      }
    }
    if(box){placed.push(box);used+=candidate.lines.length;}
    result.push({candidate,box});
  }
  return result;
}

export function labelPriority(obj:DrawObject):number {
  const token=obj.style.token;
  if(token==='call.trade'||token==='call.level'||token.startsWith('analysis.')||obj.text_args.state==='ACTIVE')return 100;
  if(token==='structure.event')return String(obj.text_args.kind??'').toUpperCase()==='BOS'?78:80;
  if(token==='structure.protected')return 70;
  if(token==='detector.confluence')return 75;
  if(token.startsWith('utbot.'))return obj.text_args.active_signal?60:20;
  if(token==='liquidity.pool'||token==='liquidity.reclaim')return 50;
  if(obj.shape==='ZONE'||/zone|order.?block|fvg|\.ob\b/.test(token))return 40;
  if(/structure|choch|bos|mss|sweep/.test(token))return 80;
  return 3;
}

/** Display projection only: the ledger's reason chain remains untouched. No parameter values. */
export function compactCallReason(source:string):string {
  const clean=source.replace(/\b(?:ATR|k|periods?|parameters?)\b\s*(?:\([^)]*\)|(?:[:=]\s*)?[+-]?[\d,.]+)?/gi,'');
  const tags=/\b(?:EQH|EQL|PDH|PDL|PWH|PWL|BSL|SSL|CHOCH|BOS|MSS|IFVG|FVG|OB|OTE|SWEEP|DISCOUNT|PREMIUM|ENTRY|SL|TP[12]|M[15]|M15|M30|H[14]|D1|W1)\b/gi;
  const values=/\b\d{2}:\d{2}(?::\d{2})?\b|\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{3,}(?:\.\d+)?\b/g;
  const parts=[...clean.matchAll(tags),...clean.matchAll(values)].sort((a,b)=>a.index!-b.index!);
  return parts.map(match=>match[0].includes(':')?match[0]:/^\d/.test(match[0])?chipPrice(Number(match[0].replaceAll(',',''))):match[0].toUpperCase()).join(' ');
}

export function labelLines(obj:DrawObject):string[] {
  if(obj.style.token==='call.trade'){
    const a=obj.text_args,state=String(a.call_state),livePhase=String(a.live_phase??'TRACKING'),tf=String(a.tf??'M15'),side=String(a.direction)==='BULLISH'?'BUY':'SELL',grade=String(a.grade??'A'),paper=String(a.broadcast_mode??'paper')==='paper'?'  PAPER':'';
    if(state==='CANCELLED')return [`${tf} ${side}  ${grade}  CANCELLED${paper}`, String(a.resolution_reason??'cancelled').toLowerCase().replaceAll('_',' ')];
    const distance=Number(a.entry_distance??0);
    const header=state==='WATCH'
      ? (a.watch_passes===false&&a.first_fail==='R_MIN'?`WATCH ${side}  ${a.grade??'A'}  R ${fmt.one(Number(a.reward_r))} < ${fmt.one(Number(a.min_r??1.5))}${paper}`:`WATCH ${side}  if price returns  ${chipPrice(distance)} away  ${fmt.r(Number(a.reward_r))}${paper}`)
      : state==='PENDING'
      ? `${tf} ${side} LIMIT  ${grade}  PENDING  ${chipPrice(distance)} away  ${Number(a.bars_remaining??0)} bars${paper}`
      : state==='ACTIVE'?`${tf} ${side}  ${grade}  ACTIVE  ${fmt.r(Number(a.live_r))}${paper}`:state==='WIN'?`${tf} ${side}  ${grade}  WIN${paper}`:state==='LOSS'?`${tf} ${side}  ${grade}  LOSS${paper}`:`${tf} ${side}  ${grade}  ${state}${paper}`;
    const lines=[header,
      `ENTRY  ${chipPrice(Number(a.entry_lo))}-${chipPrice(Number(a.entry_hi))}`,
      `SL  ${chipPrice(Number(a.stop))}`,
      `TP1  ${chipPrice(Number(a.tp1))}  ${fmt.r(Number(a.reward_r))}`];
    if(a.tp2!=null)lines.push(`TP2  ${chipPrice(Number(a.tp2))}`);
    if(state==='PENDING'&&a.too_far)lines.push(`WATCHING  ${fmt.usd(Number(a.entry_distance))} USD away`);
    if(livePhase==='SL_HIT_SEARCHING')lines.push('SL HIT  SEARCHING NEW ENTRY');
    else if(livePhase==='TP2_HIT_SEARCHING'||livePhase==='TP2_HIT')lines.push('TP2 HIT  SEARCHING NEW ENTRY');
    else if(livePhase==='TP1_HIT_WAITING_TP2')lines.push('TP1 HIT  WAITING TP2');
    else if(livePhase==='TP1_HIT')lines.push('TP1 HIT');
    return lines;
  }
  if(obj.style.token==='liquidity.reclaim')return ['RECLAIMED'];
  if(obj.style.token==='liquidity.pool'){
    if(obj.text_args.lifecycle==='DISCARDED')return [`SWEEP ${String(obj.text_args.discard_reason).toLowerCase().replaceAll('_',' ')}`];
    if(obj.text_args.confirmed===false)return [`SWEEP? ${Number(obj.text_args.bars_left)} bars`];
    if(obj.text_args.pool_state==='SWEPT')return [`SWEPT ${new Date(Number(obj.text_args.swept_ms)).toISOString().slice(11,16)}`];
    return [`${String(obj.text_args.name)}${Number(obj.text_args.strength)>1?` ${Number(obj.text_args.strength)}`:''}`];
  }
  if(obj.style.token==='zone.ob'){
    const tf=String(obj.text_args.tf);
    if(obj.text_args.lifecycle==='DISCARDED')return [`OB ${String(obj.text_args.failed_criterion??obj.text_args.discard_reason).toLowerCase().replaceAll('_',' ')}`];
    if(obj.text_args.confirmed===false)return [`OB? ${tf}`];
    const strength=Number(obj.text_args.strength??1);
    return [`${tf} ${obj.text_args.ob_state==='BREAKER'?'BREAKER':'OB'}${obj.text_args.validation_kind==='CHoCH'?' CHoCH':''}${strength>1?` ${strength}`:''}`];
  }
  if(obj.style.token==='structure.event'){const d=String(obj.text_args.direction??'').toUpperCase();return [`${String(obj.text_args.kind)} ${d==='DOWN'?'\u2193':'\u2191'}`];}
  if(obj.style.token==='structure.protected')return ['PROTECTED'];
  if(obj.style.token==='living.session')return [String(obj.text_args.name).toUpperCase()];
  if(obj.style.token==='living.measurement')return [`${fmt.usd(Number(obj.text_args.value))} ${String(obj.text_args.unit)==='pts'?'USD':String(obj.text_args.unit)}`];
  if(obj.style.token==='zone.fvg'){
    if(obj.text_args.lifecycle==='DISCARDED'){
      const names:Record<string,string>={INVALIDATED:'invalidated',SUPERSEDED:'superseded',MERGED:'merged',FAILED_CRITERIA:'failed criteria',STALE:'stale',DATA_GAP:'data gap'};
      const criterion=obj.text_args.failed_criterion;
      const reason=criterion==='GAP_FILLED'?'filled':criterion==='FVG_SIZE'?'size gate':names[String(obj.text_args.discard_reason)]??'invalidated';
      return [`FVG  ${reason}`];
    }
    if(obj.text_args.confirmed===false)return ['FVG ?'];
    if(obj.text_args.kind==='IFVG')return ['IFVG'];
    if(obj.text_args.weakened)return ['FVG  CE lost'];
    const strength=Number(obj.text_args.strength??1),fill=Math.round(Number(obj.text_args.fill_pct??0)*100);
    return [`FVG${strength>1?` ${strength}`:''}  ${fill}%`];
  }
  if(obj.style.token==='detector.confluence')return [String(obj.text_args.label??'CONFLUENCE')];
  if(obj.style.token.startsWith('notebook.'))return [String(obj.text_args.label??obj.text_args.text??'NOTE')];
  if(obj.style.token==='call.level')return [String(obj.text_args.level_role??'CALL')];
  if(obj.style.token.startsWith('utbot.'))return obj.text_args.active_signal?[obj.style.token==='utbot.buy'||obj.text_args.direction==='BULLISH'?'BUY':'SELL']:[];
  if(obj.style.token==='analysis.reason')return String(obj.text_args.label??obj.reason).split('\n').slice(0,3).map(compactCallReason).filter(Boolean);
  const raw=String(obj.text_args.label??obj.text_args.text??'');
  const known=raw.match(/\b(?:ENTRY|SL|TP[12]|EQH|EQL|PDH|PDL|PWH|PWL|BSL|SSL|CHOCH|BOS|MSS|IFVG|FVG|OB|OTE|HIGH|LOW|OPEN|LIQUIDITY)\b/i)?.[0];
  const name=known?.toUpperCase()??(obj.shape==='ZONE'?'ZONE':/structure/.test(obj.style.token)?'STRUCTURE':'LEVEL');
  return [`${name} ${chipPrice(obj.points[0].price)}`];
}



