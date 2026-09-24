/* Generated from engine/oracle/director/contracts.py. Do not edit. */

export type Answer = string;
export type EndsMs = number;
export type Handle = string;
export type Id = string;
export type Kind = "ANSWER" | "BIAS" | "LEVELS" | "SCORE" | "ZONE" | "THANKS";
export type Question = string;
export type AtMs = number;
export type EndsMs1 = number;
export type Handle1 = string;
export type Text = string;
export type CountdownMs = number;
export type EndsMs2 = number;
export type Headline = string;
export type Id1 = string;
export type Kind1 = "CANDLE_CLOSE" | "LEVEL_APPROACH" | "EVENT_COUNTDOWN" | "SETUP_TRIGGER" | "STREAK" | "SESSION_OPEN";
export type Outcome = string | null;
export type Priority = number;
export type RingPct = number;
export type Sub = string;
export type Language = string;
export type Label = string;
export type Price = number;
export type Levels = Level[];
export type In = string;
export type Loop = string | null;
export type Confidence = number;
export type Digits = 2 | 3;
export type Id2 = string;
export type Layer = "L2" | "L3";
export type ObjectHash = string;
/**
 * @minItems 1
 */
export type Points = [Point, ...Point[]];
export type Price1 = number;
export type TMs = number;
export type Priority1 = number;
export type Reason = string;
export type Shape = "ZONE" | "LINE" | "RAY" | "LABEL" | "ARROW" | "FIB" | "PATH" | "LADDER" | "GLYPH";
/**
 * @minItems 1
 */
export type SourceBars = [number, ...number[]];
export type State = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type Token = string;
export type JsonValue = unknown;
export type TextKey = string;
export type TtlMs = number;
export type Z = number;
export type Marks = DrawObject[];
export type NowMs = number;
export type Rehearsal = boolean;
export type Active = number;
export type Ambiguous = number;
export type Cancelled = number;
export type Expectancy = number | null;
export type GapSkipped = number;
export type HitRate = number | null;
export type Losses = number;
export type NeverTriggered = number;
export type Pending = number;
export type Produced = number;
export type Resolved = number;
export type Scratch = number;
export type Triggered = number;
export type VoidData = number;
export type Wins = number;
export type Ambiguous1 = boolean;
export type ClockVersion = number;
export type CreatedMs = number;
export type CreatedTradingDay = string;
export type DayBoundary = string;
export type Direction = "LONG" | "SHORT";
export type EntryHi = number;
export type EntryLo = number;
export type EntryRef = number | null;
export type EvalFromMs = number;
export type EvalToMs = number;
export type ExpiresMs = number;
export type GapSkipped1 = boolean;
export type Grade = "A" | "B" | "C";
export type GradeNotes = string[];
export type Id3 = string;
export type InOte = boolean | null;
export type Invalidation = number;
export type Kind2 = "SETUP" | "STRUCTURE";
export type Mae = number | null;
export type Mfe = number | null;
export type ObId = string | null;
export type Reason1 = string;
export type ReasonChain = string[];
export type ResolvedMs = number | null;
export type ResolvedTradingDay = string | null;
export type SourceBars1 = number[];
export type State1 = "PENDING" | "ACTIVE" | "WIN" | "LOSS" | "SCRATCH" | "NEVER_TRIGGERED" | "VOID_DATA" | "CANCELLED";
export type StateHash = string;
export type StructureEventId = string | null;
export type Symbol = string;
export type Target = number;
export type TargetPoolId = string | null;
export type Timeframe = string | null;
export type Tp2 = number | null;
export type TriggerPrice = number | null;
export type CancellationReason = string | null;
export type Cancelled1 = boolean;
export type PriorBidClose = number | null;
export type ResolutionReason = string | null;
export type Rows = CallRow[];
export type TodayLabel = string;
export type TodayTradingDay = string;
export type Session = string;
export type Shout = string | null;
export type Supporters = string[];
export type Zoom = {
  [k: string]: number;
} | null;

