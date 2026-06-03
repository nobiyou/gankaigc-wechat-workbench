#!/usr/bin/env node
"use strict";

const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const childProcess = require("node:child_process");
const { setTimeout: sleep } = require("node:timers/promises");

const DEFAULT_PAGE_URL = "https://matrix.tencent.com/ai-detect/ai_gen_txt";
const DEFAULT_WS_URL = "wss://matrix.tencent.com/ai_gen_txt_server/getClassify";
const DEFAULT_RESULT_URL = "https://matrix.tencent.com/user/detect/result";
const DEFAULT_TIMEOUT_MS = 45000;
const DEFAULT_POLL_INTERVAL_MS = 5000;
const DEFAULT_MAX_POLLS = 6;
const APP_ID = "2089775896";
const JWT_CHAR_RE = /[A-Za-z0-9_-]+/g;

function printUsage() {
  console.log(
    [
      "Usage:",
      "  node scripts/run_zhuque_text_detector.js --input-file <file> [options]",
      "",
      "Options:",
      "  --input-file <file>            Text file to detect.",
      "  --text <text>                  Inline text to detect instead of --input-file.",
      "  --template-json <file>         Update an external-detector template JSON in place.",
      "  --output-json <file>           Write the full Zhuque probe/detection result JSON.",
      "  --bundle-result-json <file>    Attach the probe result into an existing result.json bundle.",
      "  --bundle-slot <name>           Slot name under external_detector_preflight.zhuque_tencent_text.",
      "  --capture-payload-text <text>  Raw console line or JSON containing ZHUQUE_COMBINED_PAYLOAD data.",
      "  --capture-payload-file <file>  Text/JSON file containing a ZHUQUE_COMBINED_PAYLOAD line or object.",
      "  --capture-payload-clipboard    Read the raw console line from the system clipboard.",
      "  --auth-payload-file <file>     JSON file containing {\"access_token\": \"...\", \"fp\": \"...\"}.",
      "  --auth-from-chrome-local-storage Try to recover {access_token, fp} from the local Chrome profile.",
      "  --captcha-payload-file <file>  JSON file containing {\"ticket\": \"...\", \"randstr\": \"...\"}.",
      "  --ticket <value>               TencentCaptcha ticket.",
      "  --randstr <value>              TencentCaptcha randstr.",
      "  --access-token <value>         Existing aiGenAccessToken value when available.",
      "  --fp <value>                   Explicit fp value; auto-generated when omitted.",
      "  --timeout-ms <n>               Total timeout in milliseconds. Default: 45000.",
      "  --poll-interval-ms <n>         /user/detect/result polling interval. Default: 5000.",
      "  --max-polls <n>                Maximum result polling attempts after running. Default: 6.",
      "  --page-url <url>               Detector page URL. Default: Zhuque text detector page.",
      "  --ws-url <url>                 Detector WebSocket URL.",
      "  --result-url <url>             Detector result polling URL.",
      "  --help                         Show this message.",
      "",
      "Typical flow:",
      "  1. Run this script once without captcha arguments to verify handshake and quota.",
      "  2. In the Zhuque page console, patch WebSocket.prototype.send to log {ticket, randstr}.",
      "  3. Solve the captcha once in the browser and save that JSON.",
      "  4. Rerun this script with --captcha-payload-file to perform the real detection and",
      "     write the result back into the external-detector template JSON.",
    ].join("\n")
  );
}

