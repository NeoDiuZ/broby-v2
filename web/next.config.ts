import type { NextConfig } from 'next';
const apiOrigin = process.env.BROBY_API_ORIGIN || 'http://127.0.0.1:8100';
const config: NextConfig = {
  output: 'standalone',
  async headers(){return [{source:'/broby-sw.js',headers:[{key:'Cache-Control',value:'no-cache'},{key:'Service-Worker-Allowed',value:'/'}]},{source:'/offline-workspace.html',headers:[{key:'Cache-Control',value:'no-cache'}]}]},
  async rewrites() {
    return { beforeFiles: [
      { source: '/', destination: '/live/index.html' },
      { source: '/api/:path*', destination: `${apiOrigin}/api/:path*` },
    ] };
  },
};
export default config;
