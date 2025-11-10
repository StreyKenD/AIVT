import { env as publicEnv } from '$env/dynamic/public';
import { readable, type Readable } from 'svelte/store';
import type {
  ExpressionSnapshot,
  MemorySnapshot,
  MemorySummary,
  ModuleStatus,
  OrchestratorStatus,
  PersonaSnapshot,
  TTSRecord
} from './api';

const DEFAULT_ORCH_WS_URL = 'ws://localhost:8000';
const ORCH_WS_URL = publicEnv.PUBLIC_ORCH_WS_URL ?? DEFAULT_ORCH_WS_URL;

type OrchestratorEvent =
  | { type: 'status'; payload: OrchestratorStatus }
  | { type: 'module.toggle'; module: string; enabled: boolean; state?: string }
  | { type: 'persona_update'; persona: PersonaSnapshot }
  | { type: 'tts_request'; data: TTSRecord; summary_generated?: boolean }
  | { type: 'obs_scene'; scene: string; ts: number }
  | { type: 'vts_expression'; data: ExpressionSnapshot }
  | { type: 'memory_summary'; summary: MemorySummary }
  | { type: 'control.mute'; muted: boolean }
  | { type: 'control.panic'; ts?: number; reason?: string | null }
  | { type: 'control.preset'; preset?: string };

export type TelemetryMessage = OrchestratorEvent;

const STREAM_PATH = '/stream';
const BASE_RECONNECT_DELAY_MS = 500;
const SOFT_MAX_RECONNECT_DELAY_MS = 5000;
const HARD_MAX_RECONNECT_DELAY_MS = 10000;
const SOCKET_STATE_CONNECTING = 0;
const SOCKET_STATE_OPEN = 1;
const SOCKET_STATE_CLOSING = 2;

type TimeoutHandle = ReturnType<typeof setTimeout>;
type TimeoutScheduler = (handler: () => void, timeout: number) => TimeoutHandle;
type TimeoutCanceller = (handle: TimeoutHandle) => void;

type WebSocketFactory = () => WebSocketLike;

export interface TelemetryStream {
  subscribe: Readable<TelemetryMessage | null>['subscribe'];
  connect(): void;
  disconnect(): void;
}

export interface TelemetryStreamOptions {
  url?: string;
  socketFactory?: WebSocketFactory;
  scheduleReconnect?: TimeoutScheduler;
  cancelReconnect?: TimeoutCanceller;
}

type WebSocketLike = {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent<string | ArrayBuffer | Blob>) => void) | null;
  onerror: ((event: Event) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  close(code?: number, reason?: string): void;
};

class TelemetrySocketManager {
  private listener: (message: TelemetryMessage) => void = () => {};
  private socket: WebSocketLike | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: TimeoutHandle | null = null;
  private intentionalShutdown = false;
  private buffer = '';

  constructor(
    private readonly factory: WebSocketFactory,
    private readonly schedule: TimeoutScheduler,
    private readonly cancel: TimeoutCanceller
  ) {}

  setListener(listener: (message: TelemetryMessage) => void) {
    this.listener = listener;
  }

  connect(): void {
    this.intentionalShutdown = false;
    this.clearReconnectTimer();

    if (
      this.socket &&
      (this.socket.readyState === SOCKET_STATE_OPEN || this.socket.readyState === SOCKET_STATE_CONNECTING)
    ) {
      return;
    }

    const socket = this.factory();
    this.attachSocket(socket);
  }

  disconnect(): void {
    this.intentionalShutdown = true;
    this.clearReconnectTimer();

    const socket = this.socket;
    if (!socket) {
      this.buffer = '';
      return;
    }

    this.cleanupSocket();

    if (
      socket.readyState === SOCKET_STATE_OPEN ||
      socket.readyState === SOCKET_STATE_CONNECTING ||
      socket.readyState === SOCKET_STATE_CLOSING
    ) {
      try {
        socket.close();
      } catch {
        // Ignore errors triggered by closing synthetic sockets.
      }
    }

    this.buffer = '';
  }

  private attachSocket(socket: WebSocketLike): void {
    this.cleanupSocket();
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempts = 0;
    };

    socket.onmessage = (event) => {
      this.handleIncoming(event.data);
    };

