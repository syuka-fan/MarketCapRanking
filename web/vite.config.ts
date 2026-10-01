import { defineConfig } from 'vite';

export default defineConfig({
  base: './',
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/zrender/')) return 'renderer';
          if (id.includes('/echarts/')) return 'charts';
        },
      },
    },
  },
});
