<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { createTelemetryStream, type TelemetryMessage } from '$lib/ws';
  import {
    ApiError,
    applyPreset,
    downloadTelemetryCsv,
    fetchLatestMetrics,
    fetchSoakResults,
    fetchControlStatus,
    getOrchestratorStatus,
    fetchLogs,
    getLlmStatus,
    requestTTS,
    setGlobalMute,
    setOBSScene,
    setPersona,
    setVTSExpression,
    startLlm,
    triggerPanic,
    toggleModule,
    type ExpressionSnapshot,
    type LatestMetrics,
    type LlmStatus,
    type LogEntry,
    type LogQuery,
    type MemorySummary,
    type ModuleStatus,
    type OrchestratorStatus,
    type PersonaSnapshot,
    type SoakResult,
    type TTSRecord
  } from '$lib/api';
  import LatencyChart from '$lib/LatencyChart.svelte';
  import StatusBadge from '$lib/StatusBadge.svelte';
  import type { LatencyPoint, StatusVariant } from '$lib/types';

  const telemetry = createTelemetryStream();
  const currentYear = new Date().getFullYear();

  const personaStyles = ['kawaii', 'chaotic', 'calm'] as const;

  type PersonaFormState = {
    style: string;
    chaos: number;
    energy: number;
    family_mode: boolean;
  };

  type FeedbackState = { type: 'success' | 'error'; text: string } | null;

  type ExpressionOption = { label: string; value: string; intensity: number };
  type LatencySeries = Record<string, LatencyPoint[]>;
  type ControlState = NonNullable<OrchestratorStatus['control']>;

  const expressionOptions: ExpressionOption[] = [
    { label: 'Smile', value: 'smile', intensity: 0.7 },
    { label: 'Surprised', value: 'surprised', intensity: 0.8 },
    { label: 'Relaxed', value: 'calm', intensity: 0.5 },
    { label: 'Thoughtful', value: 'thinking', intensity: 0.6 },
    { label: 'Sleepy', value: 'sleepy', intensity: 0.4 }
  ];

  const presetOptions = [
    { value: 'default', label: 'Default', description: 'Kawaii balance (50% energy)' },
    { value: 'cozy', label: 'Cozy', description: 'Calm tone for intimate chat segments' },
    { value: 'hype', label: 'Hype', description: 'Maximum energy for announcements and raids' }
  ];

  const latencySeries: LatencySeries = {
    asr_worker: [],
    policy_worker: [],
    tts_worker: []
  };
  const LATENCY_MAX_POINTS = 24;
  const METRIC_POLL_INTERVAL_MS = 5000;
  const SOAK_POLL_INTERVAL_MS = 20000;
  const STATUS_POLL_INTERVAL_MS = 15000;
  const LOGS_POLL_INTERVAL_MS = 20000;
  const MAX_LOG_ENTRIES = 200;
  const LOG_GROUP_WINDOW_MS = 60000;
  const LOG_LEVEL_OPTIONS = ['debug', 'info', 'warning', 'error', 'critical'] as const;
  type LogSinceOption = { value: string; label: string; ms: number | null };
  const LOG_SINCE_OPTIONS: LogSinceOption[] = [
    { value: 'all', label: 'All time', ms: null },
    { value: '5m', label: 'Last 5 minutes', ms: 5 * 60_000 },
    { value: '15m', label: 'Last 15 minutes', ms: 15 * 60_000 },
    { value: '1h', label: 'Last hour', ms: 60 * 60_000 },
    { value: '4h', label: 'Last 4 hours', ms: 4 * 60 * 60_000 },
    { value: '12h', label: 'Last 12 hours', ms: 12 * 60 * 60_000 },
    { value: '24h', label: 'Last day', ms: 24 * 60 * 60_000 }
  ];
  const FEEDBACK_TIMEOUT_MS = 5000;
  const latencyColors: Record<string, string> = {
    asr_worker: '#60a5fa',
    policy_worker: '#facc15',
    tts_worker: '#34d399'
  };

  type DisplayLogEntry = LogEntry & {
    count: number;
    earliestMs: number | null;
    latestMs: number | null;
    earliestTs: string | null;
    latestTs: string | null;
  };

  type InternalDisplayLogEntry = DisplayLogEntry & { groupKey: string };

  const relativeTimeFormatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });

  const TABS = [
    {
      id: 'overview' as const,
      label: 'Overview',
      blurb: 'At-a-glance persona & module status'
    },
    {
      id: 'controls' as const,
      label: 'Control Room',
      blurb: 'Persona tuning, scenes, expressions, safety'
    },
    {
      id: 'insights' as const,
      label: 'Insights',
      blurb: 'Latency, soak harness, and memory summaries'
    },
    {
      id: 'diagnostics' as const,
      label: 'Diagnostics',
      blurb: 'Logs, recent errors, and console feed'
    }
  ];

  type TabId = (typeof TABS)[number]['id'];
  let activeTab: TabId = 'overview';

  const STATUS_VARIANTS: Record<StatusVariant, { label: string; classes: string; dot: string }> = {
    online: {
      label: 'Online',
      classes: 'border-emerald-400/60 bg-emerald-500/10 text-emerald-100 ring-1 ring-emerald-400/30',
      dot: 'bg-emerald-400'
    },
    degraded: {
      label: 'Degraded',
      classes: 'border-amber-400/60 bg-amber-500/10 text-amber-100 ring-1 ring-amber-400/30',
      dot: 'bg-amber-400'
    },
    offline: {
      label: 'Offline',
      classes: 'border-rose-400/60 bg-rose-500/10 text-rose-100 ring-1 ring-rose-400/30',
      dot: 'bg-rose-400'
    },
    unknown: {
      label: 'Unknown',
      classes: 'border-slate-400/40 bg-slate-600/20 text-slate-200 ring-1 ring-slate-400/20',
      dot: 'bg-slate-400'
    }
  };

  const STATUS_ALIASES: Record<string, StatusVariant> = {
    ok: 'online',
    healthy: 'online',
    ready: 'online',
    online: 'online',
    degraded: 'degraded',
    warning: 'degraded',
    unstable: 'degraded',
    offline: 'offline',
    error: 'offline',
    failed: 'offline',
    unknown: 'unknown'
  };

  function normalizeStatus(status: string | null | undefined): StatusVariant {
    if (!status) {
      return 'unknown';
    }
    const key = status.toLowerCase();
    if (key in STATUS_ALIASES) {
      return STATUS_ALIASES[key];
    }
    if (key in STATUS_VARIANTS) {
      return key as StatusVariant;
    }
    return 'unknown';
  }

  function statusLabel(status: string | null | undefined): string {
    return STATUS_VARIANTS[normalizeStatus(status)].label;
  }

  function normalizeLlmStatus(status: string | null | undefined): StatusVariant {
    if (!status) {
      return 'unknown';
    }
    if (status.toLowerCase() === 'unmanaged') {
      return 'unknown';
    }
    return normalizeStatus(status);
  }

  function llmStatusLabel(status: string | null | undefined): string {
    if (!status) {
      return 'Unknown';
    }
    if (status.toLowerCase() === 'unmanaged') {
      return 'Unmanaged';
    }
    return statusLabel(status);
  }

  function logLevelBadgeClass(level: string): string {
    const normalized = (level ?? '').toLowerCase();
    switch (normalized) {
      case 'error':
        return 'border border-rose-400/50 bg-rose-500/20 text-rose-100';
      case 'warning':
        return 'border border-amber-400/40 bg-amber-500/15 text-amber-100';
      case 'debug':
        return 'border border-sky-400/40 bg-sky-500/15 text-sky-100';
      case 'info':
      default:
        return 'border border-slate-500/40 bg-slate-600/30 text-slate-100';
    }
  }

  let orchestrator: OrchestratorStatus | null = null;
  let modulePending: Record<string, boolean> = {};
  let personaForm: PersonaFormState = { style: 'kawaii', chaos: 20, energy: 50, family_mode: true };
  let sceneInput = '';
  let ttsText = '';
  let ttsVoice = '';
  let personaSubmitting = false;
  let sceneSubmitting = false;
  let ttsSubmitting = false;
  let expressionPending = false;
  let controlState: ControlState = {
    tts_muted: false,
    panic_at: null,
    panic_reason: null,
    active_preset: 'default'
  };
  let panicReason = '';
  let loadingStatus = true;
  let refreshing = false;
  let loadError = '';
  let feedback: FeedbackState = null;
  let mutePending = false;
  let panicPending = false;
  let presetPending: string | null = null;
  let csvPending = false;
  let controlBackendAvailable = true;
  let orchestratorFallbackAttempted = false;
  let llmStatus: LlmStatus | null = null;
  let llmPending = false;

  let metrics: LatestMetrics | null = null;
  let metricsError = '';
  let metricsLoading = true;
  let soakResults: SoakResult[] = [];
  let soakLoading = true;
  let soakError = '';
  let logs: LogEntry[] = [];
  let logsLoading = false;
  let logsError = '';
  let displayLogs: DisplayLogEntry[] = [];
  let logServiceOptions: string[] = [];
  let logServiceFilter = 'all';
  let logLevelFilter = 'all';
  let logContainsFilter = '';
  let logSinceValue = 'all';
  let logSearchDebounce: ReturnType<typeof setTimeout> | null = null;
  let pendingLogRefresh: { showNotice: boolean } | null = null;

  let metricsTimer: ReturnType<typeof setInterval> | null = null;
  let soakTimer: ReturnType<typeof setInterval> | null = null;
  let statusTimer: ReturnType<typeof setInterval> | null = null;
  let logsTimer: ReturnType<typeof setInterval> | null = null;
  let feedbackTimer: ReturnType<typeof setTimeout> | null = null;
  let componentDestroyed = false;
  let pollingPaused = false;

  $: currentExpression = orchestrator?.last_expression ?? null;
  $: expressionIntensity = currentExpression ? Math.round((currentExpression.intensity ?? 0) * 100) : 0;
  $: currentExpressionLabel = currentExpression ? currentExpression.expression : 'n/a';
  $: personaEnergyPercent = Math.round(personaForm.energy);
  $: personaChaosPercent = Math.round(personaForm.chaos);
  $: displayLogs = groupLogEntries(logs);
  $: trimmedLogSearchTerm = logContainsFilter.trim();
  $: hasActiveLogFilters =
    logLevelFilter !== 'all' ||
    logServiceFilter !== 'all' ||
    trimmedLogSearchTerm.length > 0 ||
    logSinceValue !== 'all';

  onMount(() => {
    componentDestroyed = false;
    const unsubscribe = telemetry.subscribe(handleTelemetry);

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        pausePolling();
      } else {
        resumePolling(true);
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);

    void fetchStatus(true);
    void refreshMetrics(true);
    void refreshSoak(true);
    resumePolling();

    return () => {
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      unsubscribe();
      telemetry.disconnect();
      pausePolling();
    };
  });

  onDestroy(() => {
    componentDestroyed = true;
    pausePolling();
    if (feedbackTimer) {
      clearTimeout(feedbackTimer);
      feedbackTimer = null;
    }
    clearLogSearchDebounce();
    stopLogsPolling();
  });

  function appendLogEntry(entry: LogEntry) {
    updateServiceOptions([entry]);
    if (!logMatchesFilters(entry)) {
      return;
    }
    logs = [entry, ...logs].slice(0, MAX_LOG_ENTRIES);
  }

  async function refreshLogs(showNotice = false) {
    if (logsLoading) {
      pendingLogRefresh = {
        showNotice: (pendingLogRefresh?.showNotice ?? false) || showNotice
      };
      return;
    }
    logsLoading = true;
    logsError = '';
    try {
      const items = await fetchLogs(buildLogQuery());
      if (componentDestroyed) return;
      logs = items;
      updateServiceOptions(items);
      if (showNotice) {
        setFeedback('success', 'Logs refreshed.');
      }
    } catch (error) {
      if (componentDestroyed) return;
      logsError = getErrorMessage(error, 'Failed to load logs.');
    } finally {
      logsLoading = false;
      if (componentDestroyed) {
        pendingLogRefresh = null;
        return;
      }
      if (pendingLogRefresh) {
        const next = pendingLogRefresh;
        pendingLogRefresh = null;
        void refreshLogs(next.showNotice);
      }
    }
  }

  function buildLogQuery(): LogQuery {
    const query: LogQuery = {
      limit: MAX_LOG_ENTRIES,
      order: 'desc'
    };
    if (logServiceFilter !== 'all') {
      query.service = logServiceFilter;
    }
    if (logLevelFilter !== 'all') {
      query.level = logLevelFilter;
    }
    const contains = logContainsFilter.trim();
    if (contains) {
      query.contains = contains;
    }
    const sinceIso = resolveSinceIso(logSinceValue);
    if (sinceIso) {
      query.since = sinceIso;
    }
    return query;
  }

  function resolveSinceMs(value: string): number | null {
    const option = LOG_SINCE_OPTIONS.find((item) => item.value === value);
    if (!option || option.ms === null) {
      return null;
    }
    return Math.max(Date.now() - option.ms, 0);
  }

  function resolveSinceIso(value: string): string | undefined {
    const cutoff = resolveSinceMs(value);
    return cutoff === null ? undefined : new Date(cutoff).toISOString();
  }

  function updateServiceOptions(items: LogEntry[]): void {
    if (!items.length) {
      return;
    }
    const existing = new Set(logServiceOptions);
    let mutated = false;
    for (const entry of items) {
      const name = entry.service?.trim();
      if (!name) continue;
      if (!existing.has(name)) {
        existing.add(name);
        mutated = true;
      }
    }
    if (mutated) {
      logServiceOptions = Array.from(existing).sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
    }
  }

  function handleLogServiceChange(event: Event) {
    const target = event.target as HTMLSelectElement | null;
    logServiceFilter = target?.value ?? 'all';
    void refreshLogs(false);
  }

  function handleLogLevelChange(event: Event) {
    const target = event.target as HTMLSelectElement | null;
    logLevelFilter = target?.value ?? 'all';
    void refreshLogs(false);
  }

  function handleLogSinceChange(event: Event) {
    const target = event.target as HTMLSelectElement | null;
    logSinceValue = target?.value ?? 'all';
    void refreshLogs(false);
  }

  function clearLogSearchDebounce() {
    if (logSearchDebounce) {
      clearTimeout(logSearchDebounce);
      logSearchDebounce = null;
    }
  }

  function scheduleLogSearchRefresh() {
    clearLogSearchDebounce();
    const trigger = () => {
      if (logsLoading) {
        logSearchDebounce = setTimeout(trigger, 200);
        return;
      }
      logSearchDebounce = null;
      void refreshLogs(false);
    };
    logSearchDebounce = setTimeout(trigger, 400);
  }

  function handleLogSearchInput(event: Event) {
    const target = event.target as HTMLInputElement | null;
    logContainsFilter = target?.value ?? '';
    scheduleLogSearchRefresh();
  }

  function handleClearLogFilters() {
    const hadFilters = hasActiveLogFilters;
    logServiceFilter = 'all';
    logLevelFilter = 'all';
    logContainsFilter = '';
    logSinceValue = 'all';
    clearLogSearchDebounce();
    if (hadFilters) {
      void refreshLogs(true);
    }
  }

  function escapeRegExp(value: string): string {
    return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  function highlightSegments(text: string | null | undefined, needle: string): Array<{ value: string; match: boolean }> {
    const source = text ?? '';
    const query = needle.trim();
    if (!query) {
      return [{ value: source, match: false }];
    }
    try {
      const regex = new RegExp(`(${escapeRegExp(query)})`, 'ig');
      const parts = source.split(regex);
      const segments: Array<{ value: string; match: boolean }> = [];
      parts.forEach((part, index) => {
        if (!part) {
          return;
        }
        segments.push({ value: part, match: index % 2 === 1 });
      });
      return segments.length ? segments : [{ value: source, match: false }];
    } catch {
      return [{ value: source, match: false }];
    }
  }

  function logMatchesFilters(entry: LogEntry): boolean {
    if (logServiceFilter !== 'all' && entry.service !== logServiceFilter) {
      return false;
    }
    if (logLevelFilter !== 'all' && (entry.level ?? '').toLowerCase() !== logLevelFilter) {
      return false;
    }
    const contains = logContainsFilter.trim();
    if (contains) {
      const needle = contains.toLowerCase();
      const haystacks = [
        entry.message ?? '',
        entry.logger ?? '',
        entry.file ?? '',
        entry.exception ?? '',
        entry.extra ? JSON.stringify(entry.extra) : ''
      ];
      const matched = haystacks.some((value) => value.toLowerCase().includes(needle));
      if (!matched) {
        return false;
      }
    }
    const cutoff = resolveSinceMs(logSinceValue);
    if (cutoff !== null) {
      const timestampMs = toMillis(entry.ts);
      if (timestampMs === null || timestampMs < cutoff) {
        return false;
      }
    }
    return true;
  }

  function startLogsPolling(runImmediately = false) {
    if (logsTimer) {
      return;
    }
    logsTimer = setInterval(() => void refreshLogs(false), LOGS_POLL_INTERVAL_MS);
    if (runImmediately) {
      void refreshLogs(false);
    }
  }

  function stopLogsPolling() {
    if (logsTimer) {
      clearInterval(logsTimer);
      logsTimer = null;
    }
  }

  $: {
    if (activeTab === 'diagnostics' && !componentDestroyed) {
      startLogsPolling(true);
    } else if (logsTimer) {
      stopLogsPolling();
    }
  }

  async function fetchStatus(initial = false, showNotice = false) {
    if (!initial && (refreshing || loadingStatus)) {
      return;
    }
    if (initial) {
      loadingStatus = true;
    } else {
      refreshing = true;
    }
    loadError = '';

    const attemptFallback = async (baseError?: unknown, force = false) => {
      if (componentDestroyed) return;
      if (orchestratorFallbackAttempted && !force) {
        loadError = getErrorMessage(
          baseError instanceof Error ? baseError : baseError ?? new Error('Control backend unavailable.'),
          'Control backend offline. Start the control service to restore full functionality.'
        );
        return;
      }
      orchestratorFallbackAttempted = true;
      try {
        const fallback = await getOrchestratorStatus();
        if (componentDestroyed) return;
        applySnapshot(fallback);
        llmStatus = null;
        metricsLoading = false;
        metricsError = 'Metrics unavailable while control backend is offline.';
        loadError = 'Control backend unreachable. Showing read-only orchestrator status.';
      } catch (innerError) {
        if (componentDestroyed) return;
        llmStatus = null;
        metricsLoading = false;
        metricsError = 'Metrics unavailable while control backend is offline.';
        loadError = getErrorMessage(
          innerError instanceof Error ? innerError : baseError ?? innerError,
          'Failed to load orchestrator status. Ensure the orchestrator is running.'
        );
      }
    };

    const shouldQueryControl = controlBackendAvailable || showNotice;

    if (shouldQueryControl) {
      try {
        const snapshot = await fetchControlStatus();
        if (componentDestroyed) return;
        controlBackendAvailable = true;
        orchestratorFallbackAttempted = false;
        applySnapshot(snapshot.status);
        llmStatus = snapshot.ollama ?? null;
        if (snapshot.metrics) {
          metrics = snapshot.metrics;
          updateLatencySeries(snapshot.metrics);
          metricsLoading = false;
          metricsError = '';
        }
        if (showNotice) {
          setFeedback('success', 'Status updated.');
        }
      } catch (error) {
        if (componentDestroyed) return;
        controlBackendAvailable = false;
        await attemptFallback(error, showNotice);
      }
    } else {
      await attemptFallback(undefined, showNotice);
    }

    if (componentDestroyed) return;
    if (initial) {
      loadingStatus = false;
    } else {
      refreshing = false;
    }
  }

  function setFeedback(type: 'success' | 'error', text: string) {
    feedback = { type, text };
    if (feedbackTimer) {
      clearTimeout(feedbackTimer);
    }
    feedbackTimer = setTimeout(() => {
      feedback = null;
      feedbackTimer = null;
    }, FEEDBACK_TIMEOUT_MS);
  }

  function handleTelemetry(message: TelemetryMessage | null) {
    if (!message || componentDestroyed) return;

    if (message.type === 'status') {
      applySnapshot(message.payload);
      return;
    }

    if (!orchestrator && message.type !== 'console') {
      return;
    }

    switch (message.type) {
      case 'module.toggle': {
        const previous = orchestrator.modules[message.module];
        const enabledFlag = Boolean(message.enabled);
        const resolvedState =
          typeof message.state === 'string' && message.state.length
            ? (message.state as string)
            : enabledFlag
              ? previous?.state ?? 'online'
              : 'offline';
        const timestamp = Date.now() / 1000;
        const updated: ModuleStatus = previous
          ? {
              ...previous,
              enabled: enabledFlag,
              state: resolvedState,
              last_updated: timestamp
            }
          : {
              enabled: enabledFlag,
              state: resolvedState,
              latency_ms: 0,
              last_updated: timestamp
            };
        orchestrator = {
          ...orchestrator,
          modules: { ...orchestrator.modules, [message.module]: updated }
        };
        modulePending = { ...modulePending, [message.module]: false };
        break;
      }
      case 'persona_update': {
        const snapshot = clonePersona(message.persona);
        orchestrator = { ...orchestrator, persona: snapshot };
        personaForm = toPersonaForm(snapshot);
        break;
      }
      case 'tts_request': {
        orchestrator = { ...orchestrator, last_tts: cloneTts(message.data) };
        break;
      }
      case 'obs_scene': {
        orchestrator = { ...orchestrator, scene: message.scene };
        sceneInput = message.scene;
        sceneSubmitting = false;
        break;
      }
      case 'vts_expression': {
        orchestrator = { ...orchestrator, last_expression: cloneExpression(message.data) };
        expressionPending = false;
        break;
      }
      case 'memory_summary': {
        orchestrator = {
          ...orchestrator,
          memory: { ...orchestrator.memory, current_summary: cloneSummary(message.summary) }
        };
        break;
      }
      case 'control.mute': {
        controlState = { ...controlState, tts_muted: Boolean(message.muted) };
        modulePending = { ...modulePending, tts_worker: false };
        break;
      }
      case 'control.panic': {
        controlState = {
          ...controlState,
          panic_at: message.ts ?? Date.now() / 1000,
          panic_reason: 'reason' in message ? (message as { reason?: string }).reason ?? null : null
        };
        break;
      }
      case 'control.preset': {
        const presetName = (message as { preset?: string }).preset ?? controlState.active_preset;
        controlState = { ...controlState, active_preset: presetName };
        break;
      }
      case 'console': {
        const entry: LogEntry = {
          ts: new Date().toISOString(),
          service: 'orchestrator',
          level: message.data.level ?? 'info',
          message: message.data.message,
          logger: null,
          extra: null,
          exception: null,
          file: 'stream'
        };
        appendLogEntry(entry);
        break;
      }
      case 'expression': {
        const synthetic: ExpressionSnapshot = {
          expression: message.data.expression,
          intensity: orchestrator.last_expression?.intensity ?? 0.5,
          ts: Date.now() / 1000
        };
        orchestrator = { ...orchestrator, last_expression: cloneExpression(synthetic) };
        break;
      }
      default:
        break;
    }
  }

  function applySnapshot(snapshot: OrchestratorStatus) {
    const cloned = cloneStatus(snapshot);
    orchestrator = cloned;
    personaForm = toPersonaForm(cloned.persona);
    sceneInput = cloned.scene;
    modulePending = Object.fromEntries(Object.keys(cloned.modules).map((name) => [name, false]));
    expressionPending = false;
    sceneSubmitting = false;
    ttsSubmitting = false;
    personaSubmitting = false;
    controlState = cloneControl(cloned.control);
  }

  function cloneStatus(snapshot: OrchestratorStatus): OrchestratorStatus {
    return {
      ...snapshot,
      persona: clonePersona(snapshot.persona),
      modules: Object.fromEntries(
        Object.entries(snapshot.modules).map(([name, info]) => [
          name,
          {
            ...info,
            enabled: info.enabled ?? normalizeStatus(info.state) === 'online'
          }
        ])
      ),
      last_expression: snapshot.last_expression ? cloneExpression(snapshot.last_expression) : null,
      last_tts: snapshot.last_tts ? cloneTts(snapshot.last_tts) : null,
      memory: {
        ...snapshot.memory,
        current_summary: snapshot.memory.current_summary
          ? cloneSummary(snapshot.memory.current_summary)
          : null
      },
      control: snapshot.control ? cloneControl(snapshot.control) : undefined
    };
  }

  function clonePersona(persona: PersonaSnapshot): PersonaSnapshot {
    return { ...persona };
  }

  function cloneExpression(expression: ExpressionSnapshot): ExpressionSnapshot {
    return { ...expression };
  }

  function cloneTts(record: TTSRecord): TTSRecord {
    return { ...record };
  }

  function cloneSummary(summary: MemorySummary): MemorySummary {
    const { metadata: existingMetadata, ...withLegacy } = summary as MemorySummary & {
      knobs?: Record<string, number>;
    };
    const { knobs: legacyKnobs, ...base } = withLegacy;
    const metadata = existingMetadata ?? legacyKnobs ?? {};

    return {
      ...(base as Omit<MemorySummary, 'metadata'>),
      metadata: { ...metadata }
    };
  }

  function cloneControl(control: OrchestratorStatus['control']): ControlState {
    if (!control) {
      return {
        tts_muted: false,
        panic_at: null,
        panic_reason: null,
        active_preset: 'default'
      };
    }
    return { ...control };
  }

  function toPersonaForm(persona: PersonaSnapshot): PersonaFormState {
    return {
      style: persona.style,
      chaos: clampPercentage(persona.chaos_level * 100),
      energy: clampPercentage(persona.energy * 100),
      family_mode: persona.family_mode
    };
  }

  function clampPercentage(value: number): number {
    return Math.round(Math.min(100, Math.max(0, value)));
  }

  function getErrorMessage(error: unknown, fallback: string): string {
    if (error instanceof ApiError) return error.message;
    if (error instanceof Error && error.message) return error.message;
    return fallback;
  }

  function updateLatencySeries(latest: LatestMetrics) {
    const now = Date.now();
    (['asr_worker', 'policy_worker', 'tts_worker'] as const).forEach((key) => {
      const bucket = latest.metrics[key];
      if (!bucket || !bucket.latency_ms || typeof bucket.latency_ms.avg !== 'number') {
        return;
      }
      const series = latencySeries[key];
      series.push({ ts: now, value: bucket.latency_ms.avg });
      if (series.length > LATENCY_MAX_POINTS) {
        series.splice(0, series.length - LATENCY_MAX_POINTS);
      }
    });
  }

  function pausePolling() {
    pollingPaused = true;
    stopLogsPolling();
    if (metricsTimer) {
      clearInterval(metricsTimer);
      metricsTimer = null;
    }
    if (soakTimer) {
      clearInterval(soakTimer);
      soakTimer = null;
    }
    if (statusTimer) {
      clearInterval(statusTimer);
      statusTimer = null;
    }
  }

  function resumePolling(runImmediately = false) {
    if (componentDestroyed) {
      return;
    }
    if (!pollingPaused && metricsTimer && soakTimer) {
      return;
    }
    pollingPaused = false;
    if (metricsTimer) {
      clearInterval(metricsTimer);
    }
    if (soakTimer) {
      clearInterval(soakTimer);
    }
    if (statusTimer) {
      clearInterval(statusTimer);
    }
    metricsTimer = setInterval(() => void refreshMetrics(false), METRIC_POLL_INTERVAL_MS);
    soakTimer = setInterval(() => void refreshSoak(false), SOAK_POLL_INTERVAL_MS);
    statusTimer = setInterval(() => {
      void fetchStatus(false);
    }, STATUS_POLL_INTERVAL_MS);
    if (runImmediately) {
      void refreshMetrics(false);
      void refreshSoak(false);
      void fetchStatus(false);
    }
  }

  function getLatencySnapshot(key: keyof LatencySeries): number | null {
    const series = latencySeries[key];
    if (!series.length) return null;
    return series[series.length - 1].value;
  }

  function formatRelativeTimestamp(ts: number | null | undefined): string {
  if (!ts || Number.isNaN(ts)) return 'n/a';
    const millis = ts > 1_000_000_000_000 ? ts : ts * 1000;
    return new Date(millis).toLocaleString();
  }

  async function refreshStatus() {
    if (loadingStatus || refreshing) return;
    await fetchStatus(false, true);
  }

  async function refreshMetrics(initial = false) {
    if (initial) {
      metricsLoading = true;
    }
    metricsError = '';
    try {
      const latest = await fetchLatestMetrics();
      if (componentDestroyed) return;
      metrics = latest;
      updateLatencySeries(latest);
    } catch (error) {
      if (componentDestroyed) return;
      metricsError = getErrorMessage(error, 'Failed to load metrics.');
    } finally {
      if (componentDestroyed) return;
      if (initial) {
        metricsLoading = false;
      }
    }
  }

async function refreshSoak(initial = false) {
  if (initial) {
    soakLoading = true;
  }
  soakError = '';
  try {
    const results = await fetchSoakResults(10);
    if (componentDestroyed) return;
    soakResults = results;
  } catch (error) {
    if (componentDestroyed) return;
    soakError = getErrorMessage(error, 'Failed to load soak test results.');
  } finally {
    if (componentDestroyed) return;
    if (initial) {
      soakLoading = false;
    }
  }
  }

  async function handleModuleToggle(module: string, enabled: boolean) {
    if (!orchestrator) return;
    const current = orchestrator.modules[module];
    const previous = current ? { ...current } : undefined;

    const timestamp = Date.now() / 1000;
    const nextState = enabled ? current?.state ?? 'online' : 'offline';
    const updated: ModuleStatus = current
      ? { ...current, enabled, state: nextState, last_updated: timestamp }
      : { enabled, state: nextState, latency_ms: 0, last_updated: timestamp };

    orchestrator = {
      ...orchestrator,
      modules: { ...orchestrator.modules, [module]: updated }
    };
    modulePending = { ...modulePending, [module]: true };

    try {
      const response = await toggleModule(module, enabled);
      const finalState =
        typeof response.state === 'string' && response.state.trim() ? response.state : nextState;
      orchestrator = {
        ...orchestrator,
        modules: {
          ...orchestrator.modules,
          [module]: {
            enabled: response.enabled ?? enabled,
            state: finalState,
            latency_ms: updated.latency_ms,
            last_updated: Date.now() / 1000
          }
        }
      };
      setFeedback('success', `Module ${module} ${response.enabled ? 'enabled' : 'disabled'}.`);
    } catch (error) {
      if (previous) {
        orchestrator = {
          ...orchestrator,
          modules: { ...orchestrator.modules, [module]: previous }
        };
      }
      setFeedback('error', getErrorMessage(error, 'Could not toggle module.'));
    } finally {
      modulePending = { ...modulePending, [module]: false };
    }
  }

  async function submitPersona() {
    if (!orchestrator) return;
    personaSubmitting = true;
    try {
      const payload = {
        style: personaForm.style,
        chaos_level: personaForm.chaos / 100,
        energy: personaForm.energy / 100,
        family_mode: personaForm.family_mode
      };
      const response = await setPersona(payload);
      const updated = clonePersona(response.persona);
      orchestrator = { ...orchestrator, persona: updated };
      personaForm = toPersonaForm(updated);
      setFeedback('success', 'Persona updated successfully.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not update persona.'));
    } finally {
      personaSubmitting = false;
    }
  }

  async function submitScene() {
    if (!orchestrator) return;
    const trimmed = sceneInput.trim();
    if (!trimmed) {
      setFeedback('error', 'Provide a valid scene name.');
      return;
    }

    sceneSubmitting = true;
    try {
      await setOBSScene(trimmed);
      orchestrator = { ...orchestrator, scene: trimmed };
      setFeedback('success', 'Scene sent to OBS.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not update the scene.'));
    } finally {
      sceneSubmitting = false;
    }
  }

  async function submitTTS() {
    if (!orchestrator) return;
    const text = ttsText.trim();
    if (!text) {
      setFeedback('error', 'Provide text for TTS.');
      return;
    }

    ttsSubmitting = true;
    try {
      const voice = ttsVoice.trim();
      const response = await requestTTS(voice ? { text, voice } : { text });
      orchestrator = { ...orchestrator, last_tts: cloneTts(response.data) };
      ttsText = '';
      setFeedback('success', 'TTS request sent.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not send the TTS request.'));
    } finally {
      ttsSubmitting = false;
    }
  }

  async function sendExpression(option: ExpressionOption) {
    if (!orchestrator || expressionPending) return;
    expressionPending = true;
    try {
      await setVTSExpression({ expression: option.value, intensity: option.intensity });
      orchestrator = {
        ...orchestrator,
        last_expression: {
          expression: option.value,
          intensity: option.intensity,
          ts: Date.now() / 1000
        }
      };
      setFeedback('success', `Expression ${option.label} sent.`);
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not update the expression.'));
    } finally {
      expressionPending = false;
    }
  }

  async function toggleMuteState() {
    if (mutePending) return;
    const target = !controlState.tts_muted;
    mutePending = true;
    try {
      await setGlobalMute(target);
      controlState = { ...controlState, tts_muted: target };
      setFeedback('success', target ? 'TTS muted.' : 'TTS unmuted.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not toggle mute.'));
    } finally {
      mutePending = false;
    }
  }

  async function sendPanic() {
    if (panicPending) return;
    panicPending = true;
    try {
      const response = await triggerPanic(panicReason);
      controlState = {
        ...controlState,
        panic_at: typeof response.ts === 'number' ? response.ts : Date.now() / 1000,
        panic_reason:
          typeof response.reason === 'string' && response.reason.trim() ? response.reason : panicReason.trim() || null
      };
      panicReason = '';
      setFeedback('success', 'Panic mode triggered.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not trigger panic.'));
    } finally {
      panicPending = false;
    }
  }

  async function applyPresetAction(preset: string) {
    if (presetPending) return;
    presetPending = preset;
    try {
      await applyPreset(preset);
      controlState = { ...controlState, active_preset: preset };
      setFeedback('success', `Preset ${preset} applied.`);
      await fetchStatus(false);
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not apply the preset.'));
    } finally {
      presetPending = null;
    }
  }

  async function downloadCsvExport() {
    if (csvPending) return;
    csvPending = true;
    try {
      const blob = await downloadTelemetryCsv();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const suggested = (blob as Blob & { suggestedName?: string }).suggestedName;
      const fallback = `telemetry-${new Date().toISOString()}.csv`;
      const filename = (suggested && suggested.trim()) || fallback;
      link.download = filename.toLowerCase().endsWith('.csv') ? filename : `${filename}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setFeedback('success', 'CSV exported successfully.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Failed to export CSV.'));
    } finally {
      csvPending = false;
    }
  }

  async function startLlmDaemon() {
    if (llmPending) return;
    llmPending = true;
    try {
      const status = await startLlm();
      llmStatus = status;
      controlBackendAvailable = true;
      orchestratorFallbackAttempted = false;
      setFeedback('success', 'Ollama start requested.');
      await fetchStatus(false);
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Could not start Ollama.'));
      if (controlBackendAvailable) {
        try {
          llmStatus = await getLlmStatus();
          controlBackendAvailable = true;
        } catch {
          llmStatus = null;
          controlBackendAvailable = false;
        }
      } else {
        llmStatus = null;
      }
    } finally {
      llmPending = false;
    }
  }

  function toMillis(ts: string | number | null | undefined): number | null {
    if (typeof ts === 'number' && Number.isFinite(ts)) {
      return ts > 1_000_000_000_000 ? ts : ts * 1000;
    }
    if (typeof ts === 'string') {
      const parsed = Date.parse(ts);
      if (!Number.isNaN(parsed)) {
        return parsed;
      }
      const normalized = ts.endsWith('Z') || /[+-]\d\d:\d\d$/.test(ts) ? ts : `${ts}Z`;
      const reparsed = Date.parse(normalized);
      if (!Number.isNaN(reparsed)) {
        return reparsed;
      }
    }
    return null;
  }

  function formatTimestamp(ts: string | number | null | undefined): string {
    const millis = toMillis(ts);
    if (millis === null) {
      return 'n/a';
    }
    return new Date(millis).toLocaleString();
  }

  function formatRelativeTime(ts: string | number | null | undefined): string {
    const millis = toMillis(ts);
    if (millis === null) {
      return '';
    }
    const diffMs = millis - Date.now();
    const absDiff = Math.abs(diffMs);
    if (absDiff < 1000) {
      return 'just now';
    }
    const units: Array<{ limit: number; divisor: number; unit: Intl.RelativeTimeFormatUnit }> = [
      { limit: 60_000, divisor: 1000, unit: 'second' },
      { limit: 3_600_000, divisor: 60_000, unit: 'minute' },
      { limit: 86_400_000, divisor: 3_600_000, unit: 'hour' },
      { limit: Infinity, divisor: 86_400_000, unit: 'day' }
    ];
    for (const { limit, divisor, unit } of units) {
      if (absDiff < limit) {
        const value = Math.round(diffMs / divisor);
        return relativeTimeFormatter.format(value, unit);
      }
    }
    return '';
  }

  function formatDurationMs(durationMs: number): string {
    const ms = Math.max(0, Math.floor(durationMs));
    if (!Number.isFinite(ms) || ms === 0) {
      return '<1s';
    }
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    const parts: string[] = [];
    if (hours) parts.push(`${hours}h`);
    if (minutes) parts.push(`${minutes}m`);
    if (seconds || !parts.length) parts.push(`${seconds}s`);
    return parts.join(' ');
  }

  function formatOccurrences(entry: DisplayLogEntry): string {
    if (entry.count <= 1) {
      return '';
    }
    if (entry.earliestMs === null || entry.latestMs === null) {
      return `Repeated x${entry.count}`;
    }
    const span = entry.latestMs - entry.earliestMs;
    if (span < 1000) {
      return `Repeated x${entry.count} in <1s`;
    }
    return `Repeated x${entry.count} over ${formatDurationMs(span)}`;
  }

  function buildLogGroupKey(entry: LogEntry): string {
    const extraKey = entry.extra ? JSON.stringify(entry.extra) : '';
    return [entry.service ?? '', entry.level ?? '', entry.message ?? '', entry.logger ?? '', entry.exception ?? '', extraKey].join('|');
  }

  function formatServiceName(service: string | null | undefined): string {
    if (!service) {
      return 'Unknown';
    }
    return service
      .split(/[._-]/g)
      .filter(Boolean)
      .map((segment) => {
        const lower = segment.toLowerCase();
        if (lower.length <= 3) {
          return lower.toUpperCase();
        }
        return lower.charAt(0).toUpperCase() + lower.slice(1);
      })
      .join(' ');
  }

  function groupLogEntries(entries: LogEntry[]): DisplayLogEntry[] {
    const grouped: InternalDisplayLogEntry[] = [];
    for (const entry of entries) {
      const timestampMs = toMillis(entry.ts);
      const key = buildLogGroupKey(entry);
      const last = grouped[grouped.length - 1];
      if (last && last.groupKey === key) {
        const referenceMs = last.latestMs ?? timestampMs;
        const withinWindow =
          referenceMs === null ||
          timestampMs === null ||
          Math.abs(referenceMs - timestampMs) <= LOG_GROUP_WINDOW_MS;
        if (withinWindow) {
          last.count += 1;
          if (timestampMs !== null) {
            if (last.latestMs === null || timestampMs > last.latestMs) {
              last.latestMs = timestampMs;
              last.latestTs = entry.ts;
              last.ts = entry.ts;
            }
            if (last.earliestMs === null || timestampMs < last.earliestMs) {
              last.earliestMs = timestampMs;
              last.earliestTs = entry.ts;
            }
          }
          continue;
        }
      }
      grouped.push({
        ...entry,
        count: 1,
        earliestMs: timestampMs,
        latestMs: timestampMs,
        earliestTs: entry.ts,
        latestTs: entry.ts,
        groupKey: key
      });
    }
    return grouped.map(({ groupKey, ...rest }) => rest);
  }
</script>

<svelte:head>
  <title>Kitsu Orchestrator</title>
</svelte:head>

<div class="relative min-h-screen overflow-hidden bg-slate-950 text-slate-50">
  <div class="pointer-events-none absolute inset-0">
    <div class="absolute -left-24 top-[-12%] h-72 w-72 rounded-full bg-emerald-500/25 blur-3xl"></div>
    <div class="absolute bottom-[-16%] left-1/3 h-80 w-80 rounded-full bg-sky-500/20 blur-3xl"></div>
    <div class="absolute right-[-18%] top-10 h-72 w-72 rounded-full bg-purple-500/20 blur-3xl"></div>
  </div>

  <div class="relative mx-auto flex max-w-6xl flex-col gap-6 px-6 py-12 sm:px-8 lg:px-10">
    <header class="flex flex-col gap-6 rounded-2xl border border-white/10 bg-slate-900/70 p-6 shadow-xl shadow-slate-950/40 backdrop-blur">
      <div class="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <p class="text-xs uppercase tracking-[0.2em] text-slate-400">Operations dashboard</p>
          <h1 class="mt-2 text-4xl font-semibold tracking-tight text-white">Kitsu Orchestrator</h1>
          <p class="mt-3 max-w-2xl text-sm text-slate-300">
            Monitor live worker activity, adjust personas and expressions, and send emergency automations
            without leaving your stream overlay.
          </p>
        </div>
        <div class="flex flex-wrap items-center gap-3">
          {#if !loadingStatus && !loadError}
            <StatusBadge
              status={normalizeStatus(orchestrator?.status)}
              label={statusLabel(orchestrator?.status)}
            />
          {/if}
          <button
            class="inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-emerald-400/90 to-sky-400/90 px-5 py-2 text-sm font-semibold text-slate-950 shadow-lg shadow-emerald-500/30 transition hover:from-emerald-300 hover:to-sky-300 focus:outline-none focus:ring-2 focus:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-70"
            on:click={refreshStatus}
            disabled={loadingStatus || refreshing}
          >
            {#if refreshing}
              <span class="inline-flex items-center gap-2">
                <svg class="h-4 w-4 animate-spin text-slate-900/80" viewBox="0 0 24 24" fill="none">
                  <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                  <path
                    class="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
                  />
                </svg>
                Refreshing
              </span>
            {:else}
              <span class="inline-flex items-center gap-2">
                <svg class="h-4 w-4 text-slate-950/80" viewBox="0 0 24 24" fill="none" stroke="currentColor">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 4v5h.582m15.356 2A8.966 8.966 0 0020 12c0-4.97-4.03-9-9-9-2.386 0-4.56.93-6.176 2.45M4.582 9H9" />
                </svg>
                Refresh status
              </span>
            {/if}
          </button>
        </div>
      </div>
    </header>

    {#if !controlBackendAvailable}
      <div
        class="rounded-xl border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-100 shadow-lg shadow-amber-900/20"
        role="status"
        aria-live="polite"
      >
        Control backend is offline. Showing read-only data directly from the orchestrator. Start the control service on port 8100 to restore full functionality.
      </div>
    {/if}

    {#if feedback}
      <div
        class={`rounded-xl border px-4 py-3 text-sm shadow-lg shadow-slate-950/40 ${
          feedback.type === 'error'
            ? 'border-red-500/60 bg-red-500/15 text-red-100'
            : 'border-emerald-500/60 bg-emerald-500/15 text-emerald-100'
        }`}
        role={feedback.type === 'error' ? 'alert' : 'status'}
        aria-live={feedback.type === 'error' ? 'assertive' : 'polite'}
      >
        {feedback.text}
      </div>
    {/if}

    {#if loadingStatus}
      <div
        class="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-900/60 px-4 py-3 text-sm text-slate-300"
        aria-live="polite"
      >
        <svg class="h-4 w-4 animate-spin text-slate-300" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
        </svg>
        Loading orchestrator status...
      </div>
    {:else if loadError}
      <div
        class="rounded-xl border border-red-500/60 bg-red-500/15 p-4 text-sm text-red-100 shadow-lg shadow-red-500/20"
        role="alert"
        aria-live="assertive"
      >
        <p>{loadError}</p>
        <button
          class="mt-3 inline-flex items-center gap-2 rounded-full bg-red-400 px-3 py-1.5 text-xs font-semibold text-red-950 shadow hover:bg-red-300 focus:outline-none focus:ring-2 focus:ring-red-300"
          on:click={() => fetchStatus(true)}
        >
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M4 4v5h.582m15.356 2A8.966 8.966 0 0020 12c0-4.97-4.03-9-9-9-2.386 0-4.56.93-6.176 2.45M4.582 9H9" />
          </svg>
          Try again
        </button>
      </div>
    {:else if orchestrator}
      <div class="flex flex-col gap-6">
        <div
          class="flex snap-x snap-mandatory gap-2 overflow-x-auto rounded-xl border border-white/10 bg-slate-900/70 p-3 shadow-lg shadow-slate-950/30"
          aria-label="Dashboard sections"
          role="tablist"
        >
          {#each TABS as tab}
            <button
              type="button"
              id={`tab-${tab.id}`}
              role="tab"
              aria-controls={`panel-${tab.id}`}
              aria-selected={activeTab === tab.id}
              class={`min-w-[160px] snap-start rounded-lg px-4 py-3 text-left transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-400 ${
                activeTab === tab.id
                  ? 'bg-emerald-500/90 text-slate-950 shadow-lg shadow-emerald-500/30'
                  : 'bg-slate-900/60 text-slate-300 hover:bg-slate-800/80'
              }`}
              on:click={() => (activeTab = tab.id)}
            >
              <span class="block text-sm font-semibold">{tab.label}</span>
              <span class="mt-1 block text-xs opacity-75">{tab.blurb}</span>
            </button>
          {/each}
        </div>

        <div
          id="panel-overview"
          role="tabpanel"
          aria-labelledby="tab-overview"
          tabindex="0"
          class="space-y-6"
          class:hidden={activeTab !== 'overview'}
        >
          <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-6" aria-label="Quick summary">
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Persona</h2>
          <p class="text-2xl font-semibold capitalize">{orchestrator.persona.style}</p>
          <p class="mt-2 text-sm text-slate-300">
            Energy {personaEnergyPercent}% &middot; Chaos {personaChaosPercent}%
          </p>
          <p class="text-xs text-slate-500">
            Family {orchestrator.persona.family_mode ? 'enabled' : 'disabled'}
          </p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">OBS scene</h2>
          <p class="text-2xl font-semibold">{orchestrator.scene}</p>
          <p class="mt-2 text-xs text-slate-500">Orchestrator status: {orchestrator.status}</p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Active expression</h2>
          <p class="text-2xl font-semibold capitalize">
            {orchestrator.last_expression ? orchestrator.last_expression.expression : 'n/a'}
          </p>
          <p class="mt-2 text-xs text-slate-500">
            Intensity {orchestrator.last_expression ? Math.round(orchestrator.last_expression.intensity * 100) : 0}%
          </p>
          <p class="text-xs text-slate-500">
            Updated {formatTimestamp(orchestrator.last_expression?.ts)}
          </p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Latest TTS</h2>
          <p class="text-base font-medium text-slate-200">
            {orchestrator.last_tts ? orchestrator.last_tts.text : 'No request yet.'}
          </p>
          {#if orchestrator.last_tts}
            <p class="mt-2 text-xs text-slate-500">Voice: {orchestrator.last_tts.voice ?? 'auto'}</p>
            <p class="text-xs text-slate-500">Sent {formatTimestamp(orchestrator.last_tts.ts)}</p>
          {/if}
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">LLM backend</h2>
          {#if llmStatus}
            <div class="mt-2 flex items-center gap-2">
              <StatusBadge
                status={normalizeLlmStatus(llmStatus.status)}
                label={llmStatusLabel(llmStatus.status)}
                tone="soft"
              />
              <span class="text-sm font-semibold text-slate-200 capitalize">{llmStatus.backend}</span>
            </div>
            <p class="mt-2 text-xs text-slate-500 truncate">
              {llmStatus.url} ({llmStatus.is_local ? 'local' : 'remote'})
            </p>
            <p class="text-xs text-slate-500">
              Host {llmStatus.host}:{llmStatus.port}
            </p>
            {#if llmStatus.last_error}
              <p class="mt-2 text-xs text-rose-300">Error: {llmStatus.last_error}</p>
            {/if}
            {#if llmStatus.is_local}
              <button
                class="mt-3 inline-flex items-center gap-2 rounded-full border border-emerald-400/60 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-100 ring-1 ring-emerald-400/20 transition hover:bg-emerald-500/20 focus:outline-none focus:ring-2 focus:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
                on:click={startLlmDaemon}
                disabled={!controlBackendAvailable || llmPending || normalizeLlmStatus(llmStatus.status) === 'online'}
              >
                {#if llmPending}
                  <svg class="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                  </svg>
                  <span>Starting…</span>
                {:else if normalizeLlmStatus(llmStatus.status) === 'online'}
                  <span>Running</span>
                {:else}
                  <span>Start Ollama</span>
                {/if}
              </button>
            {:else}
              <p class="mt-2 text-xs text-slate-500">Managed externally.</p>
            {/if}
          {:else}
            <p class="mt-2 text-sm text-slate-300">
              Control backend unavailable; showing direct orchestrator status.
            </p>
          {/if}
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Operations</h2>
          <p class="text-lg font-semibold capitalize">Preset {controlState.active_preset}</p>
          <p class="mt-2 text-xs text-slate-500">
            TTS {controlState.tts_muted ? 'muted' : 'active'}
          </p>
          <p class="text-xs text-slate-500">
            Last panic {formatRelativeTimestamp(controlState.panic_at)}
          </p>
        </div>
          </section>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Orchestrator modules">
            <header class="mb-4 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div class="flex items-center gap-3">
                <h2 class="text-lg font-medium">Modules</h2>
                <button
                  class="rounded-full border border-slate-500/40 bg-slate-800/60 px-3 py-1.5 text-xs font-semibold text-slate-200 transition hover:bg-slate-700/70 focus:outline-none focus:ring-2 focus:ring-emerald-300 disabled:cursor-not-allowed disabled:opacity-60"
                  on:click={() => fetchStatus(false, true)}
                  disabled={loadingStatus || refreshing}
                  title="Refresh module health from the orchestrator"
                >
                  Refresh modules
                </button>
              </div>
              <p class="text-xs text-slate-400">
                Automatic restore: {orchestrator.restore_context ? 'enabled' : 'disabled'}
              </p>
            </header>
            <ul class="grid gap-3 md:grid-cols-2">
              {#each Object.entries(orchestrator.modules) as [name, module]}
                <li class="rounded-lg border border-white/5 bg-slate-950/50 p-3">
                  <div class="flex items-center justify-between">
                    <div class="flex flex-col gap-1">
                      <div class="flex items-center gap-2">
                        <p class="text-sm font-semibold text-slate-100">{name}</p>
                        <StatusBadge
                          status={normalizeStatus(module.state)}
                          label={statusLabel(module.state)}
                          tone="soft"
                        />
                      </div>
                      <p class="text-xs text-slate-400">
                        Latency {module.latency_ms.toFixed(1)} ms
                      </p>
                      <p class="text-[11px] text-slate-500">
                        Updated {formatTimestamp(module.last_updated)}
                      </p>
                    </div>
                    <label class="inline-flex items-center gap-2 text-xs font-medium">
                      <span class="sr-only">Toggle {name}</span>
                      <input
                        type="checkbox"
                        class="h-4 w-4 rounded border border-slate-600 bg-slate-800"
                        checked={module.enabled}
                        disabled={modulePending[name]}
                        on:change={(event) =>
                          handleModuleToggle(name, (event.currentTarget as HTMLInputElement).checked)}
                      />
                      <span>{module.enabled ? 'Active' : 'Disabled'}</span>
                    </label>
                  </div>
                </li>
              {/each}
            </ul>
          </article>
        </div>

        <div
          id="panel-insights"
          role="tabpanel"
          aria-labelledby="tab-insights"
          tabindex="0"
          class="space-y-6"
          class:hidden={activeTab !== 'insights'}
        >
          <section class="rounded-xl border border-white/10 bg-slate-900/70 p-5 shadow" aria-label="Real-time telemetry">
        <header class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 class="text-lg font-medium">Real-time telemetry</h2>
            <p class="text-xs text-slate-400">Aggregated latencies per stage and soak test overview.</p>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <button
              class="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
              on:click={() => refreshMetrics(false)}
              disabled={metricsLoading}
            >
              {metricsLoading ? 'Loading.....' : 'Refresh metrics'}
            </button>
            <button
              class="rounded-lg bg-emerald-500 px-4 py-2 text-xs font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
              on:click={downloadCsvExport}
              disabled={csvPending}
            >
              {csvPending ? 'Generating CSV...' : 'Export CSV'}
            </button>
          </div>
        </header>

        {#if metricsLoading}
          <p class="mt-4 text-sm text-slate-400" aria-live="polite">Loading metrics...</p>
        {:else if metricsError}
          <div class="mt-4 rounded border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200" role="alert">
            {metricsError}
          </div>
        {:else if metrics}
          <div class="mt-4 grid gap-4 lg:grid-cols-3">
            <LatencyChart
              title="ASR"
              points={latencySeries.asr_worker}
              accent={latencyColors.asr_worker}
            />
            <LatencyChart
              title="Policy/LLM"
              points={latencySeries.policy_worker}
              accent={latencyColors.policy_worker}
            />
            <LatencyChart
              title="TTS"
              points={latencySeries.tts_worker}
              accent={latencyColors.tts_worker}
            />
          </div>
          <div class="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <div class="rounded-lg border border-white/5 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p class="font-semibold text-slate-200">ASR</p>
              <p>Events: {metrics.metrics.asr_worker?.count ?? 0}</p>
              <p>Average latency: {getLatencySnapshot('asr_worker')?.toFixed(1) ?? 'n/a'} ms</p>
            </div>
            <div class="rounded-lg border border-white/5 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p class="font-semibold text-slate-200">Policy</p>
              <p>Events: {metrics.metrics.policy_worker?.count ?? 0}</p>
              <p>Average latency: {getLatencySnapshot('policy_worker')?.toFixed(1) ?? 'n/a'} ms</p>
            </div>
            <div class="rounded-lg border border-white/5 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p class="font-semibold text-slate-200">TTS</p>
              <p>Events: {metrics.metrics.tts_worker?.count ?? 0}</p>
              <p>Average latency: {getLatencySnapshot('tts_worker')?.toFixed(1) ?? 'n/a'} ms</p>
            </div>
          </div>
        {/if}

        <div class="mt-6 border-t border-white/5 pt-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200">Soak test results</h3>
            <button
              class="rounded bg-slate-800 px-3 py-1.5 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
              on:click={() => refreshSoak(false)}
              disabled={soakLoading}
            >
              {soakLoading ? 'Loading.....' : 'Refresh' }
            </button>
          </div>
          {#if soakLoading && !soakResults.length}
            <p class="mt-3 text-xs text-slate-400" aria-live="polite">Loading soak history...</p>
          {:else if soakError}
            <div class="mt-3 rounded border border-red-500/50 bg-red-500/10 p-3 text-xs text-red-200" role="alert">
              {soakError}
            </div>
          {:else if soakResults.length}
            <div class="mt-3 overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-800 text-left text-xs">
                <thead class="bg-slate-950/60 text-slate-400">
                  <tr>
                    <th class="px-3 py-2 font-semibold">Date</th>
                    <th class="px-3 py-2 font-semibold">Status</th>
                    <th class="px-3 py-2 font-semibold">Details</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-900/80 text-slate-200">
                  {#each soakResults as result}
                    <tr>
                      <td class="px-3 py-2 whitespace-nowrap">{new Date(result.ts).toLocaleString()}</td>
                      <td class="px-3 py-2">
                        <StatusBadge
                          status={result.payload.success ? 'online' : 'offline'}
                          label={result.payload.success ? 'Success' : 'Failure'}
                          tone="soft"
                        />
                      </td>
                      <td class="px-3 py-2">
                        <code class="rounded bg-slate-950/70 px-2 py-1 text-[11px] text-slate-300">
                          {JSON.stringify(result.payload)}
                        </code>
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else}
            <p class="mt-3 text-xs text-slate-400">No results recorded yet.</p>
          {/if}
        </div>
      </section>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Memory history">
            <h2 class="text-lg font-medium">Memory</h2>
            <p class="mt-2 text-sm text-slate-300">
              Buffer: {orchestrator.memory.buffer_length} interactions &middot; Summary every {orchestrator.memory.summary_interval} turns
            </p>
            <p class="text-xs text-slate-400">
              Memory restore {orchestrator.memory.restore_enabled ? 'enabled' : 'disabled'}
            </p>
            {#if orchestrator.memory.current_summary}
              <div class="mt-4 rounded border border-white/5 bg-slate-950/40 p-3 text-sm text-slate-200">
                <p class="font-semibold">Summary #{orchestrator.memory.current_summary.id ?? 'n/a'}</p>
                <p class="mt-2 text-slate-300">{orchestrator.memory.current_summary.summary_text}</p>
                <p class="mt-2 text-xs text-slate-400">
                  Mood: {orchestrator.memory.current_summary.mood_state} &middot; Updated {formatTimestamp(orchestrator.memory.current_summary.ts)}
                </p>
              </div>
            {:else}
              <p class="mt-3 text-sm text-slate-400">No summary generated yet.</p>
            {/if}
          </article>
        </div>

        <div
          id="panel-controls"
          role="tabpanel"
          aria-labelledby="tab-controls"
          tabindex="0"
          class="space-y-6"
          class:hidden={activeTab !== 'controls'}
        >
      <section class="grid gap-6 lg:grid-cols-[2fr,1fr]" aria-label="Primary controls">
        <div class="flex flex-col gap-6">
          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Request TTS">
            <h2 class="text-lg font-medium">Request TTS</h2>
            <form class="mt-4 space-y-4" on:submit|preventDefault={submitTTS}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Text
                <textarea
                  class="min-h-[96px] rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={ttsText}
                  aria-label="TTS text"
                  required
                ></textarea>
              </label>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Preferred voice (optional)
                <input
                  type="text"
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={ttsVoice}
                  aria-label="Voice identifier"
                  placeholder="ex: en-US-female"
                />
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={ttsSubmitting}
              >
                {ttsSubmitting ? 'Sending...' : 'Send TTS'}
              </button>
            </form>
          </article>
        </div>

        <aside class="flex flex-col gap-6">
          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Safety controls">
            <h2 class="text-lg font-medium">Safety</h2>
            <p class="mt-1 text-xs text-slate-400">
              State: {controlState.tts_muted ? 'TTS muted' : 'TTS active'} &middot; Preset {controlState.active_preset}
            </p>
            <button
              class={`mt-4 w-full rounded-lg px-4 py-2 text-sm font-semibold transition ${
                controlState.tts_muted
                  ? 'bg-emerald-500 text-emerald-950 hover:bg-emerald-400'
                  : 'bg-amber-500 text-amber-950 hover:bg-amber-400'
              } disabled:opacity-60`}
              type="button"
              on:click={toggleMuteState}
              disabled={mutePending}
            >
              {controlState.tts_muted ? 'Unmute TTS' : 'Mute TTS'}
            </button>

            <div class="mt-4 space-y-2" aria-label="Panic">
              <label class="flex flex-col gap-1 text-xs font-medium text-slate-300">
                Optional message
                <textarea
                  class="min-h-[60px] rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={panicReason}
                  aria-label="Panic reason"
                ></textarea>
              </label>
              <button
                class="w-full rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-red-950 transition hover:bg-red-400 disabled:opacity-60"
                type="button"
                on:click={sendPanic}
                disabled={panicPending}
              >
                {panicPending ? 'Triggering...' : 'Trigger panic'}
              </button>
              <p class="text-[11px] text-slate-500">
                Last panic: {formatRelativeTimestamp(controlState.panic_at)}
              </p>
            </div>

            <div class="mt-5 space-y-2">
              <h3 class="text-sm font-semibold text-slate-200">Persona presets</h3>
              <ul class="space-y-2">
                {#each presetOptions as preset}
                  <li>
                    <button
                      class={`w-full rounded-lg border px-3 py-2 text-left text-sm transition ${
                        controlState.active_preset === preset.value
                          ? 'border-emerald-400 bg-emerald-400/20 text-emerald-100'
                          : 'border-white/10 bg-slate-950/50 text-slate-200 hover:bg-slate-800'
                      } disabled:opacity-60`}
                      type="button"
                      on:click={() => applyPresetAction(preset.value)}
                      disabled={presetPending !== null}
                    >
                      <span class="block font-semibold">{preset.label}</span>
                      <span class="block text-xs text-slate-400">{preset.description}</span>
                    </button>
                  </li>
                {/each}
              </ul>
            </div>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Configure persona">
            <h2 class="text-lg font-medium">Persona</h2>
            <form class="mt-4 space-y-4" on:submit|preventDefault={submitPersona}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Style
                <select
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={personaForm.style}
                  aria-label="Persona style"
                >
                  {#each personaStyles as style}
                    <option value={style}>{style}</option>
                  {/each}
                </select>
              </label>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Chaos ({personaForm.chaos}%)
                <input
                  type="range"
                  min="0"
                  max="100"
                  bind:value={personaForm.chaos}
                  class="range"
                  aria-valuenow={personaForm.chaos}
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-valuetext={`${personaForm.chaos}%`}
                  aria-label="Chaos level"
                />
              </label>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Energy ({personaForm.energy}%)
                <input
                  type="range"
                  min="0"
                  max="100"
                  bind:value={personaForm.energy}
                  class="range"
                  aria-valuenow={personaForm.energy}
                  aria-valuemin="0"
                  aria-valuemax="100"
                  aria-valuetext={`${personaForm.energy}%`}
                  aria-label="Energy level"
                />
              </label>
              <label class="flex items-center gap-2 text-sm font-medium text-slate-200">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border border-slate-600 bg-slate-800"
                  bind:checked={personaForm.family_mode}
                  aria-label="Enable family mode"
                />
                Family mode
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={personaSubmitting}
              >
                {personaSubmitting ? 'Saving...' : 'Save changes'}
              </button>
            </form>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Update OBS scene">
            <h2 class="text-lg font-medium">OBS</h2>
            <form class="mt-4 space-y-3" on:submit|preventDefault={submitScene}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Active scene
                <input
                  type="text"
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={sceneInput}
                  aria-label="OBS scene"
                />
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={sceneSubmitting}
              >
                {sceneSubmitting ? 'Refreshing...' : 'Update scene'}
              </button>
            </form>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="VTS expressions">
            <h2 class="text-lg font-medium">VTS expressions</h2>
            <div class="mt-3 grid grid-cols-2 gap-2">
              {#each expressionOptions as option}
                <button
                  class={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                    orchestrator.last_expression?.expression === option.value
                      ? 'bg-emerald-400 text-emerald-950'
                      : 'bg-slate-800 hover:bg-slate-700'
                  }`}
                  type="button"
                  aria-pressed={orchestrator.last_expression?.expression === option.value}
                  on:click={() => sendExpression(option)}
                  disabled={expressionPending}
                >
                  {option.label}
                </button>
              {/each}
            </div>
            <p class="mt-4 text-xs text-slate-400">
              Current intensity{' '}
              {orchestrator.last_expression ? Math.round(orchestrator.last_expression.intensity * 100) : 0}%
            </p>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Live expression preview">
            <h2 class="text-lg font-medium">Live expression</h2>
            <p class="text-xs text-slate-400">
              Snapshot from the avatar bridge. Updates when VTS confirms a mood or intensity change.
            </p>
            <div class="mt-4 flex flex-col gap-4 sm:flex-row sm:items-center">
              <div class="relative h-24 w-24 shrink-0">
                <div class="absolute inset-0 rounded-full bg-gradient-to-br from-emerald-400/40 via-sky-400/40 to-purple-500/40 blur-xl"></div>
                <div class="relative flex h-full w-full items-center justify-center rounded-full border border-white/10 bg-slate-950/70 text-center">
                  <span class="px-4 text-sm font-semibold capitalize text-slate-100">{currentExpressionLabel}</span>
                </div>
              </div>
              <div class="flex-1 space-y-3 text-xs text-slate-400">
                <div class="space-y-1">
                  <div class="flex items-center justify-between font-medium text-slate-200">
                    <span>Intensity</span>
                    <span>{expressionIntensity}%</span>
                  </div>
                  <div class="h-2 w-full rounded-full bg-slate-800">
                    <div
                      class="h-full rounded-full bg-gradient-to-r from-emerald-400 via-sky-400 to-purple-500 transition-[width] duration-500"
                      style={`width: ${Math.min(100, Math.max(0, expressionIntensity))}%`}
                    ></div>
                  </div>
                </div>
                <p>
                  Persona style:
                  <span class="font-semibold text-slate-200 capitalize">{personaForm.style}</span>
                </p>
                <p>Last update {formatTimestamp(currentExpression?.ts)}</p>
              </div>
            </div>
          </article>
        </aside>
        </section>
      </div>

      <div
        id="panel-diagnostics"
        role="tabpanel"
        aria-labelledby="tab-diagnostics"
        tabindex="0"
        class="space-y-6"
        class:hidden={activeTab !== 'diagnostics'}
      >
        <section class="rounded-xl border border-white/10 bg-slate-900/70 p-5 shadow" aria-label="Diagnostics and logs">
          <header class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <h2 class="text-lg font-medium">Diagnostics</h2>
              <p class="text-xs text-slate-400">Live logs from orchestrator, workers, and controllers.</p>
            </div>
            <div class="flex flex-wrap items-center gap-3">
              <span class="text-[11px] text-slate-500">Auto-refresh every {Math.round(LOGS_POLL_INTERVAL_MS / 1000)}s</span>
              <button
                class="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
                on:click={() => refreshLogs(true)}
                disabled={logsLoading}
              >
                {logsLoading ? 'Loading...' : 'Refresh logs'}
              </button>
            </div>
          </header>

          <div class="mt-4 flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Service
                <select
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={logServiceFilter}
                  on:change={handleLogServiceChange}
                  aria-label="Filter logs by service"
                >
                  <option value="all">All services</option>
                  {#each logServiceOptions as service}
                    <option value={service}>{formatServiceName(service)}</option>
                  {/each}
                </select>
              </label>

              <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Level
                <select
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={logLevelFilter}
                  on:change={handleLogLevelChange}
                  aria-label="Filter logs by level"
                >
                  <option value="all">All levels</option>
                  {#each LOG_LEVEL_OPTIONS as level}
                    <option value={level}>{level.toUpperCase()}</option>
                  {/each}
                </select>
              </label>

              <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Time range
                <select
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={logSinceValue}
                  on:change={handleLogSinceChange}
                  aria-label="Filter logs by time range"
                >
                  {#each LOG_SINCE_OPTIONS as option}
                    <option value={option.value}>{option.label}</option>
                  {/each}
                </select>
              </label>

              <label class="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-wide text-slate-400">
                Search
                <input
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  type="search"
                  placeholder="Message contains…"
                  bind:value={logContainsFilter}
                  on:input={handleLogSearchInput}
                  aria-label="Search logs"
                  autocomplete="off"
                />
              </label>
            </div>

            <div class="flex items-center gap-2">
              <button
                class="rounded-lg border border-white/10 px-3 py-2 text-xs font-semibold text-slate-200 transition hover:border-emerald-400 hover:text-emerald-200 disabled:opacity-50"
                on:click={handleClearLogFilters}
                type="button"
                disabled={!hasActiveLogFilters}
              >
                Clear filters
              </button>
            </div>
          </div>

          {#if logsLoading && !logs.length}
            <p class="mt-4 text-sm text-slate-400" aria-live="polite">Loading logs...</p>
          {:else if logsError}
            <div class="mt-4 rounded border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200" role="alert">
              <p>{logsError}</p>
              <button
                class="mt-3 inline-flex items-center gap-2 rounded bg-red-400 px-3 py-1 text-xs font-semibold text-red-950 hover:bg-red-300 focus:outline-none focus:ring-2 focus:ring-red-300 disabled:opacity-60"
                on:click={() => refreshLogs(false)}
                disabled={logsLoading}
              >
                Retry
              </button>
            </div>
          {:else if displayLogs.length}
            <div class="mt-4 overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-800 text-left text-xs">
                <thead class="bg-slate-950/60 text-slate-400">
                  <tr>
                    <th class="px-3 py-2 font-semibold">Time</th>
                    <th class="px-3 py-2 font-semibold">Service</th>
                    <th class="px-3 py-2 font-semibold">Level</th>
                    <th class="px-3 py-2 font-semibold">Message</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-900/70">
                  {#each displayLogs as entry (entry.ts + entry.service + entry.message + entry.count)}
                    {@const displayTs = entry.latestTs ?? entry.ts}
                    {@const relativeDisplay = formatRelativeTime(displayTs)}
                    {@const occurrenceSummary = entry.count > 1 ? formatOccurrences(entry) : ''}
                    <tr class="transition hover:bg-slate-900/60">
                      <td class="whitespace-nowrap px-3 py-2 text-slate-400">
                        <div class="font-medium text-slate-200">{formatTimestamp(displayTs)}</div>
                        {#if relativeDisplay}
                          <div class="text-[11px] text-slate-500">{relativeDisplay}</div>
                        {/if}
                        {#if occurrenceSummary}
                          <div class="mt-1 text-[11px] font-semibold text-emerald-300">{occurrenceSummary}</div>
                        {/if}
                      </td>
                      <td class="whitespace-nowrap px-3 py-2 text-slate-300">{formatServiceName(entry.service)}</td>
                      <td class="whitespace-nowrap px-3 py-2">
                        <span class={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${logLevelBadgeClass(entry.level)}`}>
                          {(entry.level ?? 'info').toUpperCase()}
                        </span>
                      </td>
                      <td class="px-3 py-2 text-slate-100">
                        <p class="font-medium text-slate-100">
                          {#each highlightSegments(entry.message, trimmedLogSearchTerm) as segment, index (index)}
                            {#if segment.match}
                              <mark class="rounded bg-emerald-500/20 px-1 text-emerald-100">{segment.value}</mark>
                            {:else}
                              {segment.value}
                            {/if}
                          {/each}
                        </p>
                        {#if entry.logger}
                          <p class="mt-1 text-[11px] text-slate-500">Logger: {entry.logger}</p>
                        {/if}
                        {#if entry.file}
                          <p class="mt-0.5 text-[11px] text-slate-500">File: {entry.file}</p>
                        {/if}
                        {#if entry.exception}
                          <pre class="mt-2 whitespace-pre-wrap break-words rounded-lg bg-rose-500/10 p-2 text-[11px] text-rose-200">{entry.exception}</pre>
                        {/if}
                        {#if entry.extra && typeof entry.extra === 'object' && Object.keys(entry.extra as Record<string, unknown>).length}
                          <pre class="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-950/60 p-2 text-[11px] text-slate-200">{JSON.stringify(entry.extra, null, 2)}</pre>
                        {/if}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {:else}
            <p class="mt-4 text-sm text-slate-400">
              {hasActiveLogFilters ? 'No logs match the current filters.' : 'No logs available yet.'}
            </p>
          {/if}
        </section>
      </div>
      </div>
    {/if}
    <footer class="mt-10 border-t border-white/10 pt-4 text-[11px] text-slate-500" aria-label="Attributions and licenses">
      <p class="font-medium">Copyright {currentYear} Kitsu.exe - Internal use only.</p>
      <p class="mt-1">
        Required licenses: Llama 3 8B Instruct (Meta), Coqui-TTS, and the Live2D avatar "Lumi". See `licenses/third_party/` in the repository.
      </p>
    </footer>
  </div>
</div>

<style lang="postcss">
  .range {
    @apply h-2 w-full appearance-none rounded-full bg-slate-800;
  }
  .range::-webkit-slider-thumb {
    @apply h-4 w-4 cursor-pointer appearance-none rounded-full bg-emerald-400 shadow;
  }
  .range::-moz-range-thumb {
    @apply h-4 w-4 cursor-pointer rounded-full bg-emerald-400 shadow;
  }
</style>
