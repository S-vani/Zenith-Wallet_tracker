// Runs the backend tests with the project's virtualenv: `npm run test:backend` from the project root.
// Extra arguments are passed to pytest, e.g. `npm run test:backend -- -k dashboard`.
import {spawnSync} from "node:child_process";
import {existsSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";

const venvPython = join(root, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");
const python = existsSync(venvPython) ? venvPython : (isWindows ? "python" : "python3");

// shell: false so a venv path with spaces works
const result = spawnSync(python, ["-m", "pytest", ...process.argv.slice(2)], {cwd: root, stdio: "inherit"});

if (result.error) {
    console.error(`Couldn't run ${python}: ${result.error.message}`);
    console.error("Create the virtualenv first: uv sync  (or: python -m venv .venv && pip install -r requirements-dev.txt)");
    process.exit(1);
}
if (result.status === 1 && !existsSync(venvPython)) {
    console.error("No .venv found. Create one with: uv sync  (or: python -m venv .venv && pip install -r requirements-dev.txt)");
}
process.exit(result.status ?? 1);
