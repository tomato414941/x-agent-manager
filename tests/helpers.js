import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const testDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(testDir, "..");
const cliPath = path.join(projectRoot, "src", "cli.js");

export function runCli(args, cwd, env = {}) {
  const result = spawnSync(process.execPath, [cliPath, ...args], {
    cwd,
    encoding: "utf8",
    env: {
      ...process.env,
      ...env
    }
  });

  if (result.status !== 0) {
    throw new Error(
      [
        `Command failed: node src/cli.js ${args.join(" ")}`,
        `status=${result.status}`,
        `stdout=${result.stdout}`,
        `stderr=${result.stderr}`
      ].join("\n")
    );
  }

  return result.stdout.trim();
}

export function runCliJson(args, cwd, env = {}) {
  const output = runCli(args, cwd, env);
  return output ? JSON.parse(output) : null;
}

export function readJsonl(filePath) {
  if (!fs.existsSync(filePath)) {
    return [];
  }

  return fs
    .readFileSync(filePath, "utf8")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
}
