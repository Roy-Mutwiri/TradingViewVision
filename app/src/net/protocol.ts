/* Generated from engine/oracle/models.py. Do not edit. */

export type In = string;
export type Loop = string | null;
export type C = number;
export type ClockConfidence = "MEASURED" | "DERIVED" | "ASSUMED";
export type Complete = boolean;
export type Digits = 2 | 3;
export type H = number;
export type Id = string;
export type L = number;
export type O = number;
export type ObjectHash = string;
export type Source = "mt5" | "twelve_data" | "synthetic";
export type Symbol = "XAUUSD";
export type TOpenMs = number;
export type Tf = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type TickVolume = number;
export type Deviation = number;
export type Confidence = number;
export type Direction = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Evidence = string[];
export type AlignmentScore = number;
export type Evidence1 = string[];
export type DurationMs = number;
export type Easing = "linear" | "ease_in_out" | "ease_out";
export type Kind = "PAN" | "ZOOM_TO_ZONE" | "FRAME_RANGE" | "TF_MORPH";
export type FromMs = number | null;
export type ObjectId = string | null;
export type PriceHi = number | null;
export type PriceLo = number | null;
export type Tf1 = ("M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1") | null;
export type ToMs = number | null;
export type BarsRecovered = number;
export type FromMs1 = number;
export type Symbol1 = "XAUUSD";
export type ToMs1 = number;
export type Detail = string;
export type SpreadPoints = number;
export type StalenessMs = number;
export type State = "OK" | "STALE" | "GAPPED" | "WIDE_SPREAD" | "HALTED" | "NO_DATA" | "CALENDAR_PENDING";
export type Confidence1 = number;
export type Digits1 = 2 | 3;
export type Id1 = string;
export type Layer = "L2" | "L3";
export type ObjectHash1 = string;
/**
 * @minItems 1
 */
export type Points = [Point, ...Point[]];
export type Price = number;
export type TMs = number;
export type Priority = number;
export type Reason = string;
export type Shape = "ZONE" | "LINE" | "RAY" | "LABEL" | "ARROW" | "FIB" | "PATH" | "LADDER" | "GLYPH";
/**
 * @minItems 1
 */
export type SourceBars = [number, ...number[]];
export type State1 = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type Token = string;
export type JsonValue = unknown;
export type TextKey = string;
export type TtlMs = number;
export type Z = number;
export type Add = DrawObject[];
export type AsOfMs = number;
export type Remove = string[];
export type Update = DrawObject[];
export type AtMs = number;
export type Kind1 = "PULSE" | "FLASH" | "TRACE";
export type ObjectId1 = string;
export type Headline = string;
export type Impact = number;
export type Kind2 = string;
export type Source1 = string;
export type TMs1 = number;
export type AsOfMs1 = number;
export type IntelConfidence = number;
export type MinutesToNextHighImpact = number | null;
export type RiskRegime = "RISK_ON" | "RISK_OFF" | "MIXED" | "EVENT_PENDING";
/**
 * @maxItems 3
 */
export type TopFacts = [] | [string] | [string, string] | [string, string, string];
export type ActiveSegment = string;
export type AsOfMs2 = number;
export type AtrPercentile = number;
export type BreakBarIdx = number;
export type BreakMode = "body" | "wick";
export type BrokenSwingId = string;
export type Confirmed = boolean;
export type Digits2 = 2 | 3;
export type Direction1 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Id2 = string;
export type Kind3 = "BOS" | "CHOCH" | "MSS";
export type ObjectHash2 = string;
export type Price1 = number;
export type TMs2 = number;
export type Tf2 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Events = StructureEvt[];
export type Killzone = string | null;
export type Price2 = number;
export type RangePosition = number;
/**
 * @minItems 1
 */
export type ContributingFactors = [string, ...string[]];
export type Grade = "A" | "B" | "C" | "D";
export type Score = number;
export type StateHash = string;
export type Digits3 = 2 | 3;
export type Direction2 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Id3 = string;
export type LevelKind = string;
export type LevelPrice = number;
export type ObjectHash3 = string;
export type Reclaimed = boolean;
export type SweepBarIdx = number;
export type TMs3 = number;
export type Sweeps = Sweep[];
export type Digits4 = 2 | 3;
export type Id4 = string;
export type Idx = number;
export type Kind4 = "HH" | "HL" | "LH" | "LL";
export type ObjectHash4 = string;
export type Price3 = number;
export type TMs4 = number;
export type Tf3 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Swings = Swing[];
export type Symbol2 = "XAUUSD";
export type TickSize = number;
export type Digits5 = 2 | 3;
export type Direction3 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type FillPct = number;
export type Id5 = string;
export type Kind5 = "OB" | "BREAKER" | "FVG" | "IFVG" | "LIQ_POOL" | "OTE" | "RANGE" | "GAP_FVG";
export type ObjectHash5 = string;
export type PriceHi1 = number;
export type PriceLo1 = number;
export type Reason1 = string;
export type Score1 = number;
/**
 * @minItems 1
 */
