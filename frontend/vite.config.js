import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// GitHub Pages serves a project site from /<repo>/, so assets need that base path.
// Override with BASE_PATH in the deploy workflow if the repo is renamed.
export default defineConfig({
  plugins: [react()],
  base: process.env.BASE_PATH || '/topsheet-generation/',
})
