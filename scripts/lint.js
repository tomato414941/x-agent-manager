import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const rootDir = path.resolve(process.cwd());
const jsTargets = ["src", "skills", "scripts", "tests"];
const shellTargets = ["run.sh", "session.sh", "config.sh", "tools/auth.sh", "tools/queue.sh", "tools/metrics.sh"];

function collectJsFiles(dirPath) {
  if (!fs.existsSync(dirPath)) {
    return [];
  }

  const entries = fs.readdirSync(dirPath, { withFileTypes: true });
  const files = [];

  for (const entry of entries) {
    const fullPath = path.join(dirPath, entry.name);

    if (entry.isDirectory()) {
      files.push(...collectJsFiles(fullPath));
      continue;
    }

    if (entry.isFile() && fullPath.endsWith(".js")) {
      files.push(fullPath);
    }
  }

  return files;
}

function checkNodeSyntax(filePath) {
  const result = spawnSync(process.execPath, ["--check", filePath], {
    encoding: "utf8"
  });

  if (result.status !== 0) {
    process.stderr.write(`${filePath}\n`);
    process.stderr.write(result.stderr || "syntax check failed\n");
    return false;
  }

  return true;
}

function checkShellSyntax(filePath) {
  if (!fs.existsSync(filePath)) {
    return true;
  }

  const result = spawnSync("bash", ["-n", filePath], {
    encoding: "utf8"
  });

  if (result.status !== 0) {
    process.stderr.write(`${filePath}\n`);
    process.stderr.write(result.stderr || "bash syntax check failed\n");
    return false;
  }

  return true;
}

const jsFiles = jsTargets.flatMap((target) => collectJsFiles(path.join(rootDir, target)));
let failed = false;

for (const filePath of jsFiles) {
  if (!checkNodeSyntax(filePath)) {
    failed = true;
  }
}

for (const target of shellTargets) {
  const filePath = path.join(rootDir, target);
  if (!checkShellSyntax(filePath)) {
    failed = true;
  }
}

if (failed) {
  process.exit(1);
}

console.log(`lint passed: js=${jsFiles.length} shell=${shellTargets.length}`);
