export const nbsp='\u00a0';
const price2=new Intl.NumberFormat('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const live3=new Intl.NumberFormat('en-US',{minimumFractionDigits:3,maximumFractionDigits:3});
const whole=new Intl.NumberFormat('en-US',{maximumFractionDigits:0});
export const fmt={
  price:(v:number|null|undefined)=>Number.isFinite(Number(v))?price2.format(Number(v)):'--',
  live:(v:number|null|undefined)=>Number.isFinite(Number(v))?live3.format(Number(v)):'--',
  axis:(v:number)=>whole.format(v),
  delta:(v:number|null|undefined)=>{if(!Number.isFinite(Number(v)))return '--';const n=Number(v);return `${n<0?'−':'+'}${Math.abs(n).toFixed(2)}`;},
  r:(v:number|null|undefined)=>{if(!Number.isFinite(Number(v)))return '--';const n=Number(v);return `${n<0?'−':'+'}${Math.abs(n).toFixed(2)}R`;},
  int:(v:number|null|undefined)=>Number.isFinite(Number(v))?new Intl.NumberFormat('en-US',{maximumFractionDigits:0}).format(Number(v)):'--',
  one:(v:number|null|undefined)=>Number.isFinite(Number(v))?Number(v).toFixed(1):'--',
  time:(ms:number|null|undefined)=>Number.isFinite(Number(ms))?new Date(Number(ms)).toISOString().slice(11,16):'--:--',
  utcTime:(ms:number|null|undefined)=>Number.isFinite(Number(ms))?new Date(Number(ms)).toISOString().slice(11,19):'--:--:--',
  range:(lo:number|null|undefined,hi:number|null|undefined)=>{if(!Number.isFinite(Number(lo))||!Number.isFinite(Number(hi)))return '--';return Math.abs(Number(lo)-Number(hi))<0.005?price2.format(Number(lo)):`${price2.format(Number(lo))} – ${price2.format(Number(hi))}`;},
  usd:(v:number|null|undefined)=>{if(!Number.isFinite(Number(v)))return '--';const n=Number(v);return `${n<0?'−':'+'}${Math.abs(n).toFixed(2)}`;},
  spread:(brokerPoints:number|null|undefined)=>Number.isFinite(Number(brokerPoints))?(Number(brokerPoints)/1000).toFixed(2):'--',
};
export function liveParts(v:number|null|undefined){const s=fmt.live(v);const i=s.slice(0,-1),d=s.slice(-1);return {main:i,last:d};}
