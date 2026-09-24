import { useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './auth/bridge';
import { LoginGate } from './auth/LoginGate';
import { Studio } from './auth/Studio';
import type { SessionStatus } from './net/auth';
import './style.css';

function App() {
  const [mode, setMode] = useState<'login' | 'studio' | null>(null);
  const [session, setSession] = useState<SessionStatus | null>(null);
  useEffect(() => {
    if (!window.oracle) {setMode('login');return;}
    window.oracle.mode().then(async value => {if (value === 'studio') setSession(await window.oracle!.session());setMode(value);}).catch(() => setMode('login'));
  }, []);
  if (mode === 'studio') return session ? <Studio initial={session}/> : <div className="desktop-required">Authenticate before entering Studio.</div>;
  return mode === 'login' ? <LoginGate/> : <div className="boot"><span className="spinner"/>Opening secure login…</div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
