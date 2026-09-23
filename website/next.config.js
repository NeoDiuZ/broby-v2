module.exports = { reactStrictMode: true, devIndicators: false, async rewrites() { return { beforeFiles: [{ source: '/', destination: '/live/index.html' }] }; } };
