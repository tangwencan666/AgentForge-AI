import { defineConfig } from 'vite';
import { hostedBrowserContext, loopbackOrigin } from './tests/browser-ci/environment';

hostedBrowserContext();
const target = loopbackOrigin(process.env.AGENTFORGE_CI_API_ORIGIN);

// Serve the real production bundle and proxy real HTTP/SSE to this job's API.
// No dotenv import, token, mocked route, or fallback to a local default port.
export default defineConfig({
  envDir: false,
  preview: {
    host: '127.0.0.1', strictPort: true,
    proxy: Object.fromEntries(['/api', '/health', '/openapi.json'].map(prefix => [prefix, { target }])),
  },
});
