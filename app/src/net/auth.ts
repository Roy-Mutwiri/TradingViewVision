/* Generated from engine/oracle/auth/contracts.py. Do not edit. */

export type Id = string;
export type Message = string;
export type State = "pass" | "warn" | "halt";
export type Clockversion = number;
export type Offsets = number;
export type Proofdetail = string | null;
export type Proven = boolean;
export type Source = "measured";
export type Actions = string[];
export type Code = string;
export type JsonValue = unknown;
export type Field = "password" | "server" | "terminalPath" | "login" | "symbol";
export type Message1 = string;
export type Recoverable = boolean;
export type Detail1 = string | null;
export type Ok = boolean;
export type Stage =
  "locating_terminal" | "attaching" | "authorizing" | "resolving_symbol" | "measuring_clock" | "loading_history";
export type Login = number;
export type Password = string;
export type Passwordtype = "investor" | "master";
export type Remember = boolean;
export type Server = string;
export type Terminalpath = string | null;
export type Currency = string;
export type Login1 = number;
export type Name = string;
export type Readonly = boolean;
export type Server1 = string;
export type Trademode = "DEMO" | "REAL" | "CONTEST";
export type Checks = Check[];
export type Bars = number;
export type Ok1 = boolean;
export type Required = number;
export type Broker = string;
export type Canonical = "XAUUSD";
export type Contractsize = number;
export type Digits = number;
export type Point = number;
export type Spreadpoints = number;
export type Symbols = string[];
export type Downloadurl = string;
export type Idlelockmin = number | null;
export type Lastserver = string;
export type Lastusedms = number;
export type Login2 = number;
export type Name1 = string;
export type Passwordtype1 = "investor" | "master";
export type Server2 = string;
export type Terminalpath1 = string | null;
export type Trademode1 = "DEMO" | "REAL" | "CONTEST";
export type Profiles = Profile[];
export type Servers = string[];
export type Signupurl = string;
export type Terminalpath2 = string | null;
export type Clockproven = boolean;
export type State1 = "connected" | "reconnecting" | "locked";
export type Trademode2 = "DEMO" | "REAL" | "CONTEST";
export type Tradingcapable = boolean;

export interface OracleAuth {
  Check?: Check;
  ClockReport?: ClockReport;
  ConnectError?: ConnectError;
  ConnectProgress?: ConnectProgress;
  ConnectRequest?: ConnectRequest;
  ConnectResult?: ConnectResult;
  GateSettings?: GateSettings;
  HistoryDepth?: HistoryDepth;
  JsonValue?: JsonValue;
  OperatorAccount?: OperatorAccount;
  PreflightReport?: PreflightReport;
  Profile?: Profile;
  SessionStatus?: SessionStatus;
  SymbolReport?: SymbolReport;
}
export interface Check {
  id: Id;
  message: Message;
  state: State;
}
export interface ClockReport {
  clockVersion: Clockversion;
  offsetS: Offsets;
  proofDetail?: Proofdetail;
  proven: Proven;
  source?: Source;
}
export interface ConnectError {
  actions: Actions;
  code: Code;
  detail?: Detail;
  field: Field;
  message: Message1;
  recoverable?: Recoverable;
}
export interface Detail {
  [k: string]: JsonValue;
}
export interface ConnectProgress {
  check?: Check | null;
  detail?: Detail1;
  ok: Ok;
  stage: Stage;
}
export interface ConnectRequest {
  login: Login;
  password: Password;
  passwordType?: Passwordtype;
  remember?: Remember;
  server: Server;
  terminalPath?: Terminalpath;
}
export interface ConnectResult {
  error?: ConnectError | null;
  report?: PreflightReport | null;
}
export interface PreflightReport {
  account: OperatorAccount;
  checks: Checks;
  clock: ClockReport;
  history: History;
  symbol: SymbolReport;
  symbols?: Symbols;
}
export interface OperatorAccount {
  currency: Currency;
  login: Login1;
  name: Name;
  readOnly: Readonly;
  server: Server1;
  tradeMode: Trademode;
}
export interface History {
  [k: string]: HistoryDepth;
}
export interface HistoryDepth {
  bars: Bars;
  ok: Ok1;
  required: Required;
}
export interface SymbolReport {
  broker: Broker;
  canonical?: Canonical;
  contractSize: Contractsize;
  digits: Digits;
  point: Point;
  spreadPoints: Spreadpoints;
}
export interface GateSettings {
  downloadUrl: Downloadurl;
  idleLockMin: Idlelockmin;
  lastServer: Lastserver;
  profiles: Profiles;
  servers: Servers;
  signupUrl: Signupurl;
  terminalPath: Terminalpath2;
}
export interface Profile {
  lastUsedMs: Lastusedms;
  login: Login2;
  name: Name1;
  passwordType?: Passwordtype1;
  server: Server2;
  terminalPath?: Terminalpath1;
  tradeMode: Trademode1;
}
export interface SessionStatus {
  clockProven: Clockproven;
  state?: State1;
  tradeMode: Trademode2;
  tradingCapable: Tradingcapable;
}
