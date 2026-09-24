/* Generated from engine/oracle/transport/chart.py. Do not edit. */

export type OracleChart = ChartFrame | ChartDebug | BarCorrection | TickQuote;
export type TMs = number;
export type Token = string;
export type BarColors = BarColor[];
export type BarDurationMs = number;
export type CalendarDetail = string;
export type Action = "CREATE" | "UPDATE" | "PROMOTE" | "DISCARD";
export type ConfirmedId = string | null;
export type Criterion = string | null;
export type Fidelity = "TICK" | "M1" | "BAR";
export type Geometry = FVGGeometry | OBGeometry | LiquidityGeometry;
export type AtrAtCreation = number;
export type Ce = number;
export type ConstituentIds = string[];
export type CreatedIdx = number;
export type CreatedMs = number;
export type Direction = "BULLISH" | "BEARISH";
export type FvgMinAtr = number;
export type GapAdjacent = boolean;
export type PriceHi = number;
export type PriceLo = number;
export type SchemaVersion = 3;
export type Size = number;
export type SourceBars = number[];
export type SourceObjectIds = string[];
export type Symbol = "XAUUSD";
export type TStartMs = number;
export type Tf = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type AtrAtCreation1 = number;
export type Boundary = "body_to_wick" | "full_range" | "body_only";
export type Ce1 = number;
export type ConstituentIds1 = string[];
export type CreatedIdx1 = number;
export type CreatedMs1 = number;
export type Direction1 = "BULLISH" | "BEARISH";
export type DisplacementAtr = number;
export type FvgIds = string[];
export type LegStartIdx = number;
export type OriginIdx = number;
export type PriceHi1 = number;
export type PriceLo1 = number;
export type SchemaVersion1 = 1;
export type Size1 = number;
export type SourceBars1 = number[];
export type SourceObjectIds1 = string[];
export type Symbol1 = string;
export type TStartMs1 = number;
export type Tf1 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type AtrAtCreation2 = number;
export type Ce2 = number;
export type CreatedMs2 = number;
export type Direction2 = "BULLISH" | "BEARISH";
export type Level = number;
export type Name = string;
export type PriceHi2 = number;
export type PriceLo2 = number;
export type SchemaVersion2 = 1;
export type Side = "HIGH" | "LOW";
export type Size2 = 0;
export type SourceBars2 = number[];
export type SourceObjectIds2 = string[];
export type TStartMs2 = number;
export type Tf2 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Kind = "FVG" | "OB" | "POOL" | "SWEEP";
export type Criterion1 = string;
export type Passed = boolean;
export type PriceA = number;
export type PriceB = number;
export type Threshold = number;
export type Unit = "pts" | "ATR" | "R";
export type Value = number;
export type ObjectId = string;
export type Reason = ("INVALIDATED" | "SUPERSEDED" | "MERGED" | "FAILED_CRITERIA" | "STALE" | "DATA_GAP") | null;
export type Seq = number;
export type SourceBars3 = number[];
export type SourceObjectIds3 = string[];
export type TBrokerMs = number;
export type TUtcMs = number;
export type Tf3 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type UnionId = string | null;
export type CandidateDecisions = Decision[];
export type CandidateWorklog = Decision[];
export type ChartDensity = "clean" | "analyst" | "notebook";
export type EndMs = number;
export type Recurring = boolean;
export type StartMs = number;
export type Closures = SessionClosure[];
export type IndicatorEnabled = boolean;
export type Kind1 = "snapshot" | "update" | "correction" | "status" | "clock_refined";
export type Language = string;
export type Id = string;
export type Named = boolean;
export type ScopeKey = string | null;
export type State = "FRESH" | "TOUCHED" | "SWEPT" | "BROKEN";
export type Strength = number;
export type SweepEventId = string | null;
export type SweptMs = number | null;
export type TouchBars = number[];
export type TouchTimes = number[];
export type LiquidityPools = Pool[];
export type LiquidityWeeklyOpen = number | null;
export type NextCloseMs = number | null;
export type NowMs = number;
export type In = string;
export type Loop = string | null;
export type Confidence = number;
export type Digits = 2 | 3;
export type Id1 = string;
export type Layer = "L2" | "L3";
export type ObjectHash = string;
/**
 * @minItems 1
 */
export type Points = [Point, ...Point[]];
export type Price = number;
export type TMs1 = number;
export type Priority = number;
export type Reason1 = string;
export type Shape = "ZONE" | "LINE" | "RAY" | "LABEL" | "ARROW" | "FIB" | "PATH" | "LADDER" | "GLYPH";
/**
 * @minItems 1
 */
