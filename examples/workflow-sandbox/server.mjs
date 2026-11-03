import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

export function allowed(method, path) {
  return (method === "POST" && (path === "/api/v1/auth/login" || /^\/api\/v2\/workflows\/[a-z0-9][a-z0-9_-]{0,63}\/tenants\/[a-zA-Z0-9_-]+\/ingest$/.test(path))) ||
    (method === "GET" && (/^\/api\/v2\/tenants\/[a-zA-Z0-9_-]+\/runs\/[a-zA-Z0-9_-]+$/.test(path) || path === "/api/v1/auth/me"));
}
export function createSandbox(targetValue, upstreamFetch = fetch) {
  const target = new URL(targetValue);
  if (target.username || target.password || target.search || target.hash || target.pathname !== "/" ||
      !(target.protocol === "https:" || target.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(target.hostname))) throw new Error("Use a public HTTPS origin or a local HTTP origin.");
  return createServer(async (request, response) => {
    const localOrigins = ["http://127.0.0.1:" + request.socket.localPort, "http://localhost:" + request.socket.localPort];
    const send = (status, body, type = "application/json") => { response.writeHead(status, {
      "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
      "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    }); response.end(body); };
    try {
    if (!localOrigins.some(origin => new URL(origin).host === request.headers.host) || request.headers.origin && !localOrigins.includes(request.headers.origin)) return send(403, '{"detail":"Local same-origin access required"}');
    const url = new URL(request.url, localOrigins[0]);
    if (url.pathname === "/config" && request.method === "GET") return send(200, JSON.stringify({ target: target.origin }));
    if (url.pathname.startsWith("/proxy/")) {
      const path = url.pathname.slice(6);
      if (url.search || !allowed(request.method, path)) return send(403, '{"detail":"Proxy route is not permitted"}');
      const chunks = []; let size = 0;
      for await (const chunk of request) { size += chunk.length; if (size > 256 * 1024) return send(413, '{"detail":"Payload exceeds 256 KiB"}'); chunks.push(chunk); }
      const headers = { Accept: "application/json", "Content-Type": "application/json" };
      if (request.headers.authorization) headers.Authorization = request.headers.authorization;
      if (request.headers["idempotency-key"]) headers["Idempotency-Key"] = request.headers["idempotency-key"];
      const controller = new AbortController(); const timer = setTimeout(() => controller.abort(), 15000);
      try {
        const result = await upstreamFetch(new URL(path, target), { method: request.method, headers,
          body: request.method === "GET" ? undefined : Buffer.concat(chunks), redirect: "manual", signal: controller.signal });
        if (result.status >= 300 && result.status < 400) return send(502, '{"detail":"Upstream redirects are not allowed"}');
        const blocks = []; let length = 0;
        for await (const block of result.body) { length += block.length; if (length > 2 * 1024 * 1024) throw new Error(); blocks.push(block); }
        send(result.status, Buffer.concat(blocks));
      } catch { send(502, '{"detail":"TierX request failed or exceeded limits"}'); }
      finally { clearTimeout(timer); }
      return;
    }
    const file = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
    if (request.method !== "GET" || !["index.html", "app.js", "style.css"].includes(file)) return send(404, "Not found", "text/plain");
    try { send(200, await readFile(new URL(file, import.meta.url)), { "index.html": "text/html", "app.js": "text/javascript", "style.css": "text/css" }[file]); }
    catch { send(500, "File unavailable", "text/plain"); }
    } catch {
      if (!response.headersSent && !response.destroyed) send(400, '{"detail":"Request could not be read"}');
      else response.destroy();
    }
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.SANDBOX_PORT || 4174);
  createSandbox(process.env.TIERX_TARGET || "http://127.0.0.1:8080").listen(port, "127.0.0.1", () => console.log(`TierX Workflow Sandbox: http://127.0.0.1:${port}`));
}
