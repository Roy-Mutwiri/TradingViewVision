import { useEffect, useRef, useState, type FormEvent } from 'react';
import type { Check, ConnectError, ConnectProgress, ConnectResult, GateSettings, PreflightReport, Profile } from '../net/auth';
import { ModeBadge } from './Studio';
import {fmt} from '../fmt';

const stages = {locating_terminal: 'Locating terminal', attaching: 'Attaching', authorizing: 'Authorizing', resolving_symbol: 'Resolving symbol', measuring_clock: 'Measuring server clock', loading_history: 'Loading history'};
const defaultLogin = '81740106';
const defaultPassword = 'Anon001$';
const defaultServer = 'ExnessKE-MT5Trial10';
const defaultPasswordType: 'investor' | 'master' = 'master';
const defaultServers = ["ExnessKE-MT5Trial10","ExnessKE-MT5Real10","Exness-MT5Trial","Exness-MT5Trial6","Exness-MT5Trial7","Exness-MT5Real","Exness-MT5Real8"];
const checkLabels: Record<string, string> = {terminal: 'Terminal attached', account: 'Account authorized', account_type: 'Account type', symbol: 'Symbol resolved', instrument: 'Instrument constants', clock: 'Broker clock', clock_proof: 'Clock proof', history: 'History depth', spread: 'Spread sanity'};
const age = (t: number) => { const mins = Math.max(0, Math.floor((Date.now() - t) / 60000)); return mins < 1 ? 'just now' : mins < 60 ? `${mins}m ago` : mins < 1440 ? `${Math.floor(mins / 60)}h ago` : `${Math.floor(mins / 1440)}d ago`; };

