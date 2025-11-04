export type LatencyPoint = {
  ts: number;
  value: number;
};

export type StatusVariant = 'online' | 'degraded' | 'offline' | 'unknown';
