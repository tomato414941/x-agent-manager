import path from "node:path";
import { appendJsonl, ensureFile, readJsonl, writeJsonl } from "./jsonl.js";

const FILE_MAP = {
  queue: "queue.jsonl",
  posts: "posts.jsonl",
  metrics: "metrics.jsonl",
  runs: "runs.jsonl",
  authEvents: "auth_events.jsonl"
};

function stateDir(rootDir) {
  return path.resolve(rootDir, "workspace", "state");
}

export function stateFilePath(rootDir, key) {
  const fileName = FILE_MAP[key];
  if (!fileName) {
    throw new Error(`Unknown state key: ${key}`);
  }

  return path.resolve(stateDir(rootDir), fileName);
}

export async function ensureState(rootDir) {
  await Promise.all(Object.keys(FILE_MAP).map((key) => ensureFile(stateFilePath(rootDir, key))));
}

export async function readState(rootDir, key) {
  return readJsonl(stateFilePath(rootDir, key));
}

export async function appendState(rootDir, key, record) {
  await appendJsonl(stateFilePath(rootDir, key), record);
}

export async function writeState(rootDir, key, records) {
  await writeJsonl(stateFilePath(rootDir, key), records);
}
