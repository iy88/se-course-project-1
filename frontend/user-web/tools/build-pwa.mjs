/*
 * Post-build PWA step.
 *
 * Rsbuild has already emitted the app shell and content-hashed assets into
 * dist/. This script reads what actually landed there, builds an exact precache
 * allowlist and a content digest, then writes dist/sw.js. Running after every
 * production build keeps the release archive self-contained.
 */
import { createHash } from "node:crypto";
import { readFile, readdir, writeFile } from "node:fs/promises";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";

const projectDirectory = fileURLToPath(new URL("..", import.meta.url));
const distDirectory = join(projectDirectory, "dist");
const templatePath = join(projectDirectory, "tools", "service-worker.template.js");
const workerPath = join(distDirectory, "sw.js");
const shellPath = "index.html";
const hashedAssetPattern =
  /\.[0-9a-f]{8,}\.(?:js|mjs|css|woff2?|png|jpe?g|webp|gif|svg|ico|wasm)$/i;

async function listFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const absolutePath = join(directory, entry.name);
    if (entry.isDirectory()) {
      files.push(...(await listFiles(absolutePath)));
    } else if (entry.isFile()) {
      files.push(absolutePath);
    }
  }
  return files;
}

const files = await listFiles(distDirectory);
const relativeFiles = files.map((file) => relative(distDirectory, file).split(sep).join("/"));
if (!relativeFiles.includes(shellPath)) {
  throw new Error(`Missing ${shellPath} in ${distDirectory}`);
}

const assets = relativeFiles
  .filter((file) => file !== shellPath && hashedAssetPattern.test(file))
  .sort()
  .map((file) => `/${file}`);
if (assets.length === 0) {
  throw new Error("No hashed static assets found in dist");
}

const precacheAssets = [`/${shellPath}`, ...assets];
const template = await readFile(templatePath, "utf8");
const digest = createHash("sha256").update(template).update("\0");
for (const pathname of precacheAssets) {
  digest.update(pathname).update("\0");
  digest.update(await readFile(join(distDirectory, pathname.slice(1))));
  digest.update("\0");
}
const version = digest.digest("hex");

for (const token of ["__PWA_VERSION__", "__PRECACHE_ASSETS__"]) {
  if (!template.includes(token)) throw new Error(`Missing ${token} in the service worker template`);
}
const worker = template
  .replace("__PWA_VERSION__", version)
  .replace("__PRECACHE_ASSETS__", JSON.stringify(precacheAssets));

await writeFile(workerPath, worker);
console.log(
  `PWA: wrote dist/sw.js (version ${version.slice(0, 12)}, ${precacheAssets.length} precached paths)`,
);
