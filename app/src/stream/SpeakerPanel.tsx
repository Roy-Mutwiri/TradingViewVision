/**
 * TikTok input for the speaker, controlled from ORACLE.
 *
 * ORACLE holds no TikTok code: the field writes a handle and a connect intent to the speaker's control
 * directory, and everything shown here is what the speaker reported back. If the speaker is not running the
 * panel says so rather than showing a stale state.
 */
import {useEffect, useState} from 'react';
import {fmt} from '../fmt';
import type {SpeakerStatus} from '../net/speaker';

const LABEL: Record<string, string> = {
  connected: 'Connected',
  connecting: 'Connecting…',
  failed: 'Failed',
  'operator-fallback': 'Operator fallback',
  operator: 'Operator',
  idle: 'Idle',
  unknown: 'Speaker offline',
};

function age(seconds: number | null): string {
  if (seconds == null) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

export function SpeakerPanel() {
  const [status, setStatus] = useState<SpeakerStatus | null>(null);
  const [handle, setHandle] = useState('');
  const [busy, setBusy] = useState(false);
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      const next = await window.oracle!.speakerStatus!();
      if (!alive) return;
      setStatus(next);
      // the field persists between sessions: seed it from what the speaker last knew, until the user types
      if (!touched && next.username) setHandle(next.username);
    };
    void tick();
    const timer = setInterval(() => void tick(), 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [touched]);

  useEffect(() => {
    if (touched) return;
    void window.oracle!.speakerIntent!().then(intent => {
      if (intent.username) setHandle(intent.username);
    });
  }, [touched]);

  const act = async (connect: boolean) => {
    setBusy(true);
    try {
      setStatus(await window.oracle!.speakerConnect!(handle, connect));
    } finally {
      setBusy(false);
    }
  };

  const state = status?.running ? status.state : 'unknown';
  const arrivals = status?.arrivals ?? null;
  return (
    <section className="speaker-panel" data-testid="speaker-panel" data-state={state}>
      <h4>TikTok input <small>(speaker)</small></h4>

      <div className="field-row">
        <label htmlFor="speaker-handle">Username</label>
        <input
          id="speaker-handle"
          value={handle ? `@${handle.replace(/^@/, '')}` : ''}
          placeholder="@handle"
          onChange={e => {
            setTouched(true);
            setHandle(e.target.value.trimStart().replace(/^@/, ''));
          }}
        />
      </div>

      <div className="field-row">
        <button disabled={busy || !handle} onClick={() => void act(true)}>Connect</button>
        <button disabled={busy} onClick={() => void act(false)}>Disconnect</button>
        <button
          className="speaker-stop"
          data-testid="speaker-stop"
          title="Stops speech inside about a second. Clear it to resume."
          onClick={() => void window.oracle!.speakerStop!(!(status?.killed ?? false))}
        >
          {status?.killed ? 'Clear STOP' : 'STOP'}
        </button>
      </div>

      <dl className="speaker-status">
        <dt>Status</dt><dd data-testid="speaker-state">{LABEL[state] ?? state}</dd>
        <dt>Viewers</dt><dd>{status?.running ? fmt.int(status.viewers) : '—'}</dd>
        <dt>Events/min</dt><dd>{status?.running ? fmt.one(status.events_per_min) : '—'}</dd>
        <dt>Last event</dt><dd>{status?.running ? age(status.last_event_age_s) : '—'}</dd>
        {arrivals && <><dt>Welcomes</dt><dd>{arrivals.welcomes_spoken ?? 0} of {arrivals.joins_seen ?? 0} joins</dd></>}
        {arrivals && (arrivals.names_skipped ?? 0) > 0 && (
          <><dt>Names skipped</dt><dd title="Unsafe names are never spoken">{arrivals.names_skipped}</dd></>
        )}
      </dl>

      {!status?.running && <p className="speaker-note">The speaker is not running; start it to connect.</p>}
      {status?.running && status.state === 'operator-fallback' && (
        <p className="speaker-note">Webcast unavailable — a human is relaying chat. {status.error}</p>
      )}
      {status?.running && status.killed && <p className="speaker-note">STOP is set: he is silent.</p>}
    </section>
  );
}
