*** Begin Patch
*** Update File: kitsu-telemetry/ui/src/routes/+page.svelte
@@
-        </section>
-      </div>
+        </section>
+      </div>
+
+      <div
+        id="panel-diagnostics"
+        role="tabpanel"
+        aria-labelledby="tab-diagnostics"
+        tabindex="0"
+        class="space-y-6"
+        class:hidden={activeTab !== 'diagnostics'}
+      >
+        <section class="rounded-xl border border-white/10 bg-slate-900/70 p-5 shadow" aria-label="Diagnostics and logs">
+          <header class="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
+            <div>
+              <h2 class="text-lg font-medium">Diagnostics</h2>
+              <p class="text-xs text-slate-400">Live logs from orchestrator, workers, and controllers.</p>
+            </div>
+            <div class="flex flex-wrap items-center gap-3">
+              <span class="text-[11px] text-slate-500">Auto-refresh every {Math.round(LOGS_POLL_INTERVAL_MS / 1000)}s</span>
+              <button
+                class="rounded-lg bg-slate-800 px-4 py-2 text-xs font-semibold hover:bg-slate-700 disabled:opacity-60"
+                on:click={() => refreshLogs(true)}
+                disabled={logsLoading}
+              >
+                {logsLoading ? 'Loading' : 'Refresh logs'}
+              </button>
+            </div>
+          </header>
+
+          {#if logsLoading && !logs.length}
+            <p class="mt-4 text-sm text-slate-400" aria-live="polite">Loading logs</p>
+          {:else if logsError}
+            <div class="mt-4 rounded border border-red-500/50 bg-red-500/10 p-3 text-sm text-red-200" role="alert">
+              <p>{logsError}</p>
+              <button
+                class="mt-3 inline-flex items-center gap-2 rounded bg-red-400 px-3 py-1 text-xs font-semibold text-red-950 hover:bg-red-300 focus:outline-none focus:ring-2 focus:ring-red-300 disabled:opacity-60"
+                on:click={() => refreshLogs(false)}
+                disabled={logsLoading}
+              >
+                Retry
+              </button>
+            </div>
+          {:else if logs.length}
+            <div class="mt-4 overflow-x-auto">
+              <table class="min-w-full divide-y divide-slate-800 text-left text-xs">
+                <thead class="bg-slate-950/60 text-slate-400">
+                  <tr>
+                    <th class="px-3 py-2 font-semibold">Time</th>
+                    <th class="px-3 py-2 font-semibold">Service</th>
+                    <th class="px-3 py-2 font-semibold">Level</th>
+                    <th class="px-3 py-2 font-semibold">Message</th>
+                  </tr>
+                </thead>
+                <tbody class="divide-y divide-slate-900/70">
+                  {#each logs as entry (entry.ts + entry.service + entry.message)}
+                    <tr class="transition hover:bg-slate-900/60">
+                      <td class="whitespace-nowrap px-3 py-2 text-slate-400">{formatTimestamp(entry.ts)}</td>
+                      <td class="whitespace-nowrap px-3 py-2 capitalize text-slate-300">{entry.service}</td>
+                      <td class="whitespace-nowrap px-3 py-2">
+                        <span class={`inline-flex rounded-full px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide ${logLevelBadgeClass(entry.level)}`}>
+                          {(entry.level ?? 'info').toUpperCase()}
+                        </span>
+                      </td>
+                      <td class="px-3 py-2 text-slate-100">
+                        <p class="font-medium text-slate-100">{entry.message}</p>
+                        {#if entry.logger || entry.file}
+                          <p class="mt-1 text-[11px] text-slate-500">
+                            {entry.logger ?? entry.file}
+                          </p>
+                        {/if}
+                        {#if entry.exception}
+                          <pre class="mt-2 whitespace-pre-wrap break-words rounded-lg bg-rose-500/10 p-2 text-[11px] text-rose-200">{entry.exception}</pre>
+                        {/if}
+                        {#if entry.extra && typeof entry.extra === 'object' && Object.keys(entry.extra as Record<string, unknown>).length}
+                          <pre class="mt-2 whitespace-pre-wrap break-words rounded-lg bg-slate-950/60 p-2 text-[11px] text-slate-200">{JSON.stringify(entry.extra, null, 2)}</pre>
+                        {/if}
+                      </td>
+                    </tr>
+                  {/each}
+                </tbody>
+              </table>
+            </div>
+          {:else}
+            <p class="mt-4 text-sm text-slate-400">No logs available yet.</p>
+          {/if}
+        </section>
+      </div>
*** End Patch
