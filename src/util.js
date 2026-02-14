import crypto from "node:crypto";

export function nowIso() {
  return new Date().toISOString();
}

export function createId(prefix) {
  return `${prefix}_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

export function toNumber(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function toPositiveInt(value, fallback = 1) {
  const parsed = Math.floor(toNumber(value, fallback));
  return parsed > 0 ? parsed : fallback;
}

export function parseIsoDate(value, fieldName) {
  const date = new Date(String(value || ""));
  if (!Number.isFinite(date.getTime())) {
    throw new Error(`${fieldName} must be a valid ISO date-time`);
  }

  return date;
}

export function sha256Hex(text) {
  return crypto.createHash("sha256").update(String(text || "")).digest("hex");
}
