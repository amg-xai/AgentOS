import { defineConfig } from 'vitest/config';
import base from './vite.config';

export default defineConfig({
  ...base,
  test: {
    ...base.test,
    include: ['integration/**/*.test.tsx'],
    maxWorkers: 1,
    minWorkers: 1,
    fileParallelism: false,
    testTimeout: 90000,
  },
});
