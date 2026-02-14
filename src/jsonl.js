import fs from "node:fs/promises";
import path from "node:path";

export async function ensureFile(filePath) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });

  try {
    await fs.writeFile(filePath, "", { flag: "wx" });
  } catch (error) {
    if (error.code !== "EEXIST") {
      throw error;
    }
  }
}

export async function readJsonl(filePath) {
  try {
    const raw = await fs.readFile(filePath, "utf8");
    return raw
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => JSON.parse(line));
  } catch (error) {
    if (error.code === "ENOENT") {
      return [];
    }

    throw error;
  }
}

export async function appendJsonl(filePath, record) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.appendFile(filePath, `${JSON.stringify(record)}\n`, "utf8");
}

export async function writeJsonl(filePath, records) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  const body = records.map((record) => JSON.stringify(record)).join("\n");
  await fs.writeFile(filePath, body ? `${body}\n` : "", "utf8");
}
