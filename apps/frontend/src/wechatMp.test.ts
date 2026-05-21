import { startWechatMpLoginQrcode } from "./api/workbench.ts";

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) {
    throw new Error(message);
  }
}

async function testStartWechatMpLoginQrcodeReturnsBlobUrl() {
  const originalFetch = globalThis.fetch;
  const originalCreateObjectUrl = URL.createObjectURL;

  const calls: string[] = [];
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(new Blob(["fake-image"], { type: "image/jpeg" }), {
      status: 200,
      headers: { "Content-Type": "image/jpeg" },
    });
  }) as typeof fetch;

  URL.createObjectURL = ((blob: Blob) => {
    assert(blob.type === "image/jpeg", "blob type should be image/jpeg");
    return "blob:wechat-qrcode";
  }) as typeof URL.createObjectURL;

  try {
    const url = await startWechatMpLoginQrcode();
    assert(url === "blob:wechat-qrcode", "should return created blob url");
    assert(calls.length === 1, "should request qrcode endpoint once");
    assert(
      calls[0] === "http://localhost:8000/api/wechat-mp/login/qrcode",
      "should request qrcode endpoint directly",
    );
  } finally {
    globalThis.fetch = originalFetch;
    URL.createObjectURL = originalCreateObjectUrl;
  }
}

await testStartWechatMpLoginQrcodeReturnsBlobUrl();
