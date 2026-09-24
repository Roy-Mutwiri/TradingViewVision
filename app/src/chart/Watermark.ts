import type {ISeriesPrimitive,IPrimitivePaneRenderer,SeriesAttachedParameter,Time,SeriesType} from 'lightweight-charts';
import type {StreamConfig} from '../stream/types';
type Target=Parameters<IPrimitivePaneRenderer['draw']>[0];

export class Watermark implements ISeriesPrimitive<Time> {
  private request=()=>{};
  constructor(private config:StreamConfig) {}
  attached({requestUpdate}:SeriesAttachedParameter<Time,SeriesType>){this.request=requestUpdate;}
  update(config:StreamConfig){this.config=config;this.request();}
  private renderer:IPrimitivePaneRenderer={draw:()=>{},drawBackground:(target:Target)=>{
    target.useMediaCoordinateSpace(({context:ctx,mediaSize:{width,height}})=>{
      const {watermark:mark,brand}=this.config;
      ctx.save();ctx.fillStyle='#c8ab70';ctx.textBaseline='middle';
      if(mark.enabled&&mark.text){
        ctx.font='700 100px Inter, system-ui, sans-serif';
        const measure=ctx.measureText(mark.text);
        const glyphHeight=measure.actualBoundingBoxAscent+measure.actualBoundingBoxDescent;
        const size=height*mark.scale*100/Math.max(1,glyphHeight);
        ctx.font=`700 ${size}px Inter, system-ui, sans-serif`;ctx.letterSpacing=`${size*.08}px`;ctx.globalAlpha=mark.position==='tiled'?.03:.03;
        ctx.textAlign='center';
        if(mark.position==='tiled'){
          ctx.translate(width/2,height/2);ctx.rotate(-Math.PI/8);
          for(let y=-height;y<=height;y+=size*1.7)for(let x=-width;x<=width;x+=size*mark.text.length*.9)ctx.fillText(mark.text,x,y);
        }else if(mark.position==='bottom_right'){
          ctx.textAlign='right';ctx.fillText(mark.text,width-24,height-size*.65,width*.92);
        }else {
          ctx.textBaseline='alphabetic';
          const bounds=ctx.measureText(mark.text);
          ctx.fillText(mark.text,width/2,height/2+(bounds.actualBoundingBoxAscent-bounds.actualBoundingBoxDescent)/2,width*.92);
        }
      }
      ctx.restore();ctx.save();ctx.font='600 12px Consolas, monospace';ctx.fillStyle='#c8ab70';ctx.globalAlpha=.35;ctx.textBaseline='bottom';ctx.textAlign='right';
      const handle=brand.handle.trim();ctx.fillText(handle.startsWith('@')?handle:`@${handle}`,width-18,height-16);ctx.restore();
    });
  }};
  private views=[{zOrder:()=> 'normal' as const,renderer:()=>this.renderer}];
  paneViews(){return this.views;}
}
