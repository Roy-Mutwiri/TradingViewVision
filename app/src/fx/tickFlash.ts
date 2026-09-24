/** Display-only direction feedback. No timers, layout changes or engine work. */
export function tickDirection(previous:number|null,current:number):'up'|'down'|null{
  return previous==null||current===previous?null:current>previous?'up':'down';
}
export function flashPrice(element:HTMLElement,direction:'up'|'down',theme:'dark'|'light'):Animation{
  const color=direction==='up'?'#53d4b6':'#f18b91';
  return element.animate([{color},{color,offset:.8},{color:theme==='dark'?'#edf0f6':'#182230'}],{duration:120,easing:'linear'});
}
