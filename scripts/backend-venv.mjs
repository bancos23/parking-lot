import { spawnSync } from "node:child_process";
import { constants } from "node:fs";
import { access } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const rootDirectory = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "..",
);
const backendDirectory = path.join(rootDirectory, "backend");
const venvDirectory = path.join(backendDirectory, ".venv");
const venvPython =
  process.platform === "win32"
    ? path.join(venvDirectory, "Scripts", "python.exe")
    : path.join(venvDirectory, "bin", "python");

const action = process.argv[2];
const supportedActions = new Set(["install", "dev", "start"]);
const pythonVersionCheck = [
  "-c",
  "import sys; raise SystemExit(0 if (3, 13) <= sys.version_info[:2] < (3, 14) else 1)",
];

async function exists(filePath) {
  try {
    await access(filePath, constants.F_OK);
    return true;
  } catch {
    return false;
  }
}

function commandLabel(command, args = []) {
  return [command, ...args].join(" ");
}

function isPython313(command, args = []) {
  const result = spawnSync(command, [...args, ...pythonVersionCheck], {
    stdio: "ignore",
  });

  return !result.error && result.status === 0;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: rootDirectory,
    stdio: "inherit",
    ...options,
  });

  if (result.error) {
    throw new Error(`${commandLabel(command, args)} failed: ${result.error.message}`);
  }

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
}

function backendHost(defaultHost) {
  return process.env.BACKEND_HOST?.trim() || defaultHost;
}

function backendPort() {
  return process.env.BACKEND_PORT?.trim() || "8000";
}

function uvicornArgs({ reload, host }) {
  const args = ["-m", "uvicorn", "main:app"];

  if (reload) {
    args.push(
      "--reload",
      "--reload-exclude", "output",
      "--reload-exclude", "debug_outputs",
      "--reload-exclude", ".paddlex",
      "--reload-exclude", ".paddlex_local",
      "--reload-exclude", "__pycache__",
    );
  }

  args.push("--host", host, "--port", backendPort());
  return args;
}

function pythonCandidates() {
  const candidates = [];

  if (process.env.PYTHON) {
    candidates.push({ command: process.env.PYTHON, args: [] });
  }

  if (process.platform === "win32") {
    candidates.push({ command: "py", args: ["-3.13"] });
    candidates.push({ command: "py", args: [] });
  }

  candidates.push(
    { command: "python3.13", args: [] },
    { command: "python3", args: [] },
    { command: "python", args: [] },
  );

  return candidates;
}

function findBootstrapPython() {
  for (const candidate of pythonCandidates()) {
    if (isPython313(candidate.command, candidate.args)) {
      return candidate;
    }
  }

  throw new Error(
    "Could not find Python 3.13. Install Python 3.13 or set PYTHON to a Python 3.13 executable.",
  );
}

async function ensureVenv() {
  if (await exists(venvPython)) {
    if (!isPython313(venvPython)) {
      throw new Error(
        `Existing virtual environment is not Python 3.13: ${venvPython}`,
      );
    }

    return;
  }

  const python = findBootstrapPython();
  console.log(`Creating backend virtual environment with ${commandLabel(python.command, python.args)}...`);
  run(python.command, [...python.args, "-m", "venv", venvDirectory]);

  if (!(await exists(venvPython))) {
    throw new Error(`Virtual environment was created, but Python was not found at ${venvPython}`);
  }

  if (!isPython313(venvPython)) {
    throw new Error(`Virtual environment is not Python 3.13: ${venvPython}`);
  }
}

async function main() {
  if (!supportedActions.has(action)) {
    throw new Error("Usage: node scripts/backend-venv.mjs <install|dev|start>");
  }

  await ensureVenv();

  if (action === "install") {
    run(venvPython, ["-m", "pip", "install", "-e", "backend"]);
    return;
  }

  if (action === "dev") {
    run(
      venvPython,
      uvicornArgs({ reload: true, host: backendHost("0.0.0.0") }),
      { cwd: backendDirectory },
    );
    return;
  }

  run(
    venvPython,
    uvicornArgs({ reload: false, host: backendHost("127.0.0.1") }),
    { cwd: backendDirectory },
  );
}

main().catch((error) => {
  console.error(`Backend setup failed: ${error.message}`);
  process.exitCode = 1;
});
