<script lang="ts">
  import type { StatusVariant } from '$lib/types';

  export let status: StatusVariant = 'unknown';
  export let label: string;
  export let tone: 'solid' | 'soft' = 'solid';

  const VARIANT_MAP: Record<
    StatusVariant,
    { dot: string; solid: string; soft: string; text: string; shimmer: string }
  > = {
    online: {
      dot: 'bg-emerald-400',
      solid: 'bg-emerald-500/90 text-emerald-950 border border-emerald-400/70 shadow-emerald-500/30',
      soft: 'bg-emerald-500/15 text-emerald-200 border border-emerald-400/40',
      text: 'text-emerald-100',
      shimmer: 'from-emerald-400/30 to-transparent'
    },
    degraded: {
      dot: 'bg-amber-400',
      solid: 'bg-amber-400/90 text-amber-950 border border-amber-300/70 shadow-amber-400/30',
      soft: 'bg-amber-500/15 text-amber-100 border border-amber-400/40',
      text: 'text-amber-100',
      shimmer: 'from-amber-400/30 to-transparent'
    },
    offline: {
      dot: 'bg-rose-400',
      solid: 'bg-rose-500/90 text-rose-900 border border-rose-400/70 shadow-rose-500/30',
      soft: 'bg-rose-500/15 text-rose-100 border border-rose-400/40',
      text: 'text-rose-100',
      shimmer: 'from-rose-400/30 to-transparent'
    },
    unknown: {
      dot: 'bg-slate-400',
      solid: 'bg-slate-500/70 text-slate-900 border border-slate-400/60 shadow-slate-500/20',
      soft: 'bg-slate-600/20 text-slate-200 border border-slate-400/30',
      text: 'text-slate-200',
      shimmer: 'from-slate-200/20 to-transparent'
    }
  };

  $: variant = VARIANT_MAP[status] ?? VARIANT_MAP.unknown;
  $: shimmerClass = tone === 'solid' ? variant.shimmer : 'opacity-0';
</script>

<span
  class={`relative inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] ${
    tone === 'solid' ? variant.solid : variant.soft
  }`}
  data-status={status}
>
  <span class={`relative flex h-2.5 w-2.5 items-center justify-center`}>
    <span class={`h-2.5 w-2.5 rounded-full ${variant.dot} shadow-[0_0_0.65rem]`}></span>
    <span class={`absolute inset-0 animate-ping rounded-full ${shimmerClass}`}></span>
  </span>
  <span class={variant.text}>{label}</span>
</span>