function parseArgs(argv) {
  const args = {
    pageUrl: DEFAULT_PAGE_URL,
    wsUrl: DEFAULT_WS_URL,
    resultUrl: DEFAULT_RESULT_URL,
    timeoutMs: DEFAULT_TIMEOUT_MS,
    pollIntervalMs: DEFAULT_POLL_INTERVAL_MS,
    maxPolls: DEFAULT_MAX_POLLS,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    const next = argv[index + 1];

    switch (token) {
      case "--help":
        args.help = true;
        break;
      case "--input-file":
        args.inputFile = next;
        index += 1;
        break;
      case "--text":
        args.text = next;
        index += 1;
        break;
      case "--template-json":
        args.templateJson = next;
        index += 1;
        break;
      case "--output-json":
        args.outputJson = next;
        index += 1;
        break;
      case "--bundle-result-json":
        args.bundleResultJson = next;
        index += 1;
        break;
      case "--bundle-slot":
        args.bundleSlot = next;
        index += 1;
        break;
      case "--capture-payload-text":
        args.capturePayloadText = next;
        index += 1;
        break;
      case "--capture-payload-file":
        args.capturePayloadFile = next;
        index += 1;
        break;
      case "--capture-payload-clipboard":
        args.capturePayloadClipboard = true;
        break;
      case "--auth-payload-file":
        args.authPayloadFile = next;
        index += 1;
        break;
      case "--auth-from-chrome-local-storage":
        args.authFromChromeLocalStorage = true;
        break;
      case "--captcha-payload-file":
        args.captchaPayloadFile = next;
        index += 1;
        break;
      case "--ticket":
        args.ticket = next;
        index += 1;
        break;
      case "--randstr":
        args.randstr = next;
        index += 1;
        break;
      case "--access-token":
        args.accessToken = next;
        index += 1;
        break;
      case "--fp":
        args.fp = next;
        index += 1;
        break;
      case "--timeout-ms":
        args.timeoutMs = Number(next);
        index += 1;
        break;
      case "--poll-interval-ms":
        args.pollIntervalMs = Number(next);
        index += 1;
        break;
      case "--max-polls":
        args.maxPolls = Number(next);
        index += 1;
        break;
      case "--page-url":
        args.pageUrl = next;
        index += 1;
        break;
      case "--ws-url":
        args.wsUrl = next;
        index += 1;
        break;
      case "--result-url":
        args.resultUrl = next;
        index += 1;
        break;
      default:
        throw new Error(`Unknown argument: ${token}`);
    }
  }

  return args;
}

function ensureParentDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function readTextInput(args) {
  if (args.text) {
    return args.text;
  }
  if (args.inputFile) {
    return fs.readFileSync(path.resolve(args.inputFile), "utf8");
  }
  return "";
}

function readClipboardText() {
  const platform = process.platform;
  const attempts = [];
  if (platform === "win32") {
    attempts.push(["powershell", ["-NoProfile", "-Command", "Get-Clipboard -Raw"]]);
  } else if (platform === "darwin") {
    attempts.push(["pbpaste", []]);
  } else {
    attempts.push(["wl-paste", ["-n"]], ["xclip", ["-selection", "clipboard", "-o"]], ["xsel", ["--clipboard", "--output"]]);
  }

  let lastError = null;
  for (const [command, commandArgs] of attempts) {
    try {
      return childProcess.execFileSync(command, commandArgs, {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (error) {
      lastError = error;
    }
  }
  throw new Error(
    `Could not read the system clipboard on platform ${platform}: ${lastError instanceof Error ? lastError.message : String(lastError)}`
  );
}

function parseJsonCandidate(candidate) {
  const trimmed = String(candidate || "").trim();
  if (!trimmed) {
    return null;
  }
  try {
    return JSON.parse(trimmed);
  } catch (error) {}

  const firstBrace = trimmed.indexOf("{");
  if (firstBrace !== -1) {
    try {
      return JSON.parse(trimmed.slice(firstBrace));
    } catch (error) {}
  }
  return null;
}

function getDefaultChromeLevelDbDir() {
  if (process.platform !== "win32") {
    return "";
  }
  const localAppData = process.env.LOCALAPPDATA || "";
  if (!localAppData) {
    return "";
  }
  return path.join(
    localAppData,
    "Google",
    "Chrome",
    "User Data",
    "Default",
    "Local Storage",
    "leveldb"
  );
}

function extractChromeAuthPayloadFromLevelDbText(text) {
  const normalized = String(text || "");
  const accessAnchor = normalized.indexOf("aiGenAccessToken");
  if (accessAnchor === -1) {
    return null;
  }

  const accessWindow = normalized.slice(Math.max(0, accessAnchor - 200), accessAnchor + 1200);
  const header = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9";
  if (!accessWindow.includes(header)) {
    return null;
  }
  const escapedHeader = header.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const rawValueMatch = accessWindow.match(/"value"\s*:\s*"([^"]+)"/i);
  const normalizedValue = rawValueMatch ? rawValueMatch[1].replace(/[^A-Za-z0-9._-]/g, "") : "";
  const tokenMatch =
    normalizedValue.match(new RegExp(`${escapedHeader}\\.([A-Za-z0-9_-]+)\\.([A-Za-z0-9_-]{20,})`)) ||
    accessWindow.match(new RegExp(`${escapedHeader}\\.([A-Za-z0-9_-]+)\\.([A-Za-z0-9_-]{20,})`));
  const payloadCorrupted = tokenMatch ? tokenMatch[1] : "";
  const signature = tokenMatch ? tokenMatch[2] : "";
  const rawExpiryMatch = accessWindow.match(/"expiry"\s*:\s*(\d{10,16})/i);
  const rawUidMatch = accessWindow.match(/"uid"\s*:\s*"@?([A-Za-z0-9_-]{16,64})"/i);
  const compact = Array.from(accessWindow)
    .filter((char) => /[A-Za-z0-9._-]/.test(char))
    .join("");
  const expiryMatch = rawExpiryMatch || compact.match(/expiry(\d{10,16})/i);
  const uidMatch = rawUidMatch || compact.match(/uid@?([A-Za-z0-9_-]{16,64})(?:[^A-Za-z0-9_-]|$)/i);

  let tokenExp = 0;
  if (payloadCorrupted) {
    try {
      const decodedPayload = Buffer.from(payloadCorrupted, "base64url").toString("utf8");
      const decodedExpMatch = decodedPayload.match(/ex(?:p)?[^0-9]{0,8}(\d{10,16})\}?/i);
      if (decodedExpMatch) {
        tokenExp = Number(decodedExpMatch[1]);
      }
    } catch (error) {}

    if (!tokenExp) {
      for (let start = 0; start < payloadCorrupted.length; start += 1) {
        for (let length = 12; length <= 48 && start + length <= payloadCorrupted.length; length += 1) {
          const candidate = payloadCorrupted.slice(start, start + length);
          try {
            const decoded = Buffer.from(candidate, "base64url").toString("utf8");
            if (/^\d{10,16}\}?$/.test(decoded)) {
              tokenExp = Number(decoded.replace(/\}?$/, ""));
            }
          } catch (error) {}
        }
      }
    }
  }

  if (!signature || !expiryMatch || !uidMatch) {
    return null;
  }
  if (!tokenExp) {
    tokenExp = Number(expiryMatch[1]);
  }

  const payloadJson = JSON.stringify({
    uid: `@${uidMatch[1]}`,
    exp: tokenExp,
  });
  const payload = Buffer.from(payloadJson, "utf8").toString("base64url");
  const expectedPrefix = "eyJ1aWQiOiJ";
  if (!payload.startsWith(expectedPrefix)) {
    return null;
  }

  const token = `${header}.${payload}.${signature}`;
  return {
    access_token: token,
    fp: "",
  };
}