export type SourceBars1 = [number, ...number[]];
export type State2 = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type TEndMs = number;
export type TStartMs = number;
export type Tf4 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type Zones = Zone[];
export type Cues = HighlightCue[];
export type SegmentId = string;
export type Ask = number;
export type Bid = number;
export type Source2 = string;
export type Symbol3 = "XAUUSD";
export type TMs5 = number;
export type Digits6 = 2 | 3;
export type Direction4 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type ExpectedMoveAtr = number;
export type Id6 = string;
export type InvalidationPrice = number;
export type ObjectHash6 = string;
export type ProbSampleN = number;
export type Probability = number | null;
export type Rank = "PRIMARY" | "ALTERNATE" | "INVALIDATION";
/**
 * @minItems 1
 */
export type ReasonChain = [string, ...string[]];
export type ValidUntilMs = number;
/**
 * @minItems 1
 */
export type Waypoints = [Waypoint, ...Waypoint[]];
export type Kind6 = "ZONE_TAP" | "REACTION" | "TARGET";
export type Note = string;
export type Price4 = number;
export type Confidence2 = number;
export type Confirmed1 = boolean;
export type Digits7 = 2 | 3;
export type Direction5 = "BULLISH" | "BEARISH" | "NEUTRAL";
export type Id7 = string;
export type Indicator = "utbot";
export type Layer1 = "L2" | "L3";
export type ObjectHash7 = string;
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
export type SourceBars2 = [number, ...number[]];
export type State3 = "FRESH" | "TOUCHED" | "MITIGATED" | "BREAKER" | "INVALID";
export type Symbol4 = "XAUUSD";
export type TOpenMs1 = number;
export type TextKey1 = string;
export type Tf5 = "M1" | "M5" | "M15" | "M30" | "H1" | "H4" | "D1" | "W1" | "MN1";
export type TtlMs1 = number;
export type Warmup = boolean;
export type Z1 = number;
export type Payload1 =
  Bar | BarCorrection | Quote | DataQuality | DataGapHealed | MarketState | IntelSnapshot | PresentationBeat;
export type Sequence = number;
export type TMs6 = number;
export type Version = 1;

