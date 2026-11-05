import type { NextConfig } from 'next';

const config: NextConfig = {
  async rewrites() {
    return [{source:'/backend/:path*', destination:'http://127.0.0.1:8766/:path*'}];
  },
  async headers() {
    return [{source:'/:path*',headers:[
      {key:'X-Content-Type-Options',value:'nosniff'},
      {key:'Referrer-Policy',value:'no-referrer'},
      {key:'X-Frame-Options',value:'DENY'},
      {key:'Permissions-Policy',value:'camera=(), microphone=(), geolocation=()'},
    ]}];
  },
};
export default config;