function extractChromeFingerprintFromLevelDbText(text) {
  const normalized = String(text || "");
  const immortalMatch = normalized.match(/_immortal\|fp_([a-f0-9]{32})/i);
  if (immortalMatch) {
    return immortalMatch[1].toLowerCase();
  }
  const genericMatch = normalized.match(/fp[^A-Za-z0-9]{0,20}([a-f0-9]{32})/i);
  if (genericMatch) {
    return genericMatch[1].toLowerCase();
  }
  return "";
}

function recoverAuthPayloadFromChromeLocalStorage() {
  const levelDbDir = getDefaultChromeLevelDbDir();
  if (!levelDbDir || !fs.existsSync(levelDbDir)) {
    return null;
  }

  const candidates = fs
    .readdirSync(levelDbDir)
    .filter((name) => name.endsWith(".ldb"))
    .map((name) => path.join(levelDbDir, name))
    .map((filePath) => ({
      filePath,
      mtimeMs: fs.statSync(filePath).mtimeMs,
    }))
    .sort((left, right) => right.mtimeMs - left.mtimeMs)
    .slice(0, 10);

  let recoveredAccessToken = "";
  let recoveredFp = "";

  for (const candidate of candidates) {
    try {
      const rawText = fs.readFileSync(candidate.filePath, "utf8");
      if (!recoveredAccessToken) {
        const payload = extractChromeAuthPayloadFromLevelDbText(rawText);
        if (payload && payload.access_token) {
          recoveredAccessToken = payload.access_token;
        }
      }
      if (!recoveredFp) {
        recoveredFp = extractChromeFingerprintFromLevelDbText(rawText);
      }
      if (recoveredAccessToken && recoveredFp) {
        return {
          access_token: recoveredAccessToken,
          fp: recoveredFp,
        };
      }
    } catch (error) {}
  }

  if (!recoveredAccessToken && !recoveredFp) {
    return null;
  }

  return {
    access_token: recoveredAccessToken,
    fp: recoveredFp,
  };
}

