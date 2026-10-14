import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, path.resolve('..'), '');
  // Read only non-secret ports; never define or expose backend environment variables.
  const backend = `http://127.0.0.1:${env.BACKEND_PORT || '18100'}`;
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1', port: Number(env.FRONTEND_PORT || 15173), strictPort: true,
      proxy: { '/health': backend, '/api': backend, '/openapi.json': backend },
    },
    preview: { host: '127.0.0.1', port: Number(env.FRONTEND_PORT || 15173), strictPort: true },
  };
});
