import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/**/*.spec.ts']
  },
  resolve: {
    alias: {
      $lib: fileURLToPath(new URL('./src/lib', import.meta.url)),
      '$env/static/public': fileURLToPath(new URL('./src/test/env-static-public.ts', import.meta.url)),
      '$env/dynamic/public': fileURLToPath(new URL('./src/test/env-dynamic-public.ts', import.meta.url))
    }
  }
});
