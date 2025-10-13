<script lang="ts">
  export type LatencyPoint = { ts: number; value: number };

  export let title: string;
  export let points: LatencyPoint[] = [];
  export let accent = '#34d399';

  const width = 320;
  const height = 140;

  $: normalized = normalizePoints(points, width, height);
  $: path = buildPath(normalized);
  $: latest = points.length ? points[points.length - 1].value : null;

  function normalizePoints(data: LatencyPoint[], w: number, h: number) {
    if (data.length === 0) return [];
    const values = data.map((point) => point.value);
    const min = Math.min(...values);
    const max = Math.max(...values);
    const spread = max - min || 1;
    const step = w / Math.max(1, data.length - 1);
    return data.map((point, index) => ({
      x: index * step,
      y: h - ((point.value - min) / spread) * (h - 16) - 8,
    }));
  }

  function buildPath(data: { x: number; y: number }[]) {
    if (data.length === 0) return '';
    if (data.length === 1) return `M0 ${data[0].y} L${width} ${data[0].y}`;
    return data.reduce((acc, point, index) => {
      const prefix = index === 0 ? 'M' : 'L';
      return `${acc}${prefix}${point.x} ${point.y} `;
    }, '');
  }
</script>

<div class="flex flex-col gap-2">
  <div class="flex items-baseline justify-between">
    <h3 class="text-sm font-medium text-slate-300">{title}</h3>
    {#if latest !== null}
      <span class="text-xs text-slate-400">{latest.toFixed(1)} ms</span>
    {/if}
  </div>
  {#if normalized.length >= 2}
    <svg
      aria-hidden="true"
      viewBox={`0 0 ${width} ${height}`}
      class="h-32 w-full rounded-lg bg-slate-950/60"
    >
      <path d={path.trim()} fill="none" stroke={accent} stroke-width="2" stroke-linejoin="round" />
      {#each normalized as point}
        <circle cx={point.x} cy={point.y} r="3" fill={accent} fill-opacity="0.8" />
      {/each}
    </svg>
  {:else}
    <div class="flex h-32 w-full items-center justify-center rounded-lg border border-dashed border-slate-800 bg-slate-950/40 text-xs text-slate-500">
      Dados insuficientes para o gráfico.
    </div>
  {/if}
</div>
