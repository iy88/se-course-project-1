// Only allow app-local business paths supplied by a previous route guard.
export function safePostLoginRedirect(target) {
  if (typeof target !== 'string' || !target.startsWith('/') || target.startsWith('//') || target.startsWith('/auth/')) return '/home'
  return target
}