export type SourceBars4 = [number, ...number[]];
export type State1 = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type Token1 = string;
export type JsonValue = unknown;
export type TextKey = string;
export type TtlMs = number;
export type Z = number;
export type Confidence1 = number;
export type Confirmed = boolean;
export type Digits1 = 2 | 3;
export type Direction3 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Id2 = string;
export type Indicator = "utbot";
export type Layer1 = "L2" | "L3";
export type ObjectHash1 = string;
/**
 * @minItems 1
 */
export type Points1 = [Point, ...Point[]];
export type Priority1 = number;
export type Reason2 = string;
export type Shape1 = "ZONE" | "LINE" | "RAY" | "LABEL" | "ARROW" | "FIB" | "PATH" | "LADDER" | "GLYPH";
/**
 * @minItems 1
 */
export type SourceBars5 = [number, ...number[]];
export type State2 = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type Symbol2 = "XAUUSD";
export type TOpenMs = number;
export type TextKey1 = string;
export type Tf4 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type TtlMs1 = number;
export type Warmup = boolean;
export type Z1 = number;
export type Objects = (DrawObject | UTBotDrawObject)[];
export type Detail = string;
export type SpreadPoints = number;
export type StalenessMs = number;
export type State3 = "OK" | "STALE" | "GAPPED" | "WIDE_SPREAD" | "HALTED" | "NO_DATA" | "CALENDAR_PENDING";
export type Ask = number;
export type Bid = number;
export type Source = string;
export type Symbol3 = "XAUUSD";
export type TMs2 = number;
export type RefinementPending = string;
export type ResolvedSymbol = string;
export type C = number;
export type ClockConfidence = "MEASURED" | "DERIVED" | "ASSUMED";
export type Complete = boolean;
export type Digits2 = 2 | 3;
export type H = number;
export type Id3 = string;
export type L = number;
export type O = number;
export type ObjectHash2 = string;
export type Source1 = "mt5" | "twelve_data" | "synthetic";
export type Symbol4 = "XAUUSD";
export type TOpenMs1 = number;
export type Tf5 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type TickVolume = number;
export type Bars = Bar[];
export type Clockversion = number;
export type Symbol5 = "XAUUSD";
export type Tf6 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type AtrAtBreak = number;
export type BreakBarIdx = number;
export type BreakClose = number;
export type BrokenSwingId = string;
export type BrokenSwingIdx = number;
export type Direction4 = "UP" | "DOWN";
export type Id4 = string;
export type IsMss = boolean;
export type Kind2 = "BOS" | "CHoCH";
export type Level1 = number;
export type SourceBars6 = number[];
export type SourceObjectIds4 = string[];
export type SweepEventId1 = string | null;
export type TMs3 = number;
export type Timeframe = string;
export type TrendAfter = "BULLISH" | "BEARISH" | "UNDEFINED";
export type TrendBefore = "BULLISH" | "BEARISH" | "UNDEFINED";
export type MajorHigh = number | null;
export type MajorHighId = string | null;
export type MajorHighIdx = number | null;
export type MajorLow = number | null;
export type MajorLowId = string | null;
export type MajorLowIdx = number | null;
export type ProtectedHigh = number | null;
export type ProtectedLow = number | null;
export type SchemaVersion3 = 2;
export type SeenPivots = string[];
export type Trend = "BULLISH" | "BEARISH" | "UNDEFINED";
export type TrendSinceMs = number | null;
export type SwitchMs = number;
export type Symbol6 = "XAUUSD";
export type Tf7 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Action1 =
  "MARKED" | "CE_LOST" | "INVERTED" | "INVALID" | "MERGED" | "MERGE_REJECTED" | "REINVERSION_ATTEMPT";
export type AtMs = number;
export type Id5 = string;
export type Label = string;
export type ObjectId1 = string;
export type SourceBars7 = number[];
export type SourceObjectIds5 = string[];
export type Tf8 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Worklog = WorkDecision[];
export type ClockConfidence1 = string;
export type ClockVersion = number;
export type OffsetS = number;
export type TBrokerMs1 = number;
export type TOpenMs2 = number;
export type Bars1 = DebugBar[];
export type Checked = number;
export type Corrections = number;
export type Detail1 = string;
export type Code = string;
export type Message = string;
export type Recoverable = boolean;
export type LastTickMs = number;
export type MissingRanges = {
  [k: string]: number;
}[];
export type ResolvedSymbol1 = string;
export type SpreadPoints1 = number;
export type SwitchMs1 = number;
export type Symbol7 = "XAUUSD";
export type Tf9 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Digits3 = 2 | 3;
export type NowMs1 = number;
export type ReceivedMs = number;
export type SpreadPoints2 = number;

