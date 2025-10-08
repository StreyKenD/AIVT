/// <reference types="vitest" />

import { describe, expect, it } from 'vitest';
import { createTelemetryStream, type TelemetryMessage } from './ws';

const SOCKET_STATE_CONNECTING = 0;
const SOCKET_STATE_OPEN = 1;
const SOCKET_STATE_CLOSED = 3;

class FakeWebSocket {
  readyState = SOCKET_STATE_CONNECTING;
  onopen: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onclose: ((event: CloseEvent) => void) | null = null;

  emitOpen() {
    this.readyState = SOCKET_STATE_OPEN;
    this.onopen?.({} as Event);
  }

  emitMessage(payload: string) {
    this.onmessage?.({ data: payload } as MessageEvent<string>);
  }

  emitClose() {
    this.readyState = SOCKET_STATE_CLOSED;
    this.onclose?.({} as CloseEvent);
  }

  close() {
    this.emitClose();
  }
}

describe('createTelemetryStream', () => {
  it('emits telemetry messages for newline-delimited payloads', () => {
    const sockets: FakeWebSocket[] = [];
    const stream = createTelemetryStream({
      url: 'ws://telemetry.test',
      socketFactory: () => {
        const socket = new FakeWebSocket();
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      scheduleReconnect: (handler) => ({ handler } as unknown as ReturnType<typeof setTimeout>),
      cancelReconnect: () => {}
    });

    const received: TelemetryMessage[] = [];
    const unsubscribe = stream.subscribe((message) => {
      if (message) {
        received.push(message);
      }
    });

    const [socket] = sockets;
    socket.emitOpen();

    const timestamp = Math.floor(Date.now() / 1000);
    const statusPayload: TelemetryMessage = {
      type: 'status',
      payload: {
        status: 'ok',
        persona: {
          style: 'kawaii',
          chaos_level: 0.2,
          energy: 0.8,
          family_mode: true,
          last_updated: timestamp
        },
        modules: {
          asr_worker: { state: 'online', latency_ms: 23.5, last_updated: timestamp },
          tts_worker: { state: 'offline', latency_ms: 0.0, last_updated: timestamp }
        },
        scene: 'Starting Soon',
        last_expression: { expression: 'smile', intensity: 0.6, ts: timestamp },
        last_tts: { text: 'Welcome', voice: 'en-US', ts: timestamp },
        memory: {
          buffer_length: 2,
          summary_interval: 6,
          restore_enabled: true,
          current_summary: {
            id: 42,
            summary_text: 'Summary',
            mood_state: 'calm',
            knobs: { focus: 0.2, energy: 0.8 },
            ts: timestamp
          }
        },
        restore_context: false
      }
    };
    const moduleTogglePayload: TelemetryMessage = {
      type: 'module.toggle',
      module: 'tts_worker',
      enabled: true
    };
    const expressionPayload: TelemetryMessage = {
      type: 'expression',
      data: { expression: 'Happy' }
    };
    const vtsExpressionPayload: TelemetryMessage = {
      type: 'vts_expression',
      data: { expression: 'wink', intensity: 0.7, ts: timestamp }
    };

    const expressionString = JSON.stringify(expressionPayload);
    const splitIndex = Math.floor(expressionString.length / 2);

    socket.emitMessage(
      `${JSON.stringify(statusPayload)}\n${JSON.stringify(moduleTogglePayload)}\n${expressionString.slice(0, splitIndex)}`
    );
    expect(received).toHaveLength(2);
    socket.emitMessage(`${expressionString.slice(splitIndex)}\n`);
    expect(received).toHaveLength(3);
    socket.emitMessage(`${JSON.stringify(vtsExpressionPayload)}\n`);
    expect(received).toHaveLength(4);
    expect(received[0]).toEqual(statusPayload);
    expect(received[1]).toEqual(moduleTogglePayload);
    expect(received[2]).toEqual(expressionPayload);
    expect(received[3]).toEqual(vtsExpressionPayload);

    unsubscribe();
    stream.disconnect();
  });

  it('applies exponential backoff to reconnection attempts', () => {
    const sockets: FakeWebSocket[] = [];
    const delays: number[] = [];
    const pendingReconnects: Array<() => void> = [];

    const stream = createTelemetryStream({
      url: 'ws://telemetry.test',
      socketFactory: () => {
        const socket = new FakeWebSocket();
        sockets.push(socket);
        return socket as unknown as WebSocket;
      },
      scheduleReconnect: (handler, delay) => {
        delays.push(delay);
        pendingReconnects.push(handler);
        return {} as unknown as ReturnType<typeof setTimeout>;
      },
      cancelReconnect: () => {}
    });

    const unsubscribe = stream.subscribe(() => {});
    const expectedDelays = [500, 1000, 2000, 4000, 5000, 10000];

    for (const expected of expectedDelays) {
      const currentSocket = sockets[sockets.length - 1];
      currentSocket.emitClose();
      expect(delays[delays.length - 1]).toBe(expected);

      const reconnect = pendingReconnects.pop();
      reconnect?.();
    }

    unsubscribe();
    stream.disconnect();
    expect(delays).toEqual(expectedDelays);
  });
});