function extractJsonFromConsoleText(rawText, prefixes = []) {
  const trimmed = String(rawText || "").trim();
  if (!trimmed) {
    return null;
  }

  const candidates = [trimmed];
  const lines = trimmed.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
  for (const line of lines.reverse()) {
    candidates.push(line);
    for (const prefix of prefixes) {
      const index = line.indexOf(prefix);
      if (index !== -1) {
        candidates.push(line.slice(index + prefix.length).trim());
      }
    }
  }

  for (const candidate of candidates) {
    const parsed = parseJsonCandidate(candidate);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed;
    }
  }
  return null;
}

function readPayloadFile(filePath, prefixes, label) {
  const resolved = path.resolve(filePath);
  const rawText = fs.readFileSync(resolved, "utf8");
  const parsed = extractJsonFromConsoleText(rawText, prefixes);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`Could not parse ${label} payload from file: ${resolved}`);
  }
  return parsed;
}

function readCapturePayload(args, prefixes) {
  if (args.capturePayloadText) {
    const parsed = extractJsonFromConsoleText(args.capturePayloadText, prefixes);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Could not parse capture payload from --capture-payload-text.");
    }
    return parsed;
  }
  if (args.capturePayloadFile) {
    return readPayloadFile(args.capturePayloadFile, prefixes, "combined capture");
  }
  if (args.capturePayloadClipboard) {
    const parsed = extractJsonFromConsoleText(readClipboardText(), prefixes);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Could not parse capture payload from the system clipboard.");
    }
    return parsed;
  }
  return null;
}

function extractAuthPayload(payload) {
  if (payload && typeof payload === "object" && !Array.isArray(payload) && payload.auth) {
    return payload.auth;
  }
  return payload;
}

function extractCaptchaPayload(payload) {
  if (payload && typeof payload === "object" && !Array.isArray(payload) && payload.captcha) {
    return payload.captcha;
  }
  return payload;
}

function normalizeCaptchaPayload(args) {
  let ticket = args.ticket || "";
  let randstr = args.randstr || "";

  const sharedCapturePayload = readCapturePayload(args, ["ZHUQUE_COMBINED_PAYLOAD", "ZHUQUE_CAPTCHA_PAYLOAD"]);
  if (sharedCapturePayload) {
    const payload = extractCaptchaPayload(
      sharedCapturePayload
    );
    ticket = ticket || payload.ticket || "";
    randstr = randstr || payload.randstr || "";
  }

  if (args.captchaPayloadFile) {
    const payload = extractCaptchaPayload(
      readPayloadFile(
        args.captchaPayloadFile,
        ["ZHUQUE_CAPTCHA_PAYLOAD", "ZHUQUE_COMBINED_PAYLOAD"],
        "captcha"
      )
    );
    ticket = ticket || payload.ticket || "";
    randstr = randstr || payload.randstr || "";
  }

  if (!ticket || !randstr) {
    return null;
  }

  return { ticket, randstr };
}

function normalizeAuthPayload(args) {
  let accessToken = args.accessToken || "";
  let fp = args.fp || "";

  const sharedCapturePayload = readCapturePayload(args, ["ZHUQUE_COMBINED_PAYLOAD", "ZHUQUE_AUTH_PAYLOAD"]);
  if (sharedCapturePayload) {
    const payload = extractAuthPayload(
      sharedCapturePayload
    );
    accessToken = accessToken || payload.access_token || "";
    fp = fp || payload.fp || "";
  }

  if (args.authPayloadFile) {
    const payload = extractAuthPayload(
      readPayloadFile(
        args.authPayloadFile,
        ["ZHUQUE_AUTH_PAYLOAD", "ZHUQUE_COMBINED_PAYLOAD"],
        "auth"
      )
    );
    accessToken = accessToken || payload.access_token || "";
    fp = fp || payload.fp || "";
  }

  if ((!accessToken || !fp) && args.authFromChromeLocalStorage) {
    const payload = recoverAuthPayloadFromChromeLocalStorage();
    if (payload) {
      accessToken = accessToken || payload.access_token || "";
      fp = fp || payload.fp || "";
    }
  }

  return {
    accessToken: accessToken || "",
    fp: fp || "",
  };
}

function buildFingerprint() {
  return crypto
    .createHash("sha256")
    .update(`zhuque_${Date.now()}_${Math.random()}`)
    .digest("hex")
    .slice(0, 32);
}

function computeTextLength(text) {
  return text
    .split(/\s+/)
    .filter(Boolean)
    .reduce((sum, word) => sum + (/^[a-zA-Z]+$/.test(word) ? 1 : word.length), 0);
}

