import { createXGateway } from "./x_gateway.js";

export async function postNow(rootDir, input = {}) {
  const text = String(input.text || "").trim();
  if (!text) {
    throw new Error("text is required");
  }

  if (text.length > 280) {
    throw new Error("text must be 280 characters or fewer");
  }

  const gateway = await createXGateway(rootDir);
  return gateway.publishPost({
    text,
    idempotency_key: input.idempotencyKey || null
  });
}
