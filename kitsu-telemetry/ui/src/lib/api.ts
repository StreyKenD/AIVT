const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8001';

type EventFilters = {
  limit?: number;
  event_type?: string;
  source?: string;
};

export async function fetchRecentEvents(filters: EventFilters = {}) {
  const params = new URLSearchParams();
  if (filters.limit) params.set('limit', String(filters.limit));
  if (filters.event_type) params.set('event_type', filters.event_type);
  if (filters.source) params.set('source', filters.source);
  const response = await fetch(`${API_BASE}/events?${params.toString()}`);
  if (!response.ok) {
    throw new Error('Não foi possível obter eventos.');
  }
  return response.json();
}

export async function sendTelemetry(payload: Record<string, unknown>) {
  const response = await fetch(`${API_BASE}/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!response.ok) {
    throw new Error('Falha ao enviar evento.');
  }
  return response.json();
}

export async function downloadTelemetryCsv(): Promise<string> {
  const response = await fetch(`${API_BASE}/events/export`);
  if (!response.ok) {
    throw new Error('Falha ao exportar CSV.');
  }
  return response.text();
}
