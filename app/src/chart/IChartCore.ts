/** UTC milliseconds everywhere outside the chart vendor boundary. */
import type { Bar, DrawObject } from '../net/protocol';
import type { SessionClosure } from '../net/chart';
import type { Decision } from '../net/chart';
export type Timeframe = Bar['tf'];
export type ChartDensity = 'clean'|'analyst'|'notebook';
export interface ChartOpts { theme: 'dark' | 'light'; visibleBars?: number; density?: ChartDensity; }
export interface ChartEvents {
  barclose: Bar;
  range: {from: number; to: number} | null;
  resize: {width: number; height: number};
  crosshair: {t_ms: number | null; bar: Bar | null};
}
export interface IChartCore {
  mount(el: HTMLElement, opts: ChartOpts): Promise<void>;
  destroy(): void;
  setSymbol(symbol: string, tf: Timeframe): Promise<void>;
  applyBars(bars: Bar[]): void;
  updateBar(bar: Bar): void;
  priceToY(price: number): number | null;
  timeToX(tMs: number): number | null;
  visibleRange(): {from: number; to: number} | null;
  setVisibleRange(from: number, to: number): void;
  setTheme(theme: 'dark' | 'light'): void;
  setDensity(density: ChartDensity): void;
  setStream(config:import('../stream/types').StreamConfig): void;
  setLiving(config:import('../living/types').LivingConfig): void;
  setDecisions(decisions:Decision[]):void;
  sessionAt(now:number,connected:boolean):void;
  setSessions(closures: SessionClosure[]): void;
  applyDrawObjects(objects: DrawObject[], language?: string): void;
  setBarColors(colors: {t_ms:number;token:string}[]): void;
  on<K extends keyof ChartEvents>(event: K, cb: (value: ChartEvents[K]) => void): () => void;
}