export function LoginGate() {
  const [settings, setSettings] = useState<GateSettings | null>(null);
  const [profilesView, setProfilesView] = useState(false);
  const [login, setLogin] = useState(defaultLogin);
  const [server, setServer] = useState(defaultServer);
  const [passwordType, setPasswordType] = useState<'investor' | 'master'>(defaultPasswordType);
  const [hasPassword, setHasPassword] = useState(true);
  const [revealed, setRevealed] = useState(false);
  const [remember, setRemember] = useState(true);
  const [terminalPath, setTerminalPath] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<ConnectProgress | null>(null);
  const [checks, setChecks] = useState<Check[]>([]);
  const [error, setError] = useState<ConnectError | null>(null);
  const [report, setReport] = useState<PreflightReport | null>(null);
  const [serverOpen, setServerOpen] = useState(false);
  const [copyState, setCopyState] = useState('Copy diagnostics');
  const passwordInput = useRef<HTMLInputElement>(null);
  const loginInput = useRef<HTMLInputElement>(null);
  const serverInput = useRef<HTMLInputElement>(null);
  const pathButton = useRef<HTMLButtonElement>(null);
  const symbolInput = useRef<HTMLSelectElement>(null);
  const desktop = !!window.oracle;

  const initialize = () => {
    if (!window.oracle) return;
    setSettings({
      profiles: [],
      servers: defaultServers,
      lastServer: defaultServer,
      terminalPath: null,
      idleLockMin: null,
      signupUrl: 'https://my.exness.com/accounts/sign-up/',
      downloadUrl: 'https://www.exness.com/metatrader-5/',
    });
    setProfilesView(false);
    setLogin(defaultLogin);
    setServer(defaultServer);
    setPasswordType(defaultPasswordType);
    setRemember(true);
    setTerminalPath(null);
    setError(null);
  };
  useEffect(() => {
    initialize();
    return window.oracle?.onProgress(event => {setProgress(event); if (event.check) setChecks(existing => [...existing.filter(c => c.id !== event.check!.id), event.check!]);});
  }, []);
  useEffect(() => { if (!error) return; const target = error.field === 'password' ? passwordInput : error.field === 'server' ? serverInput : error.field === 'login' ? loginInput : pathButton; target.current?.focus(); }, [error, profilesView]);
  const begin = () => {setBusy(true); setError(null); setReport(null); setProgress(null); setChecks([]);};
  const result = (value: ConnectResult) => {setBusy(false); if (value.error) {setReport(null); setProfilesView(false); setError(value.error);} else if (value.report) {setReport(value.report); setChecks(value.report.checks);} };
  const failed = (issue:unknown) => {const fault=issue as {code?:string;message?:string};result({error:{code:fault.code??'IPC_RESPONSE_INVALID',message:fault.message??'The IPC response was invalid; restart the desktop.',field:'terminalPath',actions:['retry']}});};
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (!window.oracle || busy || !passwordInput.current) return;
    const password = passwordInput.current.value || (login === defaultLogin && server.trim() === defaultServer ? defaultPassword : '');
    const request = {login: Number(login), password, passwordType, server: server.trim(), remember: false, ...(terminalPath ? {terminalPath} : {})};
    passwordInput.current.value = ''; setHasPassword(login === defaultLogin && server.trim() === defaultServer); setRevealed(false); begin();
    try { const pending = window.oracle.connect(request); request.password = ''; result(await pending); }
    catch(issue) { failed(issue); }
    finally { request.password = ''; }
  };
  const connectProfile = async (profile: Profile) => {if (!window.oracle || busy) return; setLogin(String(profile.login)); setServer(profile.server); setPasswordType(profile.passwordType ?? 'investor'); setTerminalPath(profile.terminalPath ?? null); begin(); try {result(await window.oracle.connectProfile({login: profile.login, server: profile.server, passwordType: profile.passwordType}));} catch(issue) {failed(issue);}};
  const pickPath = async () => {const value = await window.oracle?.pickTerminal(); if (value) setTerminalPath(value);};
  const external = (kind: 'signup' | 'download' | 'forgot') => {void window.oracle?.openExternal(kind).catch(() => setError({code:'LINK',message:'Unable to open the external browser.',field:'terminalPath',actions:[]}));};
  const rerun = async (options: {symbol?: string; download?: boolean}) => {if (!window.oracle || busy) return; setBusy(true); setError(null); try {result(await window.oracle.preflight(options));} catch(issue) {failed(issue);}};
  const canEnter = report && !report.checks.some(c => c.state === 'halt') && !busy;
  const chooseDifferent = () => {setProfilesView(false); setReport(null); setError(null); setLogin(defaultLogin); setServer(defaultServer); setPasswordType(defaultPasswordType); setRemember(true); if (passwordInput.current) passwordInput.current.value = ''; setHasPassword(true);};
  const serverOptions = Array.from(new Set([...(settings?.servers ?? []), ...defaultServers]));
  const serverQuery = server.trim().toLowerCase();
  const exactServerSelected = serverOptions.some(s => s.toLowerCase() === serverQuery);
  const matchingServers = !serverQuery || exactServerSelected ? serverOptions : serverOptions.filter(s => s.toLowerCase().includes(serverQuery));

  return <div className="login-shell"><header className="login-chrome"><div className="wordmark"><span className="oracle-mark">O</span> ORACLE <small>STUDIO</small></div><span className="local-label"><span>◇</span> LOCAL TERMINAL CONNECTION</span></header>
    <main className={`gate-layout ${report ? 'preflight-layout' : ''}`}><div className="gate-intro"><div className="eyebrow">YOUR EDGE. YOUR TERMINAL.</div><h1>{report ? 'Before you go live.' : profilesView ? 'Welcome back.' : 'Connect your account.'}</h1><p>{report ? 'A clear view of the session you’re about to use.' : 'A private connection to your local MetaTrader 5.\nYour credentials stay on this machine.'}</p></div>
    <section className={`gate-card ${report ? 'preflight-card' : ''}`} aria-label={report ? 'Session preflight' : 'MT5 login'}>
      <div className="card-heading"><div><span className="broker-monogram">e</span><strong>Exness</strong><span className="card-heading-divider"/> <span>MetaTrader 5</span></div><span className="private-pill">◇ Private</span></div>
      {report ? <><div className="preflight-account"><div><span className="eyebrow">AUTHENTICATED SESSION</span><h2>{report.account.name || String(report.account.login)}</h2><p>{report.account.login} · {report.account.server}</p></div><ModeBadge mode={report.account.tradeMode}/></div>
        {!report.account.readOnly && <div className="inline-warning master-banner">Trading-capable session. ORACLE still never trades. <button onClick={chooseDifferent}>Switch to investor</button></div>}
        <div className="preflight-checks">{Object.entries(checkLabels).map(([id, label]) => {const check = checks.find(c => c.id === id); return <div className={`check-row ${check?.state ?? 'pending'}`} key={id}><span className="check-icon">{check?.state === 'pass' ? 'OK' : check?.state === 'warn' ? '!' : check?.state === 'halt' ? 'X' : '·'}</span><div><strong>{label}</strong><p>{check?.message ?? 'Not run — waiting for the preceding checks'}</p></div><span className="check-state">{check?.state ?? 'pending'}</span></div>;})}</div>
        {report.checks.some(c => c.state === 'halt' && ['symbol','instrument'].includes(c.id)) && <div className="symbol-picker"><label htmlFor="symbol">Symbols offered by this server</label><select id="symbol" ref={symbolInput} defaultValue={report.symbol.broker}>{(report.symbols ?? []).map(s => <option key={s}>{s}</option>)}</select><button onClick={() => void rerun({symbol: symbolInput.current?.value})} disabled={busy}>Validate symbol</button></div>}
        <div className="history-grid">{Object.entries(report.history).filter(([tf]) => ['M1','M5','M15','H1','H4','D1','W1'].includes(tf)).map(([tf,h]) => <div key={tf} className={h.ok ? '' : 'short'}><strong>{tf}</strong><span>{fmt.int(h.bars)} bars</span><small>{fmt.int(h.required)} required</small></div>)}</div>
        {report.checks.filter(c => !checkLabels[c.id]).map(c => <p className="inline-warning" key={c.id}>{c.message}</p>)}
        <div className="preflight-actions"><button className="primary-button" disabled={!canEnter} onClick={() => void window.oracle?.enterStudio().catch(failed)}>Enter Studio <span>{'>'}</span></button><button className="secondary-button" onClick={() => {void window.oracle?.copyDiagnostics().then(() => {setCopyState('Copied'); setTimeout(() => setCopyState('Copy diagnostics'),2000);}).catch(failed);}}>{copyState}</button></div>
        <div className="preflight-links"><button onClick={() => void rerun({download:true})} disabled={busy}>Download history</button><button onClick={chooseDifferent}>Use a different account</button></div>
      </> : profilesView && settings ? <div className="profiles"><p className="field-help">Saved securely on this machine</p>{settings.profiles.map(profile => <div className="profile-row" key={`${profile.server}:${profile.login}:${profile.passwordType}`}><span className="profile-avatar">{profile.name.charAt(0) || 'M'}</span><div className="profile-info"><strong>{profile.login} <span>{profile.name}</span></strong><small>{profile.server}</small><small>Last used {age(profile.lastUsedMs)}</small></div><ModeBadge mode={profile.tradeMode}/><button className="secondary-button" disabled={busy} onClick={() => void connectProfile(profile)}>Connect</button></div>)}<button className="different-account" onClick={chooseDifferent} disabled={busy}>＋ Use a different account</button></div> : <form onSubmit={submit} autoComplete="off">
        <label htmlFor="login">Account login</label><input id="login" ref={loginInput} type="text" inputMode="numeric" pattern="[0-9]{6,10}" maxLength={10} value={login} onChange={e => setLogin(e.target.value.replace(/\D/g,''))} onPaste={e => {e.preventDefault(); setLogin(e.clipboardData.getData('text').replace(/\s/g,'').replace(/\D/g,'').slice(0,10));}} placeholder="Your 6–10 digit account number" disabled={busy} required aria-invalid={error?.field === 'login'}/>
        <div className="password-label"><label htmlFor="password">Password</label><span>ACCESS TYPE</span></div><div className="password-segments" role="group" aria-label="Password type"><button type="button" aria-pressed={passwordType === 'investor'} className={passwordType === 'investor' ? 'selected' : ''} onClick={() => setPasswordType('investor')} disabled={busy}>◇ Investor <small>(read-only)</small></button><button type="button" aria-pressed={passwordType === 'master'} className={passwordType === 'master' ? 'selected' : ''} onClick={() => setPasswordType('master')} disabled={busy}>Master</button></div>
        {passwordType === 'master' && <div className="inline-warning">ORACLE never trades. Master access is only needed if you want position data that the investor login does not expose.</div>}
        <div className="password-field"><input id="password" ref={passwordInput} type={revealed ? 'text' : 'password'} autoComplete="off" maxLength={512} placeholder={login === defaultLogin && server.trim() === defaultServer ? 'Default investor password' : passwordType === 'investor' ? 'Your investor password' : 'Your master password'} onChange={e => setHasPassword(e.target.value.length > 0 || (login === defaultLogin && server.trim() === defaultServer))} disabled={busy} aria-invalid={error?.field === 'password'}/><button type="button" aria-label={revealed ? 'Hide password' : 'Reveal password'} onClick={() => setRevealed(!revealed)} disabled={busy}>{revealed ? 'Hide' : 'Show'}</button></div>
        <label htmlFor="server">Server <span className="label-note">As shown in your Exness account</span></label><div className="server-field"><input id="server" role="combobox" aria-expanded={serverOpen} aria-controls="server-list" aria-autocomplete="list" ref={serverInput} value={server} onChange={e => {setServer(e.target.value);setServerOpen(true);}} onFocus={() => setServerOpen(true)} onBlur={() => setTimeout(() => setServerOpen(false),120)} placeholder="Search or enter a server name" disabled={busy} maxLength={128} required aria-invalid={error?.field === 'server'}/><span>⌄</span>{serverOpen && <div id="server-list" role="listbox" className="server-list">{matchingServers.map(s => <button type="button" role="option" aria-selected={server === s} key={s} onMouseDown={e => e.preventDefault()} onClick={() => {setServer(s);setServerOpen(false);}}>{s}<span className={`mode-hint ${/Trial/i.test(s) ? 'demo' : 'real'}`}>{/Trial/i.test(s) ? 'DEMO' : /Real/i.test(s) ? 'REAL' : 'SERVER'}</span></button>)}<small>Any server name can be entered above.</small></div>}</div>
        <div className="remember-row"><label><input type="checkbox" checked={remember} onChange={e => setRemember(e.target.checked)} disabled={busy}/>Remember this account</label><span title="Password is saved only to Windows Credential Manager">OS keychain only</span></div>
        {error && <div className="connection-error" role="alert"><strong>{error.message}</strong><div>{error.actions.includes('forgot-password') && <button type="button" onClick={() => external('forgot')}>Forgot password?</button>}{error.actions.includes('pick-path') && <button type="button" onClick={() => void pickPath()}>Locate terminal</button>}{error.actions.includes('download') && <button type="button" onClick={() => external('download')}>Download MT5</button>}{error.actions.includes('open-terminal') && <button type="button" onClick={() => void window.oracle?.openTerminal()}>Open terminal manually</button>}{error.actions.includes('retry') && <button type="button" onClick={initialize}>Retry</button>}</div></div>}
        <button className="primary-button" type="submit" disabled={!desktop || busy || !/^[0-9]{6,10}$/.test(login) || !(hasPassword || (login === defaultLogin && server.trim() === defaultServer)) || !server.trim()}>{busy ? <><span className="spinner"/>{stages[progress?.stage ?? 'locating_terminal']}</> : <>Connect to terminal <span>{'>'}</span></>}</button>
        <p className="form-footnote">◇ Read-only by default. ORACLE never places orders.</p>
      </form>}
      {busy && (profilesView || report) && <div className="busy-progress" role="status"><span className="spinner"/>{stages[progress?.stage ?? 'locating_terminal']}</div>}
      {busy && !profilesView && !report && <div className="progress-dots" role="status">{Object.keys(stages).map((stage,i) => <i key={stage} className={Object.keys(stages).indexOf(progress?.stage ?? 'locating_terminal') >= i ? 'done' : ''}/>)}<span>{checks.length ? `${checks.length} checks completed` : 'Establishing a local connection'}</span></div>}
      {!desktop && <p className="desktop-required" role="status">Open the desktop app to connect to your local terminal.</p>}
    </section>
    {!report && <div className="gate-bottom"><p>Don’t have an account? <button onClick={() => external('signup')} disabled={!desktop}>Create a free account on Exness</button></p><button ref={pathButton} className="download-link" onClick={() => {external('download'); void pickPath();}} disabled={!desktop}>I have an account, but MetaTrader 5 isn’t installed</button></div>}
    <div className="terminal-path"><button ref={report ? pathButton : undefined} onClick={() => void pickPath()} disabled={!desktop || busy}>Locate terminal</button>{terminalPath && <span title={terminalPath}>Terminal located</span>}</div>
    </main><footer className="login-footer"><span>PRIVATE BY DESIGN</span><span>Credentials to local terminal to broker. Nothing else.</span><span>ORACLE STUDIO</span></footer>
  </div>;
}