function buildConsoleSnippet() {
  return [
    "(() => {",
    "  if (window.__zhuqueWsPatched) {",
    "    console.log('ZHUQUE_CAPTCHA_PATCH_ALREADY_SET');",
    "    return;",
    "  }",
    "  window.__zhuqueWsPatched = true;",
    "  const originalSend = WebSocket.prototype.send;",
    "  WebSocket.prototype.send = function patchedSend(data) {",
    "    try {",
    "      const parsed = JSON.parse(data);",
    "      if (parsed && parsed.ticket && parsed.randstr) {",
    "        console.log('ZHUQUE_CAPTCHA_PAYLOAD', JSON.stringify({ ticket: parsed.ticket, randstr: parsed.randstr }));",
    "      }",
    "    } catch (error) {}",
    "    return originalSend.call(this, data);",
    "  };",
    "  console.log('ZHUQUE_CAPTCHA_PATCH_READY');",
    "})();",
  ].join("\n");
}

function buildCombinedCaptureSnippet() {
  return [
    "(() => {",
    "  const state = window.__zhuqueCaptureState = window.__zhuqueCaptureState || {};",
    "  const readAuth = () => {",
    "    const tokenRaw = localStorage.getItem('aiGenAccessToken');",
    "    let accessToken = null;",
    "    try {",
    "      accessToken = tokenRaw ? JSON.parse(tokenRaw).value || null : null;",
    "    } catch (error) {}",
    "    return {",
    "      access_token: accessToken,",
    "      fp: localStorage.getItem('fp') || null,",
    "    };",
    "  };",
    "  const emitAuth = () => {",
    "    state.auth = readAuth();",
    "    console.log('ZHUQUE_AUTH_PAYLOAD', JSON.stringify(state.auth));",
    "    return state.auth;",
    "  };",
    "  const emitCombined = () => {",
    "    if (state.auth && state.captcha) {",
    "      console.log('ZHUQUE_COMBINED_PAYLOAD', JSON.stringify({ auth: state.auth, captcha: state.captcha }));",
    "    }",
    "  };",
    "  window.__dumpZhuqueCombinedPayload = () => {",
    "    emitAuth();",
    "    emitCombined();",
    "  };",
    "  emitAuth();",
    "  if (!window.__zhuqueWsPatched) {",
    "    window.__zhuqueWsPatched = true;",
    "    const originalSend = WebSocket.prototype.send;",
    "    WebSocket.prototype.send = function patchedSend(data) {",
    "      try {",
    "        const parsed = JSON.parse(data);",
    "        if (parsed && parsed.ticket && parsed.randstr) {",
    "          state.captcha = { ticket: parsed.ticket, randstr: parsed.randstr };",
    "          console.log('ZHUQUE_CAPTCHA_PAYLOAD', JSON.stringify(state.captcha));",
    "          emitCombined();",
    "        }",
    "      } catch (error) {}",
    "      return originalSend.call(this, data);",
    "    };",
    "  } else {",
    "    console.log('ZHUQUE_CAPTCHA_PATCH_ALREADY_SET');",
    "  }",
    "  console.log('ZHUQUE_CAPTURE_READY');",
    "})();",
  ].join("\n");
}

function buildAuthDumpSnippet() {
  return [
    "(() => {",
    "  const tokenRaw = localStorage.getItem('aiGenAccessToken');",
    "  let accessToken = null;",
    "  try {",
    "    accessToken = tokenRaw ? JSON.parse(tokenRaw).value || null : null;",
    "  } catch (error) {}",
    "  console.log('ZHUQUE_AUTH_PAYLOAD', JSON.stringify({",
    "    access_token: accessToken,",
    "    fp: localStorage.getItem('fp') || null,",
    "  }));",
    "})();",
  ].join("\n");
}

function buildNeedsTicketNotes(inputLength) {
  return [
    "Handshake succeeded, but Zhuque text detection still needs a real TencentCaptcha callback payload.",
    `Current input length: ${inputLength}.`,
    "",
    "Next steps:",
    "1. Open the Zhuque text detector page in Chrome.",
    "2. Paste the following one-shot snippet into the page console before clicking 检测:",
    buildCombinedCaptureSnippet(),
    "3. Click 立即检测 and complete the captcha once.",
    "4. Copy the console line that starts with ZHUQUE_COMBINED_PAYLOAD into a text file.",
    "5. Rerun this script with --capture-payload-file <that-text-file>.",
    "6. If the combined line does not appear, fall back to ZHUQUE_CAPTCHA_PAYLOAD with --captcha-payload-file.",
  ].join("\n");
}

