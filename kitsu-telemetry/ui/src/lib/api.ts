import { env as publicEnv } from '$env/dynamic/public';

const DEFAULT_ORCH_BASE_URL = 'http://localhost:8000';
const ORCH_BASE_URL = sanitizeBaseUrl(
  publicEnv.PUBLIC_ORCH_BASE_URL ?? DEFAULT_ORCH_BASE_URL,
  DEFAULT_ORCH_BASE_URL
);
const DEFAULT_CONTROL_BASE_URL = 'http://localhost:8100';
const CONTROL_BASE_URL = sanitizeBaseUrl(
  publicEnv.PUBLIC_CONTROL_BASE_URL ?? DEFAULT_CONTROL_BASE_URL,
  DEFAULT_CONTROL_BASE_URL
);

type JsonObject = { [key: string]: JsonValue };
type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];

export type ModuleStatus = {
  state: 'online' | 'offline';
  latency_ms: number;
  last_updated: number;
};

export type PersonaSnapshot = {
  style: string;
  chaos_level: number;
  energy: number;
  family_mode: boolean;
  last_updated: number;
};

export type MemorySummary = {
  id: number | null;
  summary_text: string;
  mood_state: string;
  knobs: Record<string, number>;
  ts: number;
};

export type MemorySnapshot = {
  buffer_length: number;
  summary_interval: number;
  restore_enabled: boolean;
  current_summary: MemorySummary | null;
};

export type OrchestratorStatus = {
  status: string;
  persona: PersonaSnapshot;
  modules: Record<string, ModuleStatus>;
  scene: string;
  last_expression: ExpressionSnapshot | null;
  last_tts: TTSRecord | null;
  memory: MemorySnapshot;
  restore_context: boolean;
  control?: ControlSnapshot;
};

export type ControlSnapshot = {
  tts_muted: boolean;
  panic_at: number | null;
  panic_reason: string | null;
  active_preset: string;
};

export type ExpressionSnapshot = {
  expression: string;
  intensity: number;
  ts: number;
};

export type TTSRecord = {
  text: string;
  voice: string | null;
  ts: number;
};

export type ToggleModuleResponse = {
  type: 'module.toggle';
  module: string;
  enabled: boolean;
};

export type PersonaUpdatePayload = Partial<Pick<PersonaSnapshot, 'style' | 'chaos_level' | 'energy' | 'family_mode'>>;

export type PersonaUpdateResponse = {
  type: 'persona_update';
  persona: PersonaSnapshot;
};

export type TTSRequestPayload = {
  text: string;
  voice?: string | null;
};

export type TTSRequestResponse = {
  type: 'tts_request';
  data: TTSRecord;
  summary_generated?: boolean;
};

export type OBSSceneResponse = {
  type: 'obs_scene';
  scene: string;
  ts: number;
};

export type VTSExpressionPayload = {
  expression: string;
  intensity?: number;
};

export type VTSExpressionResponse = {
  type: 'vts_expression';
  data: ExpressionSnapshot;
};

export type LatestMetrics = {
  window_seconds: number;
  metrics: Record<
    string,
    {
      count: number;
      failures?: number;
      latency_ms?: { avg?: number; max?: number; min?: number };
    }
  >;
};

export type SoakResult = {
  ts: string;
  type: string;
  payload: Record<string, JsonValue>;
};

export async function getStatus(): Promise<OrchestratorStatus> {
  return apiRequest<OrchestratorStatus>('/status');
}

export async function toggleModule(module: string, enabled: boolean): Promise<ToggleModuleResponse> {
  return apiRequest<ToggleModuleResponse>(`/toggle/${encodeURIComponent(module)}`, {
    method: 'POST',
    body: JSON.stringify({ enabled })
  });
}

