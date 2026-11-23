/*
 * Resolve hook that lets the Node test runner load the application's TypeScript
 * modules written with extensionless relative imports (the style the bundler
 * expects). Only relative specifiers are retried with a `.ts` extension, so the
 * hook cannot silently resolve an unrelated package.
 */
const CANDIDATE_SUFFIXES = [".ts", ".tsx", "/index.ts"];

export async function resolve(specifier, context, nextResolve) {
  const isRelative = specifier.startsWith("./") || specifier.startsWith("../");
  if (!isRelative) return nextResolve(specifier, context);

  try {
    return await nextResolve(specifier, context);
  } catch (error) {
    if (error?.code !== "ERR_MODULE_NOT_FOUND") throw error;
  }

  for (const suffix of CANDIDATE_SUFFIXES) {
    try {
      return await nextResolve(`${specifier}${suffix}`, context);
    } catch {
      // Try the next candidate extension.
    }
  }

  return nextResolve(specifier, context);
}
