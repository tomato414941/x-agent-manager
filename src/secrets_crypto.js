import crypto from "node:crypto";

const IV_LENGTH = 12;
const SALT_LENGTH = 16;
const KEY_LENGTH = 32;
const TAG_LENGTH = 16;
const PBKDF2_ITERATIONS = 210000;

function toBase64(input) {
  return Buffer.from(input).toString("base64");
}

function fromBase64(input) {
  return Buffer.from(String(input || ""), "base64");
}

function requireSecretsKey() {
  const key = process.env.AGENT_X_SECRETS_KEY;
  if (!key) {
    throw new Error("AGENT_X_SECRETS_KEY is required");
  }

  return key;
}

function deriveKey(masterKey, salt) {
  return crypto.pbkdf2Sync(masterKey, salt, PBKDF2_ITERATIONS, KEY_LENGTH, "sha256");
}

export function encryptObject(value) {
  const masterKey = requireSecretsKey();
  const salt = crypto.randomBytes(SALT_LENGTH);
  const iv = crypto.randomBytes(IV_LENGTH);
  const key = deriveKey(masterKey, salt);

  const cipher = crypto.createCipheriv("aes-256-gcm", key, iv);
  const plaintext = Buffer.from(JSON.stringify(value), "utf8");

  const encrypted = Buffer.concat([cipher.update(plaintext), cipher.final()]);
  const tag = cipher.getAuthTag();

  return {
    version: 1,
    algorithm: "aes-256-gcm",
    kdf: "pbkdf2-sha256",
    iterations: PBKDF2_ITERATIONS,
    salt: toBase64(salt),
    iv: toBase64(iv),
    tag: toBase64(tag),
    ciphertext: toBase64(encrypted),
    encryptedAt: new Date().toISOString()
  };
}

export function decryptObject(payload) {
  if (!payload || Number(payload.version) !== 1) {
    throw new Error("Unsupported secret payload version");
  }

  const masterKey = requireSecretsKey();
  const salt = fromBase64(payload.salt);
  const iv = fromBase64(payload.iv);
  const tag = fromBase64(payload.tag);
  const ciphertext = fromBase64(payload.ciphertext);

  if (!salt.length || !iv.length || !tag.length || !ciphertext.length) {
    throw new Error("Encrypted payload is invalid");
  }

  const key = deriveKey(masterKey, salt);
  const decipher = crypto.createDecipheriv("aes-256-gcm", key, iv);
  decipher.setAuthTag(tag.subarray(0, TAG_LENGTH));

  const plaintext = Buffer.concat([decipher.update(ciphertext), decipher.final()]);
  return JSON.parse(plaintext.toString("utf8"));
}