export interface OracleProtocol {
  Animation?: Animation;
  Bar?: Bar;
  BarCorrection?: BarCorrection;
  Bias?: Bias;
  BiasStack?: BiasStack;
  CameraMove?: CameraMove;
  CameraTarget?: CameraTarget;
  DataGapHealed?: DataGapHealed;
  DataQuality?: DataQuality;
  DrawObject?: DrawObject;
  DrawPlan?: DrawPlan;
  HighlightCue?: HighlightCue;
  IntelItem?: IntelItem;
  IntelSnapshot?: IntelSnapshot;
  JsonValue?: JsonValue;
  MarketState?: MarketState;
  Point?: Point;
  PresentationBeat?: PresentationBeat;
  Quote?: Quote;
  Scenario?: Scenario;
  SetupGrade?: SetupGrade;
  StructureEvt?: StructureEvt;
  Style?: Style;
  Sweep?: Sweep;
  Swing?: Swing;
  UTBotDrawObject?: UTBotDrawObject;
  Waypoint?: Waypoint;
  WireEvent?: WireEvent;
  Zone?: Zone;
}
export interface Animation {
  in_: In;
  loop: Loop;
}
export interface Bar {
  c: C;
  clock_confidence?: ClockConfidence;
  complete: Complete;
  digits?: Digits;
  h: H;
  id?: Id;
  l: L;
  o: O;
  object_hash?: ObjectHash;
  source: Source;
  symbol?: Symbol;
  t_open_ms: TOpenMs;
  tf: Tf;
  tick_volume: TickVolume;
}
export interface BarCorrection {
  corrected: Bar;
  deviation: Deviation;
  previous: Bar;
}
export interface Bias {
  confidence: Confidence;
  direction: Direction;
  evidence: Evidence;
}
export interface BiasStack {
  alignment_score: AlignmentScore;
  evidence: Evidence1;
  per_tf: PerTf;
}
export interface PerTf {
  [k: string]: Bias;
}
export interface CameraMove {
  duration_ms: DurationMs;
  easing: Easing;
  kind: Kind;
  target: CameraTarget;
}
export interface CameraTarget {
  from_ms?: FromMs;
  object_id?: ObjectId;
  price_hi?: PriceHi;
  price_lo?: PriceLo;
  tf?: Tf1;
  to_ms?: ToMs;
}
export interface DataGapHealed {
  bars_recovered: BarsRecovered;
  from_ms: FromMs1;
  symbol: Symbol1;
  to_ms: ToMs1;
}
export interface DataQuality {
  detail: Detail;
  spread_points: SpreadPoints;
  staleness_ms: StalenessMs;
  state: State;
}
export interface DrawObject {
  anim: Animation;
  confidence: Confidence1;
  digits?: Digits1;
  id?: Id1;
  layer: Layer;
  object_hash?: ObjectHash1;
  points: Points;
  priority: Priority;
  reason: Reason;
  shape: Shape;
  source_bars: SourceBars;
  state: State1;
  style: Style;
  text_args: TextArgs;
  text_key: TextKey;
  ttl_ms: TtlMs;
  z: Z;
}
export interface Point {
  price: Price;
  t_ms: TMs;
}
export interface Style {
  token: Token;
}
export interface TextArgs {
  [k: string]: JsonValue;
}
export interface DrawPlan {
  add: Add;
  as_of_ms: AsOfMs;
  remove: Remove;
  update: Update;
}
export interface HighlightCue {
  at_ms: AtMs;
  kind: Kind1;
  object_id: ObjectId1;
}
export interface IntelItem {
  headline: Headline;
  impact: Impact;
  kind: Kind2;
  payload: Payload;
  source: Source1;
  t_ms: TMs1;
}
export interface Payload {
  [k: string]: JsonValue;
}
export interface IntelSnapshot {
  as_of_ms: AsOfMs1;
  correlates: Correlates;
  intel_confidence: IntelConfidence;
  minutes_to_next_high_impact: MinutesToNextHighImpact;
  next_event: IntelItem | null;
  risk_regime: RiskRegime;
  top_facts: TopFacts;
}
export interface Correlates {
  [k: string]: number;
}
export interface MarketState {
  active_segment: ActiveSegment;
  as_of_ms: AsOfMs2;
  atr_percentile: AtrPercentile;
  bias: BiasStack;
  data_quality: DataQuality;
  events: Events;
  killzone: Killzone;
  price: Price2;
  range_position: RangePosition;
  setup: SetupGrade | null;
  state_hash?: StateHash;
  sweeps: Sweeps;
  swings: Swings;
  symbol: Symbol2;
  tick_size: TickSize;
  zones: Zones;
}
export interface StructureEvt {
  break_bar_idx: BreakBarIdx;
  break_mode?: BreakMode;
  broken_swing_id: BrokenSwingId;
  confirmed: Confirmed;
  digits?: Digits2;
  direction: Direction1;
  id?: Id2;
  kind: Kind3;
  object_hash?: ObjectHash2;
  price: Price1;
  t_ms: TMs2;
  tf: Tf2;
}
export interface SetupGrade {
  contributing_factors: ContributingFactors;
  grade: Grade;
  score: Score;
}
export interface Sweep {
  digits?: Digits3;
  direction: Direction2;
  id?: Id3;
  level_kind: LevelKind;
  level_price: LevelPrice;
  object_hash?: ObjectHash3;
  reclaimed: Reclaimed;
  sweep_bar_idx: SweepBarIdx;
  t_ms: TMs3;
}
export interface Swing {
  digits?: Digits4;
  id?: Id4;
  idx: Idx;
  kind: Kind4;
  object_hash?: ObjectHash4;
  price: Price3;
  t_ms: TMs4;
  tf: Tf3;
}
export interface Zone {
  digits?: Digits5;
  direction: Direction3;
  fill_pct: FillPct;
  id?: Id5;
  kind: Kind5;
  object_hash?: ObjectHash5;
  price_hi: PriceHi1;
  price_lo: PriceLo1;
  reason: Reason1;
  score: Score1;
  source_bars: SourceBars1;
  state: State2;
  t_end_ms: TEndMs;
  t_start_ms: TStartMs;
  tf: Tf4;
}
export interface PresentationBeat {
  camera: CameraMove | null;
  cues: Cues;
  draw_plan: DrawPlan;
  segment_id: SegmentId;
}
export interface Quote {
  ask: Ask;
  bid: Bid;
  source: Source2;
  symbol: Symbol3;
  t_ms: TMs5;
}
export interface Scenario {
  digits?: Digits6;
  direction: Direction4;
  expected_move_atr: ExpectedMoveAtr;
  id?: Id6;
  invalidation_price: InvalidationPrice;
  object_hash?: ObjectHash6;
  prob_sample_n: ProbSampleN;
  probability: Probability;
  rank: Rank;
  reason_chain: ReasonChain;
  valid_until_ms: ValidUntilMs;
  waypoints: Waypoints;
}
export interface Waypoint {
  kind: Kind6;
  note: Note;
  price: Price4;
}
export interface UTBotDrawObject {
  anim: Animation;
  confidence: Confidence2;
  confirmed?: Confirmed1;
  digits?: Digits7;
  direction: Direction5;
  id?: Id7;
  indicator?: Indicator;
  layer: Layer1;
  object_hash?: ObjectHash7;
  points: Points1;
  priority: Priority1;
  reason: Reason2;
  shape: Shape1;
  source_bars: SourceBars2;
  state: State3;
  style: Style;
  symbol?: Symbol4;
  t_open_ms: TOpenMs1;
  text_args: TextArgs1;
  text_key: TextKey1;
  tf: Tf5;
  ttl_ms: TtlMs1;
  warmup?: Warmup;
  z: Z1;
}
export interface TextArgs1 {
  [k: string]: JsonValue;
}
export interface WireEvent {
  payload: Payload1;
  sequence: Sequence;
  t_ms: TMs6;
  version?: Version;
}
