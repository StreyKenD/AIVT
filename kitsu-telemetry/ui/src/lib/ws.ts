import { readable, type Readable } from 'svelte/store';

type MetricPayload = {
  fps: number;
  cpu: number;
  gpu: number;
  viewers: number;
  vu: number[];
};

type ConsolePayload = {
  level: 'info' | 'warning' | 'error';
  message: string;
};

export type TelemetryMessage =
  | { type: 'metrics'; data: MetricPayload }
  | { type: 'console'; data: ConsolePayload }
  | { type: 'expression'; data: { expression: string } };

const LEVELS = ['info', 'warning', 'error'] as const;
const EXPRESSIONS = ['Happy', 'Surprised', 'Cool', 'Thinking'];

function randomInt(min: number, max: number): number {
  return Math.floor(Math.random() * (max - min + 1)) + min;
}

export class MockTelemetrySocket {
  private readonly listeners = new Set<(message: TelemetryMessage) => void>();
  private timer: ReturnType<typeof setInterval> | null = null;

  constructor(private readonly interval = 1200) {}

  connect(): void {
    if (this.timer) return;
    this.timer = setInterval(() => {
      const metricPayload: MetricPayload = {
        fps: randomInt(50, 120),
        cpu: randomInt(20, 90),
        gpu: randomInt(10, 95),
        viewers: randomInt(5, 1500),
        vu: Array.from({ length: 12 }, () => Math.random())
      };
      this.emit({ type: 'metrics', data: metricPayload });

      if (Math.random() > 0.6) {
        const message: ConsolePayload = {
          level: LEVELS[randomInt(0, LEVELS.length - 1)],
          message: `Mock log ${new Date().toLocaleTimeString()} - ${Math.random()
            .toString(16)
            .slice(2, 7)}`
        };
        this.emit({ type: 'console', data: message });
      }

      if (Math.random() > 0.75) {
        this.emit({
          type: 'expression',
          data: { expression: EXPRESSIONS[randomInt(0, EXPRESSIONS.length - 1)] }
        });
      }
    }, this.interval);
  }

  disconnect(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  onMessage(callback: (message: TelemetryMessage) => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  private emit(message: TelemetryMessage): void {
    for (const listener of this.listeners) {
      listener(message);
    }
  }
}

export interface TelemetryStream {
  socket: MockTelemetrySocket;
  subscribe: Readable<TelemetryMessage | null>['subscribe'];
}

export function createTelemetryStream(interval = 1200): TelemetryStream {
  const socket = new MockTelemetrySocket(interval);
  const store = readable<TelemetryMessage | null>(null, (set) => {
    socket.connect();
    const unsubscribe = socket.onMessage((message) => set(message));
    return () => {
      unsubscribe();
      socket.disconnect();
    };
  });

  return { socket, subscribe: store.subscribe };
}
