import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['test/**/*.test.ts'],
    exclude: ['**/node_modules/**', '**/cdk.out/**'],
    // Synthesising under cdk-nag is slower than a unit test; give it room.
    testTimeout: 30_000,
  },
});
