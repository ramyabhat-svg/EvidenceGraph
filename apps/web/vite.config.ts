import { defineConfig, loadEnv } from 'vite';

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  const target = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000';
  const proxy = { '/api': target };
  return { server: { proxy }, preview: { proxy } };
});
