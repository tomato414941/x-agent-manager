import assert from "node:assert/strict";
import test from "node:test";
import { decryptObject, encryptObject } from "../src/secrets_crypto.js";

test("encryptObject/decryptObject round trip", () => {
  const prev = process.env.AGENT_X_SECRETS_KEY;
  process.env.AGENT_X_SECRETS_KEY = "unit-test-secret-key";

  try {
    const payload = {
      accessToken: "abc",
      refreshToken: "def",
      expiresAt: "2026-02-14T00:00:00.000Z"
    };

    const encrypted = encryptObject(payload);
    assert.equal(encrypted.version, 1);
    assert.equal(Boolean(encrypted.ciphertext), true);

    const decrypted = decryptObject(encrypted);
    assert.deepEqual(decrypted, payload);
  } finally {
    if (prev === undefined) {
      delete process.env.AGENT_X_SECRETS_KEY;
    } else {
      process.env.AGENT_X_SECRETS_KEY = prev;
    }
  }
});
