import {useEffect,useMemo,useRef,useState} from 'react';
import type {CSSProperties} from 'react';
import type {AnalysisSlide} from '../analysisSlides';
import {rotateAnalysisSlides} from '../analysisSlides';
import type {UIMode} from '../auth/Studio';

const dwellMs=6000;
const interruptDwellMs=10000;

export function AnalysisSlides({slides,mode}:{slides:AnalysisSlide[];mode:UIMode}){
  const slideTypes=slides.map(slide=>slide.type).join('|');
  const sequenceTypes=useMemo(()=>rotateAnalysisSlides(slides).map(slide=>slide.type),[slideTypes]);
  const [index,setIndex]=useState(0);
  const [pinned,setPinned]=useState(false);
  const [pulse,setPulse]=useState(false);
  const lastInterrupt=useRef(0);
  const lastInterruptKey=useRef<string>('');
  const currentType=sequenceTypes[index%Math.max(1,sequenceTypes.length)]??slides[0]?.type;
  const current=slides.find(slide=>slide.type===currentType)??slides[0];

  useEffect(()=>{
    if(!sequenceTypes.length){setIndex(0);return;}
    if(index>=sequenceTypes.length)setIndex(0);
  },[sequenceTypes.length,index]);

  useEffect(()=>{
    if(!sequenceTypes.length||pinned)return;
    const timer=window.setInterval(()=>setIndex(value=>(value+1)%sequenceTypes.length),dwellMs);
    return()=>window.clearInterval(timer);
  },[sequenceTypes.length,pinned]);

  useEffect(()=>{
    const interrupt=slides.find(slide=>slide.interruptKey&&slide.interruptKey!==lastInterruptKey.current);
    if(!interrupt)return;
    const now=Date.now();
    const isCall=interrupt.type==='CALL';
    if(!isCall&&now-lastInterrupt.current<20000)return;
    const target=sequenceTypes.findIndex(type=>type===interrupt.type);
    if(target>=0){setIndex(target);setPulse(true);window.setTimeout(()=>setPulse(false),400);}
    if(interrupt.interruptKey?.startsWith('DRY:')){
      window.dispatchEvent(new CustomEvent('oracle:analysis-worklog',{detail:{key:interrupt.interruptKey,label:interrupt.content,at_ms:Date.now()}}));
    }
    lastInterrupt.current=now;
    lastInterruptKey.current=interrupt.interruptKey??interrupt.key;
  },[slides,sequenceTypes]);

  useEffect(()=>{
    const key=(event:KeyboardEvent)=>{
      if(event.target instanceof HTMLInputElement||event.target instanceof HTMLTextAreaElement)return;
      if(event.key==='p'||event.key==='P'){if(mode==='operator'){event.preventDefault();setPinned(value=>!value);}return;}
      if(event.key==='Escape'){if(mode==='operator'){event.preventDefault();setPinned(false);}return;}
      if(mode==='operator'&&/^[1-9]$/.test(event.key)){const value=Number(event.key)-1;if(value<sequenceTypes.length){event.preventDefault();setIndex(value);setPinned(true);}}
    };
    window.addEventListener('keydown',key);
    return()=>window.removeEventListener('keydown',key);
  },[mode,sequenceTypes.length]);

  if(!current)return <div className="signal-state-banner analysis-slides" aria-live="polite"><span className="slide-type">THESIS</span><span className="slide-content">Analysis warming up</span></div>;
  const eligible=slides.length;
  const position=slides.findIndex(slide=>slide.type===current.type)+1;
  return <div className={`signal-state-banner analysis-slides ${pulse?'is-interrupt':''}`} aria-live="polite" data-slide-type={current.type} style={{'--slide-dwell':`${current.interruptKey?interruptDwellMs:dwellMs}ms`} as CSSProperties}>
    <span className="slide-type">{current.type}</span>
    <span className="slide-content">{current.content}</span>
    {mode==='operator'&&pinned&&<span className="slide-pinned">PINNED</span>}
    <span className="slide-progress" aria-hidden="true"/>
    <span className="slide-dots" aria-hidden="true">{slides.slice(0,9).map((slide,i)=><i key={slide.type} className={slide.type===current.type?'active':''}/>)}<b>{Math.max(1,position)}/{Math.max(1,eligible)}</b></span>
  </div>;
}