    socket.onerror = () => {
      // rely on close events to trigger reconnection
    };

    socket.onclose = () => {
      const shouldReconnect = !this.intentionalShutdown;
      this.cleanupSocket();

      if (shouldReconnect) {
        this.scheduleReconnect();
      }
    };
  }

  private cleanupSocket(): void {
    if (!this.socket) return;
    this.socket.onopen = null;
    this.socket.onmessage = null;
    this.socket.onerror = null;
    this.socket.onclose = null;
    this.socket = null;
  }

  private scheduleReconnect(): void {
    if (this.intentionalShutdown) return;

    this.clearReconnectTimer();
    const attempt = this.reconnectAttempts;
    const delay = this.calculateBackoff(attempt);
    this.reconnectAttempts = Math.min(this.reconnectAttempts + 1, 32);

    this.reconnectTimer = this.schedule(() => {
      this.reconnectTimer = null;
      if (!this.intentionalShutdown) {
        this.connect();
      }
    }, delay);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      this.cancel(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private calculateBackoff(attempt: number): number {
    const growth = BASE_RECONNECT_DELAY_MS * 2 ** attempt;

    if (growth < SOFT_MAX_RECONNECT_DELAY_MS) {
      return growth;
    }

    if (growth < HARD_MAX_RECONNECT_DELAY_MS) {
      return SOFT_MAX_RECONNECT_DELAY_MS;
    }

    return HARD_MAX_RECONNECT_DELAY_MS;
  }

  private handleIncoming(data: unknown): void {
    if (typeof data === 'string') {
      this.consumeChunk(data);
      return;
    }

    if (data instanceof ArrayBuffer) {
      const decoder = new TextDecoder();
      this.consumeChunk(decoder.decode(data));
      return;
    }

    if (typeof Blob !== 'undefined' && data instanceof Blob) {
      data
        .text()
        .then((text) => this.consumeChunk(text))
        .catch((error) => {
          console.warn('[telemetry] failed to read Blob payload', error);
        });
      return;
    }

    console.warn('[telemetry] unsupported payload received from socket', data);
  }

  private consumeChunk(chunk: string): void {
    this.buffer += chunk;
    const pieces = this.buffer.split('\n');
    this.buffer = pieces.pop() ?? '';

    for (const piece of pieces) {
      const trimmed = piece.trim();
      if (!trimmed) continue;

      try {
        const payload = JSON.parse(trimmed);
        if (isTelemetryMessage(payload)) {
          this.listener(payload);
        } else {
          console.warn('[telemetry] ignored unknown payload', payload);
        }
      } catch (error) {
        console.warn('[telemetry] failed to parse payload', error);
      }
    }
  }
}

export function createTelemetryStream(options: TelemetryStreamOptions = {}): TelemetryStream {
  const url = options.url ?? buildStreamUrl(ORCH_WS_URL);
  const socketFactory =
    options.socketFactory ?? (() => createBrowserSocket(url));
  const scheduleReconnect = options.scheduleReconnect ?? defaultSchedule;
  const cancelReconnect = options.cancelReconnect ?? defaultCancel;

  const manager = new TelemetrySocketManager(socketFactory, scheduleReconnect, cancelReconnect);

  const store = readable<TelemetryMessage | null>(null, (set) => {
    manager.setListener((message) => set(message));
    manager.connect();

    return () => {
      manager.disconnect();
      manager.setListener(() => {});
    };
  });

  return {
    subscribe: store.subscribe,
    connect: () => manager.connect(),
    disconnect: () => manager.disconnect()
  };
}

function buildStreamUrl(baseUrl: string): string {
  const trimmed = baseUrl.endsWith('/') ? baseUrl.slice(0, -1) : baseUrl;
  if (trimmed.endsWith(STREAM_PATH)) {
    return trimmed;
  }
  return `${trimmed}${STREAM_PATH}`;
}

function createBrowserSocket(url: string): WebSocketLike {
  const WebSocketImpl = globalThis.WebSocket;
  if (!WebSocketImpl) {
    throw new Error('WebSocket API is not available in this environment.');
  }
  return new WebSocketImpl(url);
}

const defaultSchedule: TimeoutScheduler = (handler, timeout) => setTimeout(handler, timeout);
const defaultCancel: TimeoutCanceller = (handle) => clearTimeout(handle);

function isTelemetryMessage(payload: unknown): payload is TelemetryMessage {
  return isOrchestratorEvent(payload);
}

function isOrchestratorEvent(payload: unknown): payload is OrchestratorEvent {
  if (!isRecord(payload) || typeof payload.type !== 'string') {
    return false;
  }

  switch (payload.type) {
    case 'status':
      return isOrchestratorStatus(payload.payload);
    case 'module.toggle':
      return (
        typeof payload.module === 'string' &&
        typeof payload.enabled === 'boolean'
      );
    case 'persona_update':
      return isPersonaSnapshot(payload.persona);
    case 'tts_request':
      return isTTSRecord(payload.data);
    case 'obs_scene':
      return typeof payload.scene === 'string' && isNumber(payload.ts);
    case 'vts_expression':
      return isExpressionSnapshot(payload.data);
    case 'memory_summary':
      return isMemorySummary(payload.summary);
    default:
      return false;
  }
}

function isPersonaSnapshot(value: unknown): value is PersonaSnapshot {
  if (!isRecord(value)) return false;
  return (
    typeof value.style === 'string' &&
    isNumber(value.chaos_level) &&
    isNumber(value.energy) &&
    typeof value.family_mode === 'boolean' &&
    isNumber(value.last_updated)
  );
}

function isModuleStatus(value: unknown): value is ModuleStatus {
  if (!isRecord(value)) return false;
  return (
    typeof value.state === 'string' &&
    typeof value.enabled === 'boolean' &&
    isNumber(value.latency_ms) &&
    isNumber(value.last_updated)
  );
}

function isExpressionSnapshot(value: unknown): value is ExpressionSnapshot {
  if (!isRecord(value)) return false;
  return (
    typeof value.expression === 'string' &&
    isNumber(value.intensity) &&
    isNumber(value.ts)
  );
}

function isTTSRecord(value: unknown): value is TTSRecord {
  if (!isRecord(value)) return false;
  return (
    typeof value.text === 'string' &&
    (typeof value.voice === 'string' || value.voice === null || typeof value.voice === 'undefined') &&
    isNumber(value.ts)
  );
}

function isMemorySummary(value: unknown): value is MemorySummary {
  if (!isRecord(value)) return false;
  if (typeof value.summary_text !== 'string' || typeof value.mood_state !== 'string') {
    return false;
  }

  if (!isNumber(value.ts)) {
    return false;
  }

  const metadataSource = (() => {
    if (isRecord(value.metadata)) {
      return value.metadata as Record<string, unknown>;
    }
    if (isRecord(value.knobs)) {
      return value.knobs as Record<string, unknown>;
    }
    return null;
  })();

  if (!metadataSource) {
    return false;
  }

  if (!Object.values(metadataSource).every(isNumber)) {
    return false;
  }

  if (!(typeof value.id === 'number' || value.id === null || typeof value.id === 'undefined')) {
    return false;
  }

  return true;
}

function isMemorySnapshot(value: unknown): value is MemorySnapshot {
  if (!isRecord(value)) return false;
  return (
    isNumber(value.buffer_length) &&
    isNumber(value.summary_interval) &&
    typeof value.restore_enabled === 'boolean' &&
    (value.current_summary === null || typeof value.current_summary === 'undefined' || isMemorySummary(value.current_summary))
  );
}

function isModulesRecord(value: unknown): value is Record<string, ModuleStatus> {
  if (!isRecord(value)) return false;
  return Object.values(value).every(isModuleStatus);
}

function isOrchestratorStatus(value: unknown): value is OrchestratorStatus {
  if (!isRecord(value)) return false;
  return (
    typeof value.status === 'string' &&
    isPersonaSnapshot(value.persona) &&
    isModulesRecord(value.modules) &&
    typeof value.scene === 'string' &&
    (value.last_expression === null ||
      typeof value.last_expression === 'undefined' ||
      isExpressionSnapshot(value.last_expression)) &&
    (value.last_tts === null ||
      typeof value.last_tts === 'undefined' ||
      isTTSRecord(value.last_tts)) &&
    isMemorySnapshot(value.memory) &&
    typeof value.restore_context === 'boolean'
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}
