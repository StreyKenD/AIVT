<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import { createTelemetryStream, type TelemetryMessage } from '$lib/ws';
  import {
    ApiError,
    applyPreset,
    downloadTelemetryCsv,
    fetchLatestMetrics,
    fetchSoakResults,
    getStatus,
    requestTTS,
    setGlobalMute,
    setOBSScene,
    setPersona,
    setVTSExpression,
    triggerPanic,
    toggleModule,
    type ExpressionSnapshot,
    type LatestMetrics,
    type MemorySummary,
    type ModuleStatus,
    type OrchestratorStatus,
    type PersonaSnapshot,
    type SoakResult,
    type TTSRecord
  } from '$lib/api';
  import LatencyChart, { type LatencyPoint } from '$lib/LatencyChart.svelte';

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
    { label: 'Sorriso', value: 'smile', intensity: 0.7 },
    { label: 'Surpresa', value: 'surprised', intensity: 0.8 },
    { label: 'Relax', value: 'calm', intensity: 0.5 },
    { label: 'Pensativa', value: 'thinking', intensity: 0.6 },
    { label: 'Sonolenta', value: 'sleepy', intensity: 0.4 }
  ];

  const presetOptions = [
    { value: 'default', label: 'Default', description: 'Equilíbrio kawaii (50% energia)' },
    { value: 'cozy', label: 'Cozy', description: 'Tom calmo para segmentos de conversa íntima' },
    { value: 'hype', label: 'Hype', description: 'Energia máxima para anúncios e raids' }
  ];

  const latencySeries: LatencySeries = {
    asr_worker: [],
    policy_worker: [],
    tts_worker: []
  };
  const LATENCY_MAX_POINTS = 24;
  const latencyColors: Record<string, string> = {
    asr_worker: '#60a5fa',
    policy_worker: '#facc15',
    tts_worker: '#34d399'
  };

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

  let metrics: LatestMetrics | null = null;
  let metricsError = '';
  let metricsLoading = true;
  let soakResults: SoakResult[] = [];
  let soakLoading = true;
  let soakError = '';

  let metricsTimer: ReturnType<typeof setInterval> | null = null;
  let soakTimer: ReturnType<typeof setInterval> | null = null;

  onMount(() => {
    const unsubscribe = telemetry.subscribe(handleTelemetry);
    void fetchStatus(true);
    void refreshMetrics(true);
    void refreshSoak(true);
    metricsTimer = setInterval(() => void refreshMetrics(false), 5000);
    soakTimer = setInterval(() => void refreshSoak(false), 20000);

    return () => {
      unsubscribe();
      telemetry.disconnect();
      if (metricsTimer) clearInterval(metricsTimer);
      if (soakTimer) clearInterval(soakTimer);
    };
  });

  onDestroy(() => {
    if (metricsTimer) clearInterval(metricsTimer);
    if (soakTimer) clearInterval(soakTimer);
  });

  async function fetchStatus(initial = false, showNotice = false) {
    if (initial) {
      loadingStatus = true;
    } else {
      refreshing = true;
    }
    loadError = '';

    try {
      const snapshot = await getStatus();
      applySnapshot(snapshot);
      if (showNotice) {
        setFeedback('success', 'Status atualizado.');
      }
    } catch (error) {
      loadError = getErrorMessage(error, 'Falha ao carregar o status do orquestrador.');
    } finally {
      if (initial) {
        loadingStatus = false;
      } else {
        refreshing = false;
      }
    }
  }

  function setFeedback(type: 'success' | 'error', text: string) {
    feedback = { type, text };
  }

  function handleTelemetry(message: TelemetryMessage | null) {
    if (!message) return;

    if (message.type === 'status') {
      applySnapshot(message.payload);
      return;
    }

    if (!orchestrator) {
      return;
    }

    switch (message.type) {
      case 'module.toggle': {
        const previous = orchestrator.modules[message.module];
        const nextState = message.enabled ? 'online' : 'offline';
        const updated: ModuleStatus = previous
          ? { ...previous, state: nextState, last_updated: Date.now() / 1000 }
          : { state: nextState, latency_ms: 0, last_updated: Date.now() / 1000 };
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
        Object.entries(snapshot.modules).map(([name, info]) => [name, { ...info }])
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
    return {
      ...summary,
      knobs: { ...summary.knobs }
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

  function getLatencySnapshot(key: keyof LatencySeries): number | null {
    const series = latencySeries[key];
    if (!series.length) return null;
    return series[series.length - 1].value;
  }

  function formatRelativeTimestamp(ts: number | null | undefined): string {
    if (!ts || Number.isNaN(ts)) return 'n/d';
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
      metrics = latest;
      updateLatencySeries(latest);
    } catch (error) {
      metricsError = getErrorMessage(error, 'Falha ao carregar métricas.');
    } finally {
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
      soakResults = await fetchSoakResults(10);
    } catch (error) {
      soakError = getErrorMessage(error, 'Falha ao carregar resultados do soak test.');
    } finally {
      if (initial) {
        soakLoading = false;
      }
    }
  }

  async function handleModuleToggle(module: string, enabled: boolean) {
    if (!orchestrator) return;
    const current = orchestrator.modules[module];
    const previous = current ? { ...current } : undefined;

    const updated: ModuleStatus = current
      ? { ...current, state: enabled ? 'online' : 'offline', last_updated: Date.now() / 1000 }
      : { state: enabled ? 'online' : 'offline', latency_ms: 0, last_updated: Date.now() / 1000 };

    orchestrator = {
      ...orchestrator,
      modules: { ...orchestrator.modules, [module]: updated }
    };
    modulePending = { ...modulePending, [module]: true };

    try {
      await toggleModule(module, enabled);
      setFeedback('success', `Modulo ${module} ${enabled ? 'ativado' : 'desativado'}.`);
    } catch (error) {
      if (previous) {
        orchestrator = {
          ...orchestrator,
          modules: { ...orchestrator.modules, [module]: previous }
        };
      }
      setFeedback('error', getErrorMessage(error, 'Nao foi possivel alterar o modulo.'));
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
      setFeedback('success', 'Persona atualizada com sucesso.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Nao foi possivel atualizar a persona.'));
    } finally {
      personaSubmitting = false;
    }
  }

  async function submitScene() {
    if (!orchestrator) return;
    const trimmed = sceneInput.trim();
    if (!trimmed) {
      setFeedback('error', 'Informe um nome de cena valido.');
      return;
    }

    sceneSubmitting = true;
    try {
      await setOBSScene(trimmed);
      orchestrator = { ...orchestrator, scene: trimmed };
      setFeedback('success', 'Cena enviada ao OBS.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Nao foi possivel atualizar a cena.'));
    } finally {
      sceneSubmitting = false;
    }
  }

  async function submitTTS() {
    if (!orchestrator) return;
    const text = ttsText.trim();
    if (!text) {
      setFeedback('error', 'Informe um texto para TTS.');
      return;
    }

    ttsSubmitting = true;
    try {
      const voice = ttsVoice.trim();
      const response = await requestTTS(voice ? { text, voice } : { text });
      orchestrator = { ...orchestrator, last_tts: cloneTts(response.data) };
      ttsText = '';
      setFeedback('success', 'Pedido de TTS enviado.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Nao foi possivel enviar o TTS.'));
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
      setFeedback('success', `Expressao ${option.label} enviada.`);
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Nao foi possivel atualizar a expressao.'));
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
      setFeedback('success', target ? 'TTS silenciado.' : 'TTS reativado.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Não foi possível alternar mute.'));
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
      setFeedback('success', 'Modo pânico acionado.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Não foi possível disparar o pânico.'));
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
      setFeedback('success', `Preset ${preset} aplicado.`);
      await fetchStatus(false);
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Não foi possível aplicar o preset.'));
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
      link.download = `telemetry-${new Date().toISOString()}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      setFeedback('success', 'CSV exportado com sucesso.');
    } catch (error) {
      setFeedback('error', getErrorMessage(error, 'Falha ao exportar CSV.'));
    } finally {
      csvPending = false;
    }
  }

  function formatTimestamp(ts: number | null | undefined): string {
    if (typeof ts !== 'number' || !Number.isFinite(ts)) {
      return 'n/d';
    }
    const millis = ts > 1_000_000_000_000 ? ts : ts * 1000;
    return new Date(millis).toLocaleString();
  }
</script>

<svelte:head>
  <title>Kitsu Orchestrator</title>
</svelte:head>

<div class="min-h-screen bg-slate-950 text-slate-50">
  <div class="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-10">
    <header class="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <h1 class="text-3xl font-semibold tracking-tight">Kitsu Orchestrator</h1>
        <p class="text-sm text-slate-400">
          Gerencie persona, modulos e automacoes em tempo real.
        </p>
      </div>
      <div class="flex items-center gap-3">
        <button
          class="rounded-lg bg-slate-800 px-4 py-2 text-sm font-semibold transition hover:bg-slate-700 disabled:opacity-60"
          on:click={refreshStatus}
          disabled={loadingStatus || refreshing}
        >
          {#if refreshing}
            Atualizando...
          {:else}
            Atualizar status
          {/if}
        </button>
      </div>
    </header>

    {#if feedback}
      <div
        class={`rounded-lg border px-4 py-3 text-sm ${
          feedback.type === 'error'
            ? 'border-red-500/50 bg-red-500/10 text-red-200'
            : 'border-emerald-500/50 bg-emerald-500/10 text-emerald-200'
        }`}
        role={feedback.type === 'error' ? 'alert' : 'status'}
        aria-live={feedback.type === 'error' ? 'assertive' : 'polite'}
      >
        {feedback.text}
      </div>
    {/if}

    {#if loadingStatus}
      <p class="text-sm text-slate-300" aria-live="polite">Carregando status do orquestrador...</p>
    {:else if loadError}
      <div
        class="rounded-lg border border-red-500/50 bg-red-500/10 p-4 text-sm text-red-200"
        role="alert"
        aria-live="assertive"
      >
        <p>{loadError}</p>
        <button
          class="mt-3 rounded bg-red-500 px-3 py-1.5 text-xs font-semibold text-red-950 hover:bg-red-400"
          on:click={() => fetchStatus(true)}
        >
          Tentar novamente
        </button>
      </div>
    {:else if orchestrator}
      <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-5" aria-label="Resumo rapido">
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Persona</h2>
          <p class="text-2xl font-semibold capitalize">{orchestrator.persona.style}</p>
          <p class="mt-2 text-sm text-slate-300">
            Energia {Math.round(orchestrator.persona.energy * 100)}% &middot; Chaos {Math.round(orchestrator.persona.chaos_level * 100)}%
          </p>
          <p class="text-xs text-slate-500">
            Familia {orchestrator.persona.family_mode ? 'ativada' : 'desativada'}
          </p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Cena OBS</h2>
          <p class="text-2xl font-semibold">{orchestrator.scene}</p>
          <p class="mt-2 text-xs text-slate-500">Status do orquestrador: {orchestrator.status}</p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Expressao ativa</h2>
          <p class="text-2xl font-semibold capitalize">
            {orchestrator.last_expression ? orchestrator.last_expression.expression : 'n/d'}
          </p>
          <p class="mt-2 text-xs text-slate-500">
            Intensidade {orchestrator.last_expression ? Math.round(orchestrator.last_expression.intensity * 100) : 0}%
          </p>
          <p class="text-xs text-slate-500">
            Atualizado {formatTimestamp(orchestrator.last_expression?.ts)}
          </p>
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Ultimo TTS</h2>
          <p class="text-base font-medium text-slate-200">
            {orchestrator.last_tts ? orchestrator.last_tts.text : 'Nenhum pedido ainda.'}
          </p>
          {#if orchestrator.last_tts}
            <p class="mt-2 text-xs text-slate-500">Voz: {orchestrator.last_tts.voice ?? 'auto'}</p>
            <p class="text-xs text-slate-500">Emitido {formatTimestamp(orchestrator.last_tts.ts)}</p>
          {/if}
        </div>
        <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
          <h2 class="text-xs uppercase text-slate-400">Operação</h2>
          <p class="text-lg font-semibold capitalize">Preset {controlState.active_preset}</p>
          <p class="mt-2 text-xs text-slate-500">
            TTS {controlState.tts_muted ? 'mutado' : 'ativo'}
          </p>
          <p class="text-xs text-slate-500">
            Último pânico {formatRelativeTimestamp(controlState.panic_at)}
          </p>
        </div>
      </section>

      <section class="rounded-xl border border-white/10 bg-slate-900/70 p-5 shadow" aria-label="Telemetria em tempo real">
        <header class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <h2 class="text-lg font-medium">Telemetria em tempo real</h2>
            <p class="text-xs text-slate-400">Latências agregadas por estágio e visão do soak test.</p>
          </div>
          <div class="flex flex-wrap items-center gap-3">
            <button
              class="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
              on:click={() => refreshMetrics(false)}
              disabled={metricsLoading}
            >
              {metricsLoading ? 'Carregando...' : 'Atualizar métricas'}
            </button>
            <button
              class="rounded-lg bg-emerald-500 px-4 py-2 text-xs font-semibold text-emerald-950 hover:bg-emerald-400 disabled:opacity-60"
              on:click={downloadCsvExport}
              disabled={csvPending}
            >
              {csvPending ? 'Gerando CSV...' : 'Exportar CSV'}
            </button>
          </div>
        </header>

        {#if metricsLoading}
          <p class="mt-4 text-sm text-slate-400" aria-live="polite">Carregando métricas...</p>
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
              <p>Eventos: {metrics.metrics.asr_worker?.count ?? 0}</p>
              <p>Latência média: {getLatencySnapshot('asr_worker')?.toFixed(1) ?? 'n/d'} ms</p>
            </div>
            <div class="rounded-lg border border-white/5 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p class="font-semibold text-slate-200">Policy</p>
              <p>Eventos: {metrics.metrics.policy_worker?.count ?? 0}</p>
              <p>Latência média: {getLatencySnapshot('policy_worker')?.toFixed(1) ?? 'n/d'} ms</p>
            </div>
            <div class="rounded-lg border border-white/5 bg-slate-950/40 p-3 text-xs text-slate-300">
              <p class="font-semibold text-slate-200">TTS</p>
              <p>Eventos: {metrics.metrics.tts_worker?.count ?? 0}</p>
              <p>Latência média: {getLatencySnapshot('tts_worker')?.toFixed(1) ?? 'n/d'} ms</p>
            </div>
          </div>
        {/if}

        <div class="mt-6 border-t border-white/5 pt-4">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200">Resultados do soak test</h3>
            <button
              class="rounded bg-slate-800 px-3 py-1.5 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
              on:click={() => refreshSoak(false)}
              disabled={soakLoading}
            >
              {soakLoading ? 'Carregando...' : 'Atualizar' }
            </button>
          </div>
          {#if soakLoading && !soakResults.length}
            <p class="mt-3 text-xs text-slate-400" aria-live="polite">Carregando histórico de soak...</p>
          {:else if soakError}
            <div class="mt-3 rounded border border-red-500/50 bg-red-500/10 p-3 text-xs text-red-200" role="alert">
              {soakError}
            </div>
          {:else if soakResults.length}
            <div class="mt-3 overflow-x-auto">
              <table class="min-w-full divide-y divide-slate-800 text-left text-xs">
                <thead class="bg-slate-950/60 text-slate-400">
                  <tr>
                    <th class="px-3 py-2 font-semibold">Data</th>
                    <th class="px-3 py-2 font-semibold">Status</th>
                    <th class="px-3 py-2 font-semibold">Detalhes</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-900/80 text-slate-200">
                  {#each soakResults as result}
                    <tr>
                      <td class="px-3 py-2 whitespace-nowrap">{new Date(result.ts).toLocaleString()}</td>
                      <td class="px-3 py-2">
                        {result.payload.success ? '✅ Sucesso' : '⚠️ Falha'}
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
            <p class="mt-3 text-xs text-slate-400">Nenhum resultado registrado ainda.</p>
          {/if}
        </div>
      </section>

      <section class="grid gap-6 lg:grid-cols-[2fr,1fr]" aria-label="Controles principais">
        <div class="flex flex-col gap-6">
          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Modulos do orquestrador">
            <header class="mb-4 flex items-center justify-between">
              <h2 class="text-lg font-medium">Modulos</h2>
              <p class="text-xs text-slate-400">
                Restauracao automatica: {orchestrator.restore_context ? 'ativa' : 'inativa'}
              </p>
            </header>
            <ul class="grid gap-3 md:grid-cols-2">
              {#each Object.entries(orchestrator.modules) as [name, module]}
                <li class="rounded-lg border border-white/5 bg-slate-950/50 p-3">
                  <div class="flex items-center justify-between">
                    <div>
                      <p class="text-sm font-semibold text-slate-100">{name}</p>
                      <p class="text-xs text-slate-400">
                        {module.state === 'online' ? 'Online' : 'Offline'} &middot; Latencia {module.latency_ms.toFixed(1)} ms
                      </p>
                      <p class="text-[11px] text-slate-500">
                        Atualizado {formatTimestamp(module.last_updated)}
                      </p>
                    </div>
                    <label class="inline-flex items-center gap-2 text-xs font-medium">
                      <span class="sr-only">Alternar {name}</span>
                      <input
                        type="checkbox"
                        class="h-4 w-4 rounded border border-slate-600 bg-slate-800"
                        checked={module.state === 'online'}
                        disabled={modulePending[name]}
                        on:change={(event) =>
                          handleModuleToggle(name, (event.currentTarget as HTMLInputElement).checked)}
                      />
                      <span>{module.state === 'online' ? 'Ativo' : 'Inativo'}</span>
                    </label>
                  </div>
                </li>
              {/each}
            </ul>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Historico de memoria">
            <h2 class="text-lg font-medium">Memoria</h2>
            <p class="mt-2 text-sm text-slate-300">
              Buffer: {orchestrator.memory.buffer_length} interacoes &middot; Resumo a cada {orchestrator.memory.summary_interval} falas
            </p>
            <p class="text-xs text-slate-400">
              Restauracao de memoria {orchestrator.memory.restore_enabled ? 'habilitada' : 'desabilitada'}
            </p>
            {#if orchestrator.memory.current_summary}
              <div class="mt-4 rounded border border-white/5 bg-slate-950/40 p-3 text-sm text-slate-200">
                <p class="font-semibold">Resumo #{orchestrator.memory.current_summary.id ?? 'n/d'}</p>
                <p class="mt-2 text-slate-300">{orchestrator.memory.current_summary.summary_text}</p>
                <p class="mt-2 text-xs text-slate-400">
                  Humor: {orchestrator.memory.current_summary.mood_state} &middot; Atualizado {formatTimestamp(orchestrator.memory.current_summary.ts)}
                </p>
              </div>
            {:else}
              <p class="mt-3 text-sm text-slate-400">Nenhum resumo gerado ainda.</p>
            {/if}
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Solicitar TTS">
            <h2 class="text-lg font-medium">Solicitar TTS</h2>
            <form class="mt-4 space-y-4" on:submit|preventDefault={submitTTS}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Texto
                <textarea
                  class="min-h-[96px] rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={ttsText}
                  aria-label="Texto do TTS"
                  required
                ></textarea>
              </label>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Voz preferida (opcional)
                <input
                  type="text"
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={ttsVoice}
                  aria-label="Identificador da voz"
                  placeholder="ex: en-US-female"
                />
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={ttsSubmitting}
              >
                {ttsSubmitting ? 'Enviando...' : 'Enviar TTS'}
              </button>
            </form>
          </article>
        </div>

        <aside class="flex flex-col gap-6">
          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Controles de segurança">
            <h2 class="text-lg font-medium">Segurança</h2>
            <p class="mt-1 text-xs text-slate-400">
              Estado: {controlState.tts_muted ? 'TTS mutado' : 'TTS ativo'} &middot; Preset {controlState.active_preset}
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
              {controlState.tts_muted ? 'Desmutar TTS' : 'Mutar TTS'}
            </button>

            <div class="mt-4 space-y-2" aria-label="Pânico">
              <label class="flex flex-col gap-1 text-xs font-medium text-slate-300">
                Mensagem opcional
                <textarea
                  class="min-h-[60px] rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={panicReason}
                  aria-label="Motivo do pânico"
                />
              </label>
              <button
                class="w-full rounded-lg bg-red-500 px-4 py-2 text-sm font-semibold text-red-950 transition hover:bg-red-400 disabled:opacity-60"
                type="button"
                on:click={sendPanic}
                disabled={panicPending}
              >
                {panicPending ? 'Acionando...' : 'Acionar pânico'}
              </button>
              <p class="text-[11px] text-slate-500">
                Último pânico: {formatRelativeTimestamp(controlState.panic_at)}
              </p>
            </div>

            <div class="mt-5 space-y-2">
              <h3 class="text-sm font-semibold text-slate-200">Presets de persona</h3>
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

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Configurar persona">
            <h2 class="text-lg font-medium">Persona</h2>
            <form class="mt-4 space-y-4" on:submit|preventDefault={submitPersona}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Estilo
                <select
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={personaForm.style}
                  aria-label="Estilo da persona"
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
                  aria-label="Nivel de chaos"
                />
              </label>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Energia ({personaForm.energy}%)
                <input
                  type="range"
                  min="0"
                  max="100"
                  bind:value={personaForm.energy}
                  class="range"
                  aria-valuenow={personaForm.energy}
                  aria-label="Nivel de energia"
                />
              </label>
              <label class="flex items-center gap-2 text-sm font-medium text-slate-200">
                <input
                  type="checkbox"
                  class="h-4 w-4 rounded border border-slate-600 bg-slate-800"
                  bind:checked={personaForm.family_mode}
                  aria-label="Ativar modo familia"
                />
                Modo familia
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={personaSubmitting}
              >
                {personaSubmitting ? 'Salvando...' : 'Salvar ajustes'}
              </button>
            </form>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Atualizar cena do OBS">
            <h2 class="text-lg font-medium">OBS</h2>
            <form class="mt-4 space-y-3" on:submit|preventDefault={submitScene}>
              <label class="flex flex-col gap-2 text-sm font-medium text-slate-200">
                Cena ativa
                <input
                  type="text"
                  class="rounded-lg border border-white/10 bg-slate-950/60 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-400"
                  bind:value={sceneInput}
                  aria-label="Cena do OBS"
                />
              </label>
              <button
                class="w-full rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 transition hover:bg-emerald-400 disabled:opacity-60"
                type="submit"
                disabled={sceneSubmitting}
              >
                {sceneSubmitting ? 'Atualizando...' : 'Atualizar cena'}
              </button>
            </form>
          </article>

          <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Expressao VTS">
            <h2 class="text-lg font-medium">Expressoes VTS</h2>
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
              Intensidade atual{' '}
              {orchestrator.last_expression ? Math.round(orchestrator.last_expression.intensity * 100) : 0}%
            </p>
          </article>
        </aside>
      </section>
    {/if}
    <footer class="mt-10 border-t border-white/10 pt-4 text-[11px] text-slate-500" aria-label="Atribuições e licenças">
      <p class="font-medium">© {currentYear} Kitsu.exe · Uso interno.</p>
      <p class="mt-1">
        Licenças obrigatórias: Llama 3 8B Instruct (Meta), Coqui-TTS e Avatar Live2D “Lumi”. Consulte `licenses/third_party/` no repositório.
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