export async function setPersona(payload: PersonaUpdatePayload): Promise<PersonaUpdateResponse> {
  return apiRequest<PersonaUpdateResponse>('/persona', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function requestTTS(payload: TTSRequestPayload): Promise<TTSRequestResponse> {
  return apiRequest<TTSRequestResponse>('/tts', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function setOBSScene(scene: string): Promise<OBSSceneResponse> {
  return apiRequest<OBSSceneResponse>('/obs/scene', {
    method: 'POST',
    body: JSON.stringify({ scene })
  });
}

export async function setVTSExpression(payload: VTSExpressionPayload): Promise<VTSExpressionResponse> {
  return apiRequest<VTSExpressionResponse>('/vts/expr', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export async function triggerPanic(reason?: string): Promise<JsonObject> {
  return controlRequest<JsonObject>('/control/panic', {
    method: 'POST',
    body: JSON.stringify({ reason: reason?.trim() || null })
  });
}

export async function setGlobalMute(muted: boolean): Promise<JsonObject> {
  return controlRequest<JsonObject>('/control/mute', {
    method: 'POST',
    body: JSON.stringify({ muted })
  });
}

export async function applyPreset(preset: string): Promise<JsonObject> {
  return controlRequest<JsonObject>('/control/preset', {
    method: 'POST',
    body: JSON.stringify({ preset })
  });
}

export async function fetchLatestMetrics(windowSeconds = 300): Promise<LatestMetrics> {
  const search = new URLSearchParams({ window_seconds: String(windowSeconds) });
  return controlRequest<LatestMetrics>(`/metrics/latest?${search.toString()}`);
}

export async function fetchSoakResults(limit = 10): Promise<SoakResult[]> {
  const search = new URLSearchParams({ limit: String(limit) });
  const response = await controlRequest<{ items: SoakResult[] }>(`/soak/results?${search}`);
  return response.items;
}

export async function downloadTelemetryCsv(): Promise<Blob> {
  const response = await controlFetch('/telemetry/export', { method: 'GET' });
  if (!response.ok) {
    throw new ApiError(`Falha no download (${response.status})`, response.status);
  }
  return await response.blob();
}

class ApiError extends Error {
  readonly status: number;
  readonly details: JsonValue | undefined;

  constructor(message: string, status: number, details?: JsonValue) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.details = details;
  }
}

async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const url = `${ORCH_BASE_URL}${path}`;
  const response = await fetch(url, {
    headers: buildHeaders(init.headers),
    ...init
  });

  let parsed: JsonValue | undefined;
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    parsed = (await response.json()) as JsonValue;
  } else if (response.status !== 204) {
    parsed = (await response.text()) as unknown as JsonValue;
  }

  if (!response.ok) {
    const message =
      typeof parsed === 'object' && parsed !== null && 'detail' in parsed
        ? String((parsed as Record<string, unknown>).detail ?? 'Request failed')
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, parsed);
  }

  return parsed as T;
}

async function controlRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await controlFetch(path, init);

  let parsed: JsonValue | undefined;
  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    parsed = (await response.json()) as JsonValue;
  }

  if (!response.ok) {
    const message =
      typeof parsed === 'object' && parsed !== null && 'detail' in parsed
        ? String((parsed as Record<string, unknown>).detail ?? 'Request failed')
        : `Request failed with status ${response.status}`;
    throw new ApiError(message, response.status, parsed);
  }

  return parsed as T;
}

async function controlFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const url = `${CONTROL_BASE_URL}${path}`;
  return fetch(url, {
    headers: buildHeaders(init.headers),
    ...init
  });
}

function buildHeaders(headers: HeadersInit | undefined): HeadersInit {
  const existing = new Headers(headers);
  if (!existing.has('Content-Type')) {
    existing.set('Content-Type', 'application/json');
  }
  if (!existing.has('Accept')) {
    existing.set('Accept', 'application/json');
  }
  return existing;
}

function sanitizeBaseUrl(url: string, fallback: string): string {
  if (!url) {
    return fallback;
  }
  return url.endsWith('/') ? url.slice(0, -1) : url;
}

export { ApiError };
