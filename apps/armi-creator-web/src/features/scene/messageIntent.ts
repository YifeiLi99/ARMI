const MAX_REQUEST_BYTES = 256 * 1024;
const IDEMPOTENCY_PREFIX = "creator-input-v1.";

export type MessageValidation =
  { valid: true } | { valid: false; message: string };

function hasInvalidUnicode(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (!(next >= 0xdc00 && next <= 0xdfff)) {
        return true;
      }
      index += 1;
    } else if (code >= 0xdc00 && code <= 0xdfff) {
      return true;
    }
  }
  return false;
}

export function validateCreatorMessage(message: string): MessageValidation {
  if (message.includes("\u0000") || hasInvalidUnicode(message)) {
    return { valid: false, message: "输入包含无法接纳的字符。" };
  }
  if (message.trim().length === 0) {
    return { valid: false, message: "请输入至少一个非空白字符。" };
  }
  const request = JSON.stringify({ contract_version: "1.0", message });
  if (new TextEncoder().encode(request).byteLength > MAX_REQUEST_BYTES) {
    return { valid: false, message: "输入超过 256 KiB 接纳上限。" };
  }
  return { valid: true };
}

export function createCreatorInputKey(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return `${IDEMPOTENCY_PREFIX}${btoa(binary)
    .replaceAll("+", "-")
    .replaceAll("/", "_")
    .replace(/=+$/u, "")}`;
}
