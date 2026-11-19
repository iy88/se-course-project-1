import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";

const usage = "Usage: npm run dev -- [both|user|admin]";
const [target = "both", ...extra] = process.argv.slice(2);
const workspaces = {
  both: ["user-web", "admin-web"],
  user: ["user-web"],
  admin: ["admin-web"],
};

if (target === "--help" || target === "-h") {
  console.log(usage);
} else if (!Object.hasOwn(workspaces, target) || extra.length) {
  console.error(usage);
  process.exitCode = 1;
} else {
  start(workspaces[target]);
}

function start(selected) {
  const commands = selected.map((workspace) => {
    const manifest = new URL(`./${workspace}/package.json`, import.meta.url);
    const require = createRequire(manifest);
    const packagePath = require.resolve("@rsbuild/core/package.json");
    const { bin } = require(packagePath);
    return {
      workspace,
      cli: resolve(dirname(packagePath), bin.rsbuild),
      cwd: new URL(".", manifest),
    };
  });

  const children = new Set();
  let stopping = false;
  function stop(code) {
    if (stopping) return;
    stopping = true;
    process.exitCode = code;
    for (const child of children) child.kill();
  }

  process.once("SIGINT", () => stop(130));
  process.once("SIGTERM", () => stop(143));

  for (const { workspace, cli, cwd } of commands) {
    const child = spawn(process.execPath, [cli, "dev"], {
      cwd,
      stdio: "inherit",
    });
    children.add(child);
    child.once("error", (error) => {
      children.delete(child);
      console.error(`${workspace}: ${error.message}`);
      stop(1);
    });
    child.once("exit", (code, signal) => {
      children.delete(child);
      if (!stopping && (code || signal)) {
        console.error(`${workspace} exited (${signal ?? code}).`);
      }
      stop(code ?? 1);
    });
  }
}
