import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
// `npm run build:ios` builds with `--mode ios`: it reads .env.ios (the public https API) and targets the iOS app's
// web view, Safari 17 (the app's deployment target is iOS 17.0). The website keeps Vite's default target
// ("baseline-widely-available", whose output already runs on Safari 17), so raising the app's minimum doesn't
// drop older browsers from the website.
export default defineConfig(({mode}) => ({
  plugins: [react()],
  ...(mode === 'ios' && {build: {target: ['safari17']}}),
}))
