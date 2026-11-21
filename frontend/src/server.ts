import "./lib/error-capture";

import { consumeLastCapturedError } from "./lib/error-capture";
import { renderErrorPage } from "./lib/error-page";

type ServerEntry = {
  fetch: (request: Request, env: unknown, ctx: unknown) => Promise<Response> | Response;
};

let serverEntryPromise: Promise<ServerEntry> | undefined;

async function getServerEntry(): Promise<ServerEntry> {
  if (!serverEntryPromise) {
    serverEntryPromise = import("@tanstack/react-start/server-entry").then(
      (m) => (m.default ?? m) as ServerEntry,
    );
  }
  return serverEntryPromise;
}

// h3 swallows in-handler throws into a normal 500 Response with body
// {"unhandled":true,"message":"HTTPError"} — try/catch alone never fires for those.
async function normalizeCatastrophicSsrResponse(response: Response): Promise<Response> {
  if (response.status < 500) return response;
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) return response;

  const body = await response.clone().text();
  if (!isH3SwallowedErrorBody(body)) return response;

  console.error(consumeLastCapturedError() ?? new Error(`h3 swallowed SSR error: ${body}`));
  return new Response(renderErrorPage(), {
    status: 500,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

function isH3SwallowedErrorBody(body: string): boolean {
  try {
    const payload = JSON.parse(body) as { unhandled?: unknown; message?: unknown };
    return payload.unhandled === true && payload.message === "HTTPError";
  } catch {
    return false;
  }
}

// Security headers for every page. connect-src allows only this origin and the AEGIS API.
// 'unsafe-inline' scripts are needed for TanStack Start's SSR hydration payload.
function apiOrigin(): string {
  try {
    const raw = import.meta.env["VITE_AEGIS_API"];
    return raw ? new URL(raw).origin : "";
  } catch {
    return "";
  }
}
const SECURITY_HEADERS: Record<string, string> = {
  "Content-Security-Policy": [
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "img-src 'self' data: blob:",
    "font-src 'self' data: https://fonts.gstatic.com",
    `connect-src 'self' ${apiOrigin()}`.trim(),
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; "),
  "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
  "Cross-Origin-Opener-Policy": "same-origin",
};
function withSecurityHeaders(response: Response): Response {
  const headers = new Headers(response.headers);
  for (const [name, value] of Object.entries(SECURITY_HEADERS)) {
    if (!headers.has(name)) headers.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers,
  });
}

// Same-origin API proxy: /api/v1/* is forwarded to the AEGIS backend. The console and the API
// live on different sites (vercel.app vs railway.app), and the SameSite=Strict session cookie is
// never sent cross-site, so in production the browser talks only to this origin.
const API_PROXY_PREFIX = "/api";
function upstreamBase(): string {
  const runtime = typeof process !== "undefined" ? process.env?.["AEGIS_API_UPSTREAM"] : undefined;
  return (runtime || import.meta.env["VITE_AEGIS_API"] || "").replace(/\/+$/, "");
}
// Hop-by-hop headers, plus accept-encoding: fetch() decodes the body but keeps the
// content-encoding header, which would make the browser decode it twice.
const DROP_REQUEST = [
  "host",
  "connection",
  "keep-alive",
  "transfer-encoding",
  "accept-encoding",
  "content-length",
];
const DROP_RESPONSE = [
  "connection",
  "keep-alive",
  "transfer-encoding",
  "content-encoding",
  "content-length",
];
async function proxyApi(request: Request): Promise<Response> {
  const upstream = upstreamBase();
  if (!upstream) {
    return Response.json({ detail: "AEGIS API upstream is not configured." }, { status: 502 });
  }
  const url = new URL(request.url);
  const target = `${upstream}${url.pathname.slice(API_PROXY_PREFIX.length)}${url.search}`;
  const headers = new Headers(request.headers);
  for (const name of DROP_REQUEST) headers.delete(name);
  headers.set("x-forwarded-host", url.host);
  headers.set("x-forwarded-proto", url.protocol.replace(":", ""));
  const hasBody = !["GET", "HEAD"].includes(request.method);
  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? await request.arrayBuffer() : null,
      redirect: "manual",
    });
    const out = new Headers(response.headers);
    for (const name of DROP_RESPONSE) out.delete(name);
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: out,
    });
  } catch (error) {
    console.error("AEGIS API proxy failed", error);
    return Response.json({ detail: "AEGIS API is unreachable." }, { status: 502 });
  }
}
function isApiPath(pathname: string): boolean {
  return pathname === `${API_PROXY_PREFIX}/v1` || pathname.startsWith(`${API_PROXY_PREFIX}/v1/`);
}

// Hosting compresses every response at the edge. Never compress a body (gzip, brotli,
// CompressionStream) or set content-encoding here or in a server route: the body gets encoded
// twice and renders garbled.
export default {
  async fetch(request: Request, env: unknown, ctx: unknown) {
    if (isApiPath(new URL(request.url).pathname)) return proxyApi(request);
    try {
      const handler = await getServerEntry();
      const response = await handler.fetch(request, env, ctx);
      return withSecurityHeaders(await normalizeCatastrophicSsrResponse(response));
    } catch (error) {
      console.error(error);
      return withSecurityHeaders(
        new Response(renderErrorPage(), {
          status: 500,
          headers: { "content-type": "text/html; charset=utf-8" },
        }),
      );
    }
  },
};
