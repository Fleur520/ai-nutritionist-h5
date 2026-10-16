import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({
  plugins:[vue()],
  // This H5 loads a single eager bundle, so no modulepreload shim is needed.
  build:{modulePreload:{polyfill:false}},
  server:{port:5173,proxy:{'/api':{target:'http://127.0.0.1:8000',changeOrigin:true}}},
})