function buildNeedsBrowserAuthNotes(inputLength) {
  return [
    "Zhuque rejected the anonymous handshake before captcha, so this run needs browser-derived auth data.",
    `Current input length: ${inputLength}.`,
    "",
    "Next steps:",
    "1. Open the Zhuque text detector page in Chrome while already logged in or after refreshing the page once.",
    "2. Paste the following one-shot snippet into the page console:",
    buildCombinedCaptureSnippet(),
    "3. Click 立即检测, finish the captcha once, and copy the line that starts with ZHUQUE_COMBINED_PAYLOAD into a text file.",
    "4. Rerun this script with --capture-payload-file <that-text-file>.",
    "5. If the combined line does not appear, fall back to separate ZHUQUE_AUTH_PAYLOAD / ZHUQUE_CAPTCHA_PAYLOAD lines and pass --auth-payload-file plus --captcha-payload-file.",
  ].join("\n");
}

function redactPayload(payload) {
  if (!payload || typeof payload !== "object") {
    return payload;
  }
  const clone = { ...payload };
  if (clone.access_token) {
    clone.access_token = "<redacted>";
  }
  if (clone.ticket) {
    clone.ticket = "<redacted>";
  }
  if (clone.randstr) {
    clone.randstr = "<redacted>";
  }
  return clone;
}

async function pollForResult({ resultUrl, cos, startTime, pollIntervalMs, maxPolls, rawResult }) {
  for (let attempt = 1; attempt <= maxPolls; attempt += 1) {
    const url = new URL(resultUrl);
    url.searchParams.set("cos", cos);
    url.searchParams.set("startTime", String(startTime));
    const response = await fetch(url);
    const body = await response.json();
    rawResult.polls.push({
      attempt,
      http_status: response.status,
      body,
    });

    if (body && body.success === true && body.data) {
      return typeof body.data === "string" ? JSON.parse(body.data) : body.data;
    }
    if (body && body.success === false) {
      throw new Error(body.message || "Zhuque result polling failed.");
    }
    if (attempt < maxPolls) {
      await sleep(pollIntervalMs);
    }
  }

  throw new Error("Zhuque result polling timed out.");
}

