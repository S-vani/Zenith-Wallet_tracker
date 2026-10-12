// Starts the FastAPI backend and the Vite frontend together: `npm run dev` from the project root.
// Pass "backend" or "frontend" to start just one of them.
import {spawn} from "node:child_process";
import {existsSync} from "node:fs";
import {dirname, join} from "node:path";
import {fileURLToPath} from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const isWindows = process.platform === "win32";

// Prefer the project's virtualenv so the right packages are used without activating it first
const venvPython = join(root, ".venv", isWindows ? "Scripts/python.exe" : "bin/python");
const python = existsSync(venvPython) ? venvPython : (isWindows ? "python" : "python3");

const services = {
    backend: {
        color: "\x1b[36m",
        command: python,
        args: ["-m", "uvicorn", "backend.main:app", "--reload", "--reload-dir", "backend", "--port", "8000"],
        shell: false, // the venv path can contain spaces, so run python directly
    },
    frontend: {
        color: "\x1b[35m",
        command: isWindows ? "npm.cmd" : "npm",
        args: ["--prefix", "frontend", "run", "dev"],
        shell: isWindows, // npm is a .cmd file on Windows, which needs a shell
    },
};

if (!existsSync(join(root, "frontend", "node_modules"))) {
    console.log("Installing frontend packages first (one time)...");
    const install = spawn("npm --prefix frontend install", {cwd: root, stdio: "inherit", shell: true});
    await new Promise((resolve) => install.on("exit", resolve));
}

const only = process.argv[2];
const toStart = only ? [only] : Object.keys(services);
const children = [];

for (const name of toStart) {
    const {color, command, args, shell} = services[name];
    // with a shell, node wants the whole command as one string
    const child = shell
        ? spawn([command, ...args].join(" "), {cwd: root, shell: true, env: process.env})
        : spawn(command, args, {cwd: root, env: process.env});
    const prefix = `${color}[${name}]\x1b[0m `;

    const pipe = (stream, out) => stream.on("data", (chunk) => {
        for (const line of chunk.toString().split(/\r?\n/)) {
            if (line.trim()) out.write(prefix + line + "\n");
        }
    });
    pipe(child.stdout, process.stdout);
    pipe(child.stderr, process.stderr);

    child.on("exit", (code) => {
        console.log(`${prefix}stopped (exit code ${code})`);
        if (name === "backend" && code !== 0 && !existsSync(venvPython)) {
            console.log(`${prefix}No .venv found. Create one with: python -m venv .venv  then: .venv\\Scripts\\pip install -r requirements.txt`);
        }
    });
    children.push(child);
}

// Ctrl+C stops everything
const stopAll = () => {
    for (const child of children) child.kill();
    process.exit(0);
};
process.on("SIGINT", stopAll);
process.on("SIGTERM", stopAll);
