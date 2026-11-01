import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const backendRoot = path.join(root, 'backend')
const python = path.join(backendRoot, '.venv', ...(process.platform === 'win32' ? ['Scripts', 'python.exe'] : ['bin', 'python']))

// Reuse the backend's strict dotenv loader so malformed, duplicate, blank, or
// missing settings fail the default frontend startup/build with the same rules.
// The exporter returns only public endpoint settings; secrets never enter Vite.
const exporter = `
import json
from dotenv import dotenv_values
from app.core.config import load_settings, resolve_env_file

settings = load_settings()
values = dotenv_values(resolve_env_file(), interpolate=False)
result = {
    "apiBaseUrl": values.get("VITE_API_BASE_URL", "/api/v1"),
    "timeoutMs": values.get("VITE_API_TIMEOUT_MS", "15000"),
    "proxyTarget": values.get("API_PROXY_TARGET", "http://127.0.0.1:8000"),
}
print(json.dumps(result))
`

const configSource = process.env.PROJECT1_FRONTEND_CONFIG ?? 'backend'
if (!['backend', 'public'].includes(configSource)) {
  throw new Error('PROJECT1_FRONTEND_CONFIG must be backend or public')
}

let publicSettings
if (configSource === 'public') {
  // CI builds need only public endpoints, never backend credentials or Python.
  publicSettings = {
    apiBaseUrl: process.env.VITE_API_BASE_URL ?? '/api/v1',
    timeoutMs: process.env.VITE_API_TIMEOUT_MS ?? '15000',
    proxyTarget: process.env.API_PROXY_TARGET ?? 'http://127.0.0.1:8000',
  }
} else {
  let raw
  try {
    raw = execFileSync(python, ['-c', exporter], {
      cwd: backendRoot,
      encoding: 'utf8',
      env: {
        PATH: process.env.PATH || '',
        ...(process.env.SYSTEMROOT ? { SYSTEMROOT: process.env.SYSTEMROOT } : {}),
        ...(process.env.TEMP ? { TEMP: process.env.TEMP } : {}),
        ...(process.env.HOME ? { HOME: process.env.HOME } : {}),
        ...(process.env.TMPDIR ? { TMPDIR: process.env.TMPDIR } : {}),
        ...(process.env.LANG ? { LANG: process.env.LANG } : {}),
        ...(Object.hasOwn(process.env, 'APP_ENV_FILE')
          ? { APP_ENV_FILE: process.env.APP_ENV_FILE }
          : {}),
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
  } catch (error) {
    const detail = error.stderr?.toString().trim()
    throw new Error(detail || 'Selected dotenv configuration is invalid or unavailable')
  }
  publicSettings = JSON.parse(raw)
}

const apiBaseUrl = String(publicSettings.apiBaseUrl).trim()
const timeoutMs = Number(publicSettings.timeoutMs)
const proxyTarget = String(publicSettings.proxyTarget).trim()
if (!apiBaseUrl || /[\r\n]/.test(apiBaseUrl)) throw new Error('VITE_API_BASE_URL is invalid')
if (/^https?:\/\//i.test(apiBaseUrl)) {
  const apiUrl = new URL(apiBaseUrl)
  if (apiUrl.username || apiUrl.password || apiUrl.search || apiUrl.hash) {
    throw new Error('VITE_API_BASE_URL must not contain credentials, query, or fragment')
  }
} else if (!apiBaseUrl.startsWith('/') || apiBaseUrl.startsWith('//') ||
    apiBaseUrl.includes('?') || apiBaseUrl.includes('#')) {
  throw new Error('VITE_API_BASE_URL must be a root-relative path or absolute HTTP URL')
}
let target
try {
  target = new URL(proxyTarget)
} catch {
  throw new Error('API_PROXY_TARGET must be an absolute HTTP URL')
}
if (!['http:', 'https:'].includes(target.protocol) || target.username || target.password ||
    target.search || target.hash) {
  throw new Error('API_PROXY_TARGET must be an HTTP(S) URL without credentials or query data')
}
if (!Number.isInteger(timeoutMs) || timeoutMs <= 0) {
  throw new Error('VITE_API_TIMEOUT_MS must be a positive integer')
}

export const frontendSettings = {
  apiBaseUrl,
  timeoutMs,
  proxyTarget: target.origin,
}