async function runDetector(args) {
  const text = readTextInput(args);
  const captchaPayload = normalizeCaptchaPayload(args);
  const authPayloadInput = normalizeAuthPayload(args);
  const inputLength = text ? computeTextLength(text) : 0;
  const fp = authPayloadInput.fp || buildFingerprint();
  const initialAuthMode = authPayloadInput.accessToken
    ? (authPayloadInput.fp ? "access_token_fp" : "access_token")
    : "fp";
  let currentAccessToken = authPayloadInput.accessToken || "";

  if (!captchaPayload && !text) {
    throw new Error("Provide --input-file or --text so the script knows what to detect.");
  }
  if (captchaPayload && inputLength < 350) {
    throw new Error(`Zhuque text detection needs at least 350 characters. Current length: ${inputLength}.`);
  }

  const startedAt = new Date().toISOString();
  const rawResult = {
    websocket_events: [],
    polls: [],
    console_snippet: buildConsoleSnippet(),
    combined_capture_snippet: buildCombinedCaptureSnippet(),
  };

  let availableUses = null;
  let detectorPayload = null;
  let pendingPoll = null;

  const result = await new Promise((resolve, reject) => {
    let settled = false;
    let timeoutHandle = null;
    let phase = "auth";
    const resentAccessTokenValues = new Set();

    function finish(payload) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeoutHandle);
      resolve(payload);
    }

    function fail(error) {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timeoutHandle);
      reject(error);
    }

    function effectiveAuthMode() {
      if (initialAuthMode === "fp" && currentAccessToken) {
        return "fp_bootstrap_access_token";
      }
      return initialAuthMode;
    }

    function buildAuthPayload(accessToken) {
      const payload = {};
      if (accessToken) {
        payload.access_token = accessToken;
      }
      if (fp) {
        payload.fp = fp;
      }
      return payload;
    }

    const ws = new WebSocket(args.wsUrl);
    timeoutHandle = setTimeout(() => {
      try {
        ws.close();
      } catch (error) {}
      fail(new Error(`Zhuque detector timed out after ${args.timeoutMs}ms.`));
    }, args.timeoutMs);

    ws.onopen = () => {
      const authPayload = buildAuthPayload(currentAccessToken);
      rawResult.websocket_events.push({
        type: "open",
        auth_payload: redactPayload(authPayload),
      });
      rawResult.websocket_events.push({
        type: "send_auth",
        data: redactPayload(authPayload),
      });
      ws.send(JSON.stringify(authPayload));
    };

    ws.onerror = (event) => {
      rawResult.websocket_events.push({
        type: "error",
        message: String(event?.message || event),
      });
    };

    ws.onmessage = async (event) => {
      const rawText = typeof event.data === "string" ? event.data : "";
      let parsed = rawText;
      try {
        parsed = JSON.parse(rawText);
      } catch (error) {}

      rawResult.websocket_events.push({
        type: "message",
        data: redactPayload(parsed),
      });

      if (parsed && typeof parsed === "object" && typeof parsed.availableUses === "number") {
        availableUses = parsed.availableUses;
      }

      if (parsed && typeof parsed === "object" && typeof parsed.access_token === "string" && parsed.access_token) {
        currentAccessToken = parsed.access_token;
        if (!resentAccessTokenValues.has(parsed.access_token)) {
          const accessTokenPayload = buildAuthPayload(parsed.access_token);
          resentAccessTokenValues.add(parsed.access_token);
          rawResult.websocket_events.push({
            type: "send_access_token",
            data: redactPayload(accessTokenPayload),
          });
          ws.send(JSON.stringify(accessTokenPayload));
        }
      }

      if (!captchaPayload && phase === "auth" && parsed && parsed.status === "success") {
        phase = "needs_ticket";
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "needs_ticket",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: buildNeedsTicketNotes(inputLength),
          raw_result: rawResult,
        });
        return;
      }

      if (phase === "auth" && captchaPayload && parsed && parsed.status === "success") {
        phase = "captcha";
        const sanitizedPayload = redactPayload(captchaPayload);
        rawResult.websocket_events.push({
          type: "send_captcha",
          data: sanitizedPayload,
        });
        ws.send(JSON.stringify(captchaPayload));
        return;
      }

      if (phase === "auth" && parsed && parsed.status === "reauth") {
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "needs_browser_auth",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: [
            "Zhuque requested a browser re-auth before detection can continue.",
            "",
            buildNeedsBrowserAuthNotes(inputLength),
          ].join("\n"),
          raw_result: {
            ...rawResult,
            auth_dump_snippet: buildAuthDumpSnippet(),
          },
        });
        return;
      }

      if (phase === "auth" && parsed && parsed.status === "failed" && parsed.msg === "Invalid request") {
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "needs_browser_auth",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: buildNeedsBrowserAuthNotes(inputLength),
          raw_result: {
            ...rawResult,
            auth_dump_snippet: buildAuthDumpSnippet(),
          },
        });
        return;
      }

      if (phase === "captcha" && parsed && parsed.code === "1" && parsed.evil_level === "0") {
        phase = "text";
        rawResult.websocket_events.push({
          type: "send_text",
          input_length: inputLength,
        });
        ws.send(JSON.stringify({ text }));
        return;
      }

      if (
        phase === "captcha" &&
        parsed &&
        ((typeof parsed.code === "string" && parsed.code !== "1") || parsed.status === "failed")
      ) {
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "captcha_rejected",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: "The provided TencentCaptcha payload was rejected by Zhuque. Capture a fresh ticket/randstr pair and retry.",
          raw_result: rawResult,
        });
        return;
      }

      if (phase === "text" && parsed && parsed.status === "running" && parsed.cos) {
        phase = "polling";
        const startTime = Date.now();
        try {
          pendingPoll = pollForResult({
            resultUrl: args.resultUrl,
            cos: parsed.cos,
            startTime,
            pollIntervalMs: args.pollIntervalMs,
            maxPolls: args.maxPolls,
            rawResult,
          });
          detectorPayload = await pendingPoll;
          try {
            ws.close();
          } catch (error) {}
          finish({
            detector: "zhuque_tencent_text",
            detector_url: args.pageUrl,
            captured_at: startedAt,
            status: "done",
            confidence: detectorPayload.confidence ?? null,
            available_uses: typeof parsed.availableUses === "number" ? parsed.availableUses : availableUses,
            input_length: inputLength,
            auth_mode: effectiveAuthMode(),
            notes: "Detection completed through the Zhuque WebSocket plus result polling flow.",
            raw_result: {
              ...rawResult,
              final_payload: detectorPayload,
            },
          });
        } catch (error) {
          try {
            ws.close();
          } catch (closeError) {}
          fail(error);
        }
        return;
      }

      if (phase === "text" && parsed && parsed.status === "success" && parsed.confidence !== undefined) {
        detectorPayload = parsed;
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "done",
          confidence: detectorPayload.confidence ?? null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: "Detection completed directly from the Zhuque WebSocket result payload.",
          raw_result: {
            ...rawResult,
            final_payload: detectorPayload,
          },
        });
        return;
      }

      if (parsed && parsed.status === "failed") {
        try {
          ws.close();
        } catch (error) {}
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "failed",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: parsed.msg || "Zhuque returned a failed status.",
          raw_result: rawResult,
        });
      }
    };

    ws.onclose = async (event) => {
      rawResult.websocket_events.push({
        type: "close",
        code: event.code,
        reason: event.reason,
      });
      if (pendingPoll) {
        return;
      }
      if (!settled && phase !== "needs_ticket") {
        finish({
          detector: "zhuque_tencent_text",
          detector_url: args.pageUrl,
          captured_at: startedAt,
          status: "closed_without_result",
          confidence: null,
          available_uses: availableUses,
          input_length: inputLength,
          auth_mode: effectiveAuthMode(),
          notes: "The WebSocket closed before Zhuque returned a final result.",
          raw_result: rawResult,
        });
      }
    };
  });

  return result;
}