export interface ChartFrame {
  bar_colors?: BarColors;
  bar_duration_ms: BarDurationMs;
  book?: Book;
  calendar_detail?: CalendarDetail;
  candidate_decisions?: CandidateDecisions;
  candidate_status?: CandidateStatus;
  candidate_worklog?: CandidateWorklog;
  chart_density?: ChartDensity;
  closures?: Closures;
  indicator_enabled?: IndicatorEnabled;
  kind: Kind1;
  language?: Language;
  liquidity_pools?: LiquidityPools;
  liquidity_weekly_open?: LiquidityWeeklyOpen;
  next_close_ms?: NextCloseMs;
  now_ms: NowMs;
  objects?: Objects;
  quality: DataQuality;
  quote?: Quote | null;
  refinement_pending?: RefinementPending;
  resolved_symbol?: ResolvedSymbol;
  snapshot?: BarsSnapshot | null;
  structure_state?: StructureState | null;
  switch_ms?: SwitchMs;
  thesis?: Thesis;
  update?: BarUpdate | null;
  worklog?: Worklog;
}
export interface BarColor {
  t_ms: TMs;
  token: Token;
}
export interface Book {
  [k: string]: unknown;
}
export interface Decision {
  action: Action;
  confirmed_id?: ConfirmedId;
  criterion?: Criterion;
  fidelity: Fidelity;
  geometry: Geometry;
  kind: Kind;
  measurement?: Measurement | null;
  object_id: ObjectId;
  reason?: Reason;
  seq: Seq;
  source_bars: SourceBars3;
  source_object_ids: SourceObjectIds3;
  t_broker_ms: TBrokerMs;
  t_utc_ms: TUtcMs;
  tf: Tf3;
  union_id?: UnionId;
}
export interface FVGGeometry {
  atr_at_creation: AtrAtCreation;
  ce: Ce;
  constituent_ids?: ConstituentIds;
  created_idx: CreatedIdx;
  created_ms: CreatedMs;
  direction: Direction;
  fvg_min_atr: FvgMinAtr;
  gap_adjacent: GapAdjacent;
  price_hi: PriceHi;
  price_lo: PriceLo;
  schema_version?: SchemaVersion;
  size: Size;
  source_bars: SourceBars;
  source_object_ids: SourceObjectIds;
  symbol: Symbol;
  t_start_ms: TStartMs;
  tf: Tf;
}
export interface OBGeometry {
  atr_at_creation: AtrAtCreation1;
  boundary: Boundary;
  ce: Ce1;
  constituent_ids?: ConstituentIds1;
  created_idx: CreatedIdx1;
  created_ms: CreatedMs1;
  direction: Direction1;
  displacement_atr: DisplacementAtr;
  fvg_ids: FvgIds;
  leg_start_idx: LegStartIdx;
  origin_idx: OriginIdx;
  price_hi: PriceHi1;
  price_lo: PriceLo1;
  schema_version?: SchemaVersion1;
  size: Size1;
  source_bars: SourceBars1;
  source_object_ids: SourceObjectIds1;
  symbol?: Symbol1;
  t_start_ms: TStartMs1;
  tf: Tf1;
}
export interface LiquidityGeometry {
  atr_at_creation: AtrAtCreation2;
  ce: Ce2;
  created_ms: CreatedMs2;
  direction: Direction2;
  level: Level;
  name: Name;
  price_hi: PriceHi2;
  price_lo: PriceLo2;
  schema_version?: SchemaVersion2;
  side: Side;
  size?: Size2;
  source_bars: SourceBars2;
  source_object_ids: SourceObjectIds2;
  t_start_ms: TStartMs2;
  tf: Tf2;
}
export interface Measurement {
  criterion: Criterion1;
  passed: Passed;
  price_a: PriceA;
  price_b: PriceB;
  threshold: Threshold;
  unit: Unit;
  value: Value;
}
export interface CandidateStatus {
  [k: string]: unknown;
}
export interface SessionClosure {
  end_ms: EndMs;
  recurring: Recurring;
  start_ms: StartMs;
}
export interface Pool {
  geometry: LiquidityGeometry;
  id: Id;
  named?: Named;
  scope_key?: ScopeKey;
  state?: State;
  strength: Strength;
  sweep_event_id?: SweepEventId;
  swept_ms?: SweptMs;
  touch_bars?: TouchBars;
  touch_times?: TouchTimes;
}
export interface DrawObject {
  anim: Animation;
  confidence: Confidence;
  digits?: Digits;
  id?: Id1;
  layer: Layer;
  object_hash?: ObjectHash;
  points: Points;
  priority: Priority;
  reason: Reason1;
  shape: Shape;
  source_bars: SourceBars4;
  state: State1;
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
  price: Price;
  t_ms: TMs1;
}
export interface Style {
  token: Token1;
}
export interface TextArgs {
  [k: string]: JsonValue;
}
export interface UTBotDrawObject {
  anim: Animation;
  confidence: Confidence1;
  confirmed?: Confirmed;
  digits?: Digits1;
  direction: Direction3;
  id?: Id2;
  indicator?: Indicator;
  layer: Layer1;
  object_hash?: ObjectHash1;
  points: Points1;
  priority: Priority1;
  reason: Reason2;
  shape: Shape1;
  source_bars: SourceBars5;
  state: State2;
  style: Style;
  symbol?: Symbol2;
  t_open_ms: TOpenMs;
  text_args: TextArgs1;
  text_key: TextKey1;
  tf: Tf4;
  ttl_ms: TtlMs1;
  warmup?: Warmup;
  z: Z1;
}
export interface TextArgs1 {
  [k: string]: JsonValue;
}
export interface DataQuality {
  detail: Detail;
  spread_points: SpreadPoints;
  staleness_ms: StalenessMs;
  state: State3;
}
export interface Quote {
  ask: Ask;
  bid: Bid;
  source: Source;
  symbol: Symbol3;
  t_ms: TMs2;
}
export interface BarsSnapshot {
  bars: Bars;
  clockVersion: Clockversion;
  symbol?: Symbol5;
  tf: Tf6;
}
export interface Bar {
  c: C;
  clock_confidence?: ClockConfidence;
  complete: Complete;
  digits?: Digits2;
  h: H;
  id?: Id3;
  l: L;
  o: O;
  object_hash?: ObjectHash2;
  source: Source1;
  symbol?: Symbol4;
  t_open_ms: TOpenMs1;
  tf: Tf5;
  tick_volume: TickVolume;
}
export interface StructureState {
  last_event?: StructureEvent | null;
  major_high?: MajorHigh;
  major_high_id?: MajorHighId;
  major_high_idx?: MajorHighIdx;
  major_low?: MajorLow;
  major_low_id?: MajorLowId;
  major_low_idx?: MajorLowIdx;
  protected_high?: ProtectedHigh;
  protected_low?: ProtectedLow;
  schema_version?: SchemaVersion3;
  seen_pivots?: SeenPivots;
  trend?: Trend;
  trend_since_ms?: TrendSinceMs;
}
export interface StructureEvent {
  atr_at_break: AtrAtBreak;
  break_bar_idx: BreakBarIdx;
  break_close: BreakClose;
  broken_swing_id: BrokenSwingId;
  broken_swing_idx: BrokenSwingIdx;
  direction: Direction4;
  id: Id4;
  is_mss?: IsMss;
  kind: Kind2;
  level: Level1;
  source_bars: SourceBars6;
  source_object_ids: SourceObjectIds4;
  sweep_event_id?: SweepEventId1;
  t_ms: TMs3;
  timeframe: Timeframe;
  trend_after: TrendAfter;
  trend_before: TrendBefore;
}
export interface Thesis {
  [k: string]: unknown;
}
export interface BarUpdate {
  bar: Bar;
  symbol?: Symbol6;
  tf: Tf7;
}
export interface WorkDecision {
  action: Action1;
  at_ms: AtMs;
  id: Id5;
  label: Label;
  object_id: ObjectId1;
  source_bars: SourceBars7;
  source_object_ids: SourceObjectIds5;
  tf: Tf8;
}
export interface ChartDebug {
  bars: Bars1;
  checked: Checked;
  corrections: Corrections;
  detail: Detail1;
  error?: EngineFault | null;
  gateway?: Gateway;
  indicator?: Indicator1;
  last_tick_ms: LastTickMs;
  missing_ranges?: MissingRanges;
  resolved_symbol: ResolvedSymbol1;
  spread_points: SpreadPoints1;
  switch_ms?: SwitchMs1;
}
export interface DebugBar {
  clock_confidence?: ClockConfidence1;
  clock_version: ClockVersion;
  offset_s: OffsetS;
  t_broker_ms: TBrokerMs1;
  t_open_ms: TOpenMs2;
}
export interface EngineFault {
  code: Code;
  detail: Detail2;
  message: Message;
  recoverable: Recoverable;
}
export interface Detail2 {
  [k: string]: JsonValue;
}
export interface Gateway {
  [k: string]: unknown;
}
export interface Indicator1 {
  [k: string]: unknown;
}
export interface BarCorrection {
  bar: Bar;
  symbol?: Symbol7;
  tf: Tf9;
}
export interface TickQuote {
  digits: Digits3;
  now_ms: NowMs1;
  quote: Quote;
  received_ms: ReceivedMs;
  spread_points: SpreadPoints2;
}
