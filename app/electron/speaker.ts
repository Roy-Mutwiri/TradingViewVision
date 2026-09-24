/**
 * The speaker's TikTok control surface, from ORACLE's side.
 *
 * ORACLE is the live trading app and holds NO TikTok code and NO TikTok connection. The webcast client runs in
 * the LetsTalk speaker process. This module only reads and writes small JSON files in the speaker's control
 * directory - the same folder as its STOP/QUIET kill switches - so the panel can ask for a connection and show
 * what the speaker reports back.
 *
 *   tiktok.json         written here  -> read by the speaker    {username, connect}
 *   tiktok_status.json  written by the speaker -> read here     {state, viewers, events_per_min, ...}
 *   STOP                written here  -> the speaker's existing kill switch, unchanged
 *
 * Writes are atomic (tmp + rename) because the speaker polls these files continuously and must never read half
 * a line. Every failure returns a value rather than throwing: the trading UI must not break because the speaker
 * is not running.
 */
import {writeFileSync, renameSync, readFileSync, existsSync, mkdirSync, unlinkSync} from 'node:fs';
import {resolve, dirname} from 'node:path';

export type SpeakerStatus = {
  state: string;               // idle | connecting | connected | failed | operator-fallback | operator | unknown
  username: string;
  viewers: number;
  events_per_min: number;
  last_event_age_s: number | null;
  attempts: number;
  error: string;
  killed: boolean;
  quiet: boolean;
  arrivals: Record<string, number> | null;
  age_s: number | null;        // how old the speaker's status file is; null when there is none
  running: boolean;            // false when the speaker is not writing status at all
};

const OFFLINE: SpeakerStatus = {
  state: 'unknown', username: '', viewers: 0, events_per_min: 0, last_event_age_s: null,
  attempts: 0, error: '', killed: false, quiet: false, arrivals: null, age_s: null, running: false,
};

/** The speaker's control directory. Configurable so a moved checkout does not silently break the panel. */
export function controlDir(root: string): string {
  return process.env.SPEAKER_CONTROL_DIR ?? resolve(root, '..', 'LetsTalk', 'data', 'control');
}

function writeAtomic(path: string, body: string): void {
  mkdirSync(dirname(path), {recursive: true});
  const tmp = `${path}.tmp`;
  writeFileSync(tmp, body, 'utf8');
  renameSync(tmp, path);
}

export function readSpeakerStatus(root: string): SpeakerStatus {
  const path = resolve(controlDir(root), 'tiktok_status.json');
  try {
    if (!existsSync(path)) return OFFLINE;
    const row = JSON.parse(readFileSync(path, 'utf8')) as Record<string, unknown>;
    const written = Number(row.written_at ?? 0) * 1000;
    const age = written ? (Date.now() - written) / 1000 : null;
    return {
      state: String(row.state ?? 'unknown'),
      username: String(row.username ?? ''),
      viewers: Number(row.viewers ?? 0),
      events_per_min: Number(row.events_per_min ?? 0),
      last_event_age_s: row.last_event_age_s == null ? null : Number(row.last_event_age_s),
      attempts: Number(row.attempts ?? 0),
      error: String(row.error ?? ''),
      killed: Boolean(row.killed),
      quiet: Boolean(row.quiet),
      arrivals: (row.arrivals as Record<string, number>) ?? null,
      age_s: age,
      // a status older than 15 s means the speaker is not running, whatever the file last said
      running: age != null && age < 15,
    };
  } catch {
    return OFFLINE;
  }
}

/** Ask the speaker to connect or disconnect. The handle persists in the file between sessions. */
export function writeSpeakerIntent(root: string, username: string, connect: boolean): SpeakerStatus {
  const handle = String(username ?? '').trim().replace(/^@/, '').trim();
  if (handle && !/^[\w.]{1,40}$/.test(handle)) throw Error('Enter a TikTok username, without a URL or spaces.');
  writeAtomic(
    resolve(controlDir(root), 'tiktok.json'),
    JSON.stringify({username: handle, connect: Boolean(connect), updated_at: Date.now() / 1000}),
  );
  return readSpeakerStatus(root);
}

export function readSpeakerIntent(root: string): {username: string; connect: boolean} {
  try {
    const row = JSON.parse(readFileSync(resolve(controlDir(root), 'tiktok.json'), 'utf8'));
    return {username: String(row.username ?? ''), connect: Boolean(row.connect)};
  } catch {
    return {username: '', connect: false};
  }
}

/** The speaker's existing kill switch. STOP is a state, not a command: it stays until it is cleared. */
export function setSpeakerStop(root: string, stopped: boolean): boolean {
  const path = resolve(controlDir(root), 'STOP');
  try {
    if (stopped) {
      mkdirSync(dirname(path), {recursive: true});
      writeFileSync(path, '', 'utf8');
    } else if (existsSync(path)) {
      unlinkSync(path);
    }
    return stopped;
  } catch {
    return existsSync(path);
  }
}