function writeTemplate(templatePath, payload) {
  const resolved = path.resolve(templatePath);
  let template = {};
  if (fs.existsSync(resolved)) {
    template = JSON.parse(fs.readFileSync(resolved, "utf8"));
  }

  template.confidence = payload.confidence ?? null;
  template.detector_url = payload.detector_url;
  template.captured_at = payload.captured_at;
  template.notes = payload.notes;
  template.raw_result = payload.raw_result;

  ensureParentDir(resolved);
  fs.writeFileSync(resolved, `${JSON.stringify(template, null, 2)}\n`, "utf8");
}

function writeBundleProbe(bundleResultPath, slot, payload) {
  const resolved = path.resolve(bundleResultPath);
  if (!fs.existsSync(resolved)) {
    throw new Error(`Bundle result JSON not found: ${resolved}`);
  }

  const bundle = JSON.parse(fs.readFileSync(resolved, "utf8"));
  if (!bundle || typeof bundle !== "object" || Array.isArray(bundle)) {
    throw new Error(`Bundle result JSON must be an object: ${resolved}`);
  }

  bundle.external_detector_preflight = bundle.external_detector_preflight || {};
  bundle.external_detector_preflight.zhuque_tencent_text =
    bundle.external_detector_preflight.zhuque_tencent_text || {};
  bundle.external_detector_preflight.zhuque_tencent_text[slot] = payload;

  ensureParentDir(resolved);
  fs.writeFileSync(resolved, `${JSON.stringify(bundle, null, 2)}\n`, "utf8");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printUsage();
    return 0;
  }

  const payload = await runDetector(args);

  if (args.outputJson) {
    const resolved = path.resolve(args.outputJson);
    ensureParentDir(resolved);
    fs.writeFileSync(resolved, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
  }
  if (args.templateJson) {
    writeTemplate(args.templateJson, payload);
  }
  if (args.bundleResultJson) {
    const slot = args.bundleSlot || "probe";
    writeBundleProbe(args.bundleResultJson, slot, payload);
  }

  console.log(JSON.stringify(payload, null, 2));
  return 0;
}

module.exports = {
  extractChromeAuthPayloadFromLevelDbText,
  extractChromeFingerprintFromLevelDbText,
  extractJsonFromConsoleText,
  recoverAuthPayloadFromChromeLocalStorage,
  normalizeAuthPayload,
  normalizeCaptchaPayload,
  runDetector,
  parseArgs,
  pollForResult,
};

if (require.main === module) {
  main().then(
    (code) => {
      process.exitCode = code;
    },
    (error) => {
      console.error(
        JSON.stringify(
          {
            detector: "zhuque_tencent_text",
            status: "failed",
            error: {
              message: error instanceof Error ? error.message : String(error),
              stack: error instanceof Error ? error.stack : "",
            },
          },
          null,
          2
        )
      );
      process.exitCode = 1;
    }
  );
}
