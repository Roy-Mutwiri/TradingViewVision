/** What the speaker reports about its TikTok input. ORACLE displays this; it never produces it. */
export type SpeakerStatus = {
  state: string;
  username: string;
  viewers: number;
  events_per_min: number;
  last_event_age_s: number | null;
  attempts: number;
  error: string;
  killed: boolean;
  quiet: boolean;
  arrivals: Record<string, number> | null;
  age_s: number | null;
  running: boolean;
};