export interface RetentionFrame {
  bias?: Bias;
  card?: Card | null;
  comment?: AudienceComment | null;
  hook: Hook;
  language?: Language;
  levels?: Levels;
  marks?: Marks;
  now_ms: NowMs;
  rehearsal?: Rehearsal;
  scoreboard?: CallBoard;
  session?: Session;
  shout?: Shout;
  supporters?: Supporters;
  zoom?: Zoom;
}
export interface Bias {
  [k: string]: string;
}
export interface Card {
  answer: Answer;
  ends_ms: EndsMs;
  handle: Handle;
  id: Id;
  kind: Kind;
  question: Question;
}
export interface AudienceComment {
  at_ms: AtMs;
  ends_ms: EndsMs1;
  handle: Handle1;
  text: Text;
}
export interface Hook {
  countdown_ms: CountdownMs;
  ends_ms: EndsMs2;
  headline: Headline;
  id: Id1;
  kind: Kind1;
  outcome?: Outcome;
  priority: Priority;
  ring_pct: RingPct;
  sub: Sub;
}
export interface Level {
  label: Label;
  price: Price;
}
export interface DrawObject {
  anim: Animation;
  confidence: Confidence;
  digits?: Digits;
  id?: Id2;
  layer: Layer;
  object_hash?: ObjectHash;
  points: Points;
  priority: Priority1;
  reason: Reason;
  shape: Shape;
  source_bars: SourceBars;
  state: State;
  style: Style;
  text_args: TextArgs;
  text_key: TextKey;
  ttl_ms: TtlMs;
  z: Z;
}
export interface Animation {
  in_: In;
  loop: Loop;
}
export interface Point {
  price: Price1;
  t_ms: TMs;
}
export interface Style {
  token: Token;
}
export interface TextArgs {
  [k: string]: JsonValue;
}
export interface CallBoard {
  all_time?: CallStats;
  last_20?: CallStats1;
  rows?: Rows;
  today?: CallStats2;
  today_label?: TodayLabel;
  today_trading_day?: TodayTradingDay;
}
export interface CallStats {
  active?: Active;
  ambiguous?: Ambiguous;
  cancelled?: Cancelled;
  expectancy?: Expectancy;
  gap_skipped?: GapSkipped;
  hit_rate?: HitRate;
  losses?: Losses;
  never_triggered?: NeverTriggered;
  pending?: Pending;
  produced?: Produced;
  resolved?: Resolved;
  scratch?: Scratch;
  triggered?: Triggered;
  void_data?: VoidData;
  wins?: Wins;
}
export interface CallStats1 {
  active?: Active;
  ambiguous?: Ambiguous;
  cancelled?: Cancelled;
  expectancy?: Expectancy;
  gap_skipped?: GapSkipped;
  hit_rate?: HitRate;
  losses?: Losses;
  never_triggered?: NeverTriggered;
  pending?: Pending;
  produced?: Produced;
  resolved?: Resolved;
  scratch?: Scratch;
  triggered?: Triggered;
  void_data?: VoidData;
  wins?: Wins;
}
export interface CallRow {
  ambiguous?: Ambiguous1;
  call: Call;
  cancellation_reason?: CancellationReason;
  cancelled?: Cancelled1;
  prior_bid_close?: PriorBidClose;
  resolution_reason?: ResolutionReason;
}
export interface Call {
  clock_version: ClockVersion;
  created_ms: CreatedMs;
  created_trading_day?: CreatedTradingDay;
  day_boundary?: DayBoundary;
  direction: Direction;
  entry_hi: EntryHi;
  entry_lo: EntryLo;
  entry_ref?: EntryRef;
  eval_from_ms?: EvalFromMs;
  eval_to_ms?: EvalToMs;
  expires_ms: ExpiresMs;
  gap_skipped?: GapSkipped1;
  grade?: Grade;
  grade_notes?: GradeNotes;
  id?: Id3;
  in_ote?: InOte;
  invalidation: Invalidation;
  kind: Kind2;
  mae?: Mae;
  mfe?: Mfe;
  ob_id?: ObId;
  reason: Reason1;
  reason_chain?: ReasonChain;
  resolved_ms?: ResolvedMs;
  resolved_trading_day?: ResolvedTradingDay;
  source_bars?: SourceBars1;
  state?: State1;
  state_hash: StateHash;
  structure_event_id?: StructureEventId;
  symbol: Symbol;
  target: Target;
  target_pool_id?: TargetPoolId;
  timeframe?: Timeframe;
  tp2?: Tp2;
  trigger_price?: TriggerPrice;
}
export interface CallStats2 {
  active?: Active;
  ambiguous?: Ambiguous;
  cancelled?: Cancelled;
  expectancy?: Expectancy;
  gap_skipped?: GapSkipped;
  hit_rate?: HitRate;
  losses?: Losses;
  never_triggered?: NeverTriggered;
  pending?: Pending;
  produced?: Produced;
  resolved?: Resolved;
  scratch?: Scratch;
  triggered?: Triggered;
  void_data?: VoidData;
  wins?: Wins;
}
