<script lang="ts">
  import { onMount } from 'svelte';
  import { createTelemetryStream, type TelemetryMessage } from '$lib/ws';
  import { downloadTelemetryCsv, fetchRecentEvents } from '$lib/api';

  const telemetry = createTelemetryStream();

  type MetricState = {
    fps: number;
    cpu: number;
    gpu: number;
    viewers: number;
    vu: number[];
  };

  let metrics: MetricState = {
    fps: 0,
    cpu: 0,
    gpu: 0,
    viewers: 0,
    vu: Array.from({ length: 12 }, () => 0)
  };

  let consoleLines: { level: string; message: string }[] = [];
  let activeExpression = 'Happy';
  let energy = 60;
  let micGain = 40;
  let csvStatus = '';
  let recentEvents: Array<Record<string, unknown>> = [];

  const expressions = ['Happy', 'Surprised', 'Cool', 'Thinking', 'Sleepy'];

  function handleTelemetry(message: TelemetryMessage | null) {
    if (!message) return;
    if (message.type === 'metrics') {
      metrics = message.data;
    }
    if (message.type === 'console') {
      consoleLines = [{ level: message.data.level, message: message.data.message }, ...consoleLines].slice(0, 20);
    }
    if (message.type === 'expression') {
      activeExpression = message.data.expression;
    }
  }

  async function hydrateRecentEvents() {
    try {
      recentEvents = await fetchRecentEvents({ limit: 5 });
    } catch (error) {
      consoleLines = [{ level: 'warning', message: 'Não foi possível buscar eventos recentes.' }, ...consoleLines];
    }
  }

  async function handleExport() {
    csvStatus = 'Gerando CSV...';
    try {
      const csvContent = await downloadTelemetryCsv();
      const file = new Blob([csvContent], { type: 'text/csv' });
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url;
      link.download = `telemetria-${new Date().toISOString()}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      csvStatus = 'Exportação concluída!';
    } catch (error) {
      csvStatus = 'Falha ao exportar CSV.';
    }
  }

  onMount(() => {
    const unsubscribe = telemetry.subscribe(handleTelemetry);
    hydrateRecentEvents();
    return () => unsubscribe();
  });
</script>

<svelte:head>
  <title>Dashboard de Telemetria</title>
</svelte:head>

<div class="min-h-screen bg-slate-950 text-slate-50">
  <div class="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-10">
    <header class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <h1 class="text-3xl font-semibold tracking-tight">Kitsu Telemetry</h1>
      <div class="flex items-center gap-3">
        <button
          class="rounded-lg bg-emerald-500 px-4 py-2 text-sm font-semibold text-emerald-950 shadow transition hover:bg-emerald-400"
          on:click={handleExport}
          aria-label="Exportar eventos em CSV"
        >
          Exportar CSV
        </button>
        <span class="text-sm text-slate-300" aria-live="polite">{csvStatus}</span>
      </div>
    </header>

    <section class="grid gap-4 sm:grid-cols-2 xl:grid-cols-4" aria-label="Métricas principais">
      <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
        <h2 class="text-sm uppercase text-slate-400">FPS</h2>
        <p class="text-3xl font-semibold">{metrics.fps}</p>
      </div>
      <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
        <h2 class="text-sm uppercase text-slate-400">CPU</h2>
        <p class="text-3xl font-semibold">{metrics.cpu}%</p>
      </div>
      <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
        <h2 class="text-sm uppercase text-slate-400">GPU</h2>
        <p class="text-3xl font-semibold">{metrics.gpu}%</p>
      </div>
      <div class="rounded-xl border border-white/10 bg-slate-900/60 p-4 shadow">
        <h2 class="text-sm uppercase text-slate-400">Viewers</h2>
        <p class="text-3xl font-semibold">{metrics.viewers}</p>
      </div>
    </section>

    <section class="grid gap-6 lg:grid-cols-[2fr,1fr]" aria-label="Detalhes e controles">
      <div class="flex flex-col gap-6">
        <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow">
          <header class="mb-3 flex items-center justify-between">
            <h2 class="text-lg font-medium">Console</h2>
            <span class="text-xs text-slate-400">Últimos {consoleLines.length} eventos</span>
          </header>
          <div class="h-48 overflow-auto rounded-md border border-white/5 bg-black/40 p-3 font-mono text-xs">
            {#if consoleLines.length === 0}
              <p class="text-slate-400">Aguardando eventos...</p>
            {:else}
              {#each consoleLines as line, index (line.level + '-' + index + '-' + line.message)}
                <div class={`mb-1 rounded px-2 py-1 ${line.level === 'error'
                  ? 'bg-red-500/20 text-red-300'
                  : line.level === 'warning'
                  ? 'bg-amber-500/20 text-amber-200'
                  : 'bg-emerald-500/20 text-emerald-200'}`}>
                  [{line.level.toUpperCase()}] {line.message}
                </div>
              {/each}
            {/if}
          </div>
        </article>

        <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="VU Meter">
          <header class="mb-4 flex items-center justify-between">
            <h2 class="text-lg font-medium">Níveis de Áudio</h2>
            <span class="text-xs text-slate-400">Mock WebSocket</span>
          </header>
          <div class="flex h-40 items-end gap-2">
            {#each metrics.vu as level, index}
              <div
                class="flex-1 rounded-t bg-gradient-to-t from-emerald-500/50 to-emerald-300"
                style={`height: ${Math.max(level * 100, 5)}%`}
                aria-label={`Canal ${index + 1} com nível ${(level * 100).toFixed(0)}%`}
              ></div>
            {/each}
          </div>
        </article>
      </div>

      <aside class="flex flex-col gap-6">
        <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Controles de expressão">
          <h2 class="text-lg font-medium">Expressões</h2>
          <div class="mt-3 grid grid-cols-2 gap-2">
            {#each expressions as expression}
              <button
                class={`rounded-lg px-3 py-2 text-sm font-semibold transition ${
                  expression === activeExpression
                    ? 'bg-emerald-400 text-emerald-950'
                    : 'bg-slate-800 hover:bg-slate-700'
                }`}
                type="button"
                aria-pressed={expression === activeExpression}
                on:click={() => (activeExpression = expression)}
              >
                {expression}
              </button>
            {/each}
          </div>
          <p class="mt-4 text-sm text-slate-300">Atual: <span class="font-semibold">{activeExpression}</span></p>
        </article>

        <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Ajustes do avatar">
          <h2 class="text-lg font-medium">Ajustes</h2>
          <div class="mt-4 space-y-4">
            <label class="flex flex-col gap-2 text-sm font-medium">
              Energia ({energy}%)
              <input
                type="range"
                min="0"
                max="100"
                bind:value={energy}
                class="range"
                aria-valuenow={energy}
                aria-label="Energia do avatar"
              />
            </label>
            <label class="flex flex-col gap-2 text-sm font-medium">
              Ganho do microfone ({micGain}%)
              <input
                type="range"
                min="0"
                max="100"
                bind:value={micGain}
                class="range"
                aria-valuenow={micGain}
                aria-label="Ganho do microfone"
              />
            </label>
          </div>
        </article>

        <article class="rounded-xl border border-white/10 bg-slate-900/70 p-4 shadow" aria-label="Eventos recentes">
          <h2 class="text-lg font-medium">Eventos recentes</h2>
          <ul class="mt-3 space-y-2 text-xs">
            {#if recentEvents.length === 0}
              <li class="text-slate-400">Nenhum evento disponível.</li>
            {:else}
              {#each recentEvents as event, index}
                <li class="rounded bg-slate-800/70 p-2">
                  <p class="font-semibold">{event.event_type ?? 'evento'}</p>
                  <p class="text-slate-300">Origem: {event.source ?? 'desconhecida'}</p>
                  <p class="text-slate-400">Payload: {JSON.stringify(event.payload)}</p>
                  <p class="text-slate-500">#{index + 1}</p>
                </li>
              {/each}
            {/if}
          </ul>
        </article>
      </aside>
    </section>
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
