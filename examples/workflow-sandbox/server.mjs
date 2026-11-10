import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { aiConfiguration, createGenerator } from "./generator.mjs";
import { scenarioStore } from "./store.mjs";

export function allowed(method, path) {
  return (
    (method === "POST" &&
      (path === "/api/v1/auth/login" ||
        /^\/api\/v2\/workflows\/[a-z0-9][a-z0-9_-]{0,63}\/tenants\/[a-zA-Z0-9_-]+\/ingest$/.test(
          path,
        ))) ||
    (method === "GET" &&
      (/^\/api\/v2\/tenants\/[a-zA-Z0-9_-]+\/runs\/[a-zA-Z0-9_-]+$/.test(
        path,
      ) ||
        path === "/api/v1/auth/me"))
  );
}
export function createSandbox(
  targetValue,
  upstreamFetch = fetch,
  uiValue = targetValue,
  options = {},
) {
  const ai = options.ai || aiConfiguration();
  const generate = createGenerator(ai, options.generationFetch || fetch);
  const store = scenarioStore(
    options.dataDir ||
      process.env.SANDBOX_DATA_DIR ||
      fileURLToPath(new URL(".sandbox-data/", import.meta.url)),
  );
  const target = new URL(targetValue);
  const ui = new URL(uiValue);
  const extraTargets =
    options.targets || JSON.parse(process.env.SANDBOX_TARGETS || "[]");
  if (!Array.isArray(extraTargets) || extraTargets.length > 20)
    throw new Error("SANDBOX_TARGETS must be an array of at most 20 targets.");
  const targets = [
    { label: "Default", target: target.origin, ui_origin: ui.origin },
    ...extraTargets,
  ].map((item) => {
    const origin = new URL(item.target),
      dashboard = new URL(item.ui_origin || item.target);
    for (const value of [origin, dashboard])
      if (
        value.username ||
        value.password ||
        value.search ||
        value.hash ||
        value.pathname !== "/" ||
        !(
          value.protocol === "https:" ||
          (value.protocol === "http:" &&
            ["localhost", "127.0.0.1", "[::1]"].includes(value.hostname))
        )
      )
        throw new Error(
          "Targets must be HTTPS or localhost HTTP origins without credentials or paths.",
        );
    return {
      label: String(item.label || origin.origin).slice(0, 100),
      target: origin.origin,
      ui_origin: dashboard.origin,
    };
  });
  if (
    ui.username ||
    ui.password ||
    ui.search ||
    ui.hash ||
    ui.pathname !== "/" ||
    !["http:", "https:"].includes(ui.protocol)
  )
    throw new Error("Use a UI origin without credentials or a path.");
  if (
    target.username ||
    target.password ||
    target.search ||
    target.hash ||
    target.pathname !== "/" ||
    !(
      target.protocol === "https:" ||
      (target.protocol === "http:" &&
        ["localhost", "127.0.0.1", "[::1]"].includes(target.hostname))
    )
  )
    throw new Error("Use a public HTTPS origin or a local HTTP origin.");
  return createServer(async (request, response) => {
    const localOrigins = [
      "http://127.0.0.1:" + request.socket.localPort,
      "http://localhost:" + request.socket.localPort,
    ];
    const send = (status, body, type = "application/json") => {
      response.writeHead(status, {
        "Content-Type": type,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy":
          "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
      });
      response.end(body);
    };
    try {
      if (
        !localOrigins.some(
          (origin) => new URL(origin).host === request.headers.host,
        ) ||
        (request.headers.origin &&
          !localOrigins.includes(request.headers.origin))
      )
        return send(403, '{"detail":"Local same-origin access required"}');
      const url = new URL(request.url, localOrigins[0]);
      if (url.pathname === "/config" && request.method === "GET")
        return send(
          200,
          JSON.stringify({
            target: target.origin,
            ui_origin: ui.origin,
            targets,
            ai: {
              enabled: ai.provider !== "disabled",
              provider: ai.provider,
              model: ai.model || null,
            },
          }),
        );
      if (
        (url.pathname === "/ai/generate" && request.method === "POST") ||
        url.pathname.startsWith("/scenarios")
      ) {
        if (url.search)
          return send(400, '{"detail":"Query strings are not supported"}');
        const controller = new AbortController(),
          abort = () => controller.abort();
        response.on("close", abort);
        try {
          let body = {};
          if (request.method === "POST") {
            const chunks = [];
            let size = 0;
            for await (const chunk of request) {
              size += chunk.length;
              if (size > 2 * 1024 * 1024)
                return send(413, '{"detail":"Scenario request exceeds 2 MiB"}');
              chunks.push(chunk);
            }
            body = JSON.parse(Buffer.concat(chunks).toString());
          }
          if (url.pathname === "/ai/generate") {
            const result = await generate(body, controller.signal);
            const saved = await store.save({
              name: "Generated synthetic batch",
              description: body.description,
              preset: body.preset,
              negative: body.negative,
              missing_path: body.missing_path,
              schema: body.schema ?? null,
              ...result,
            });
            return send(
              200,
              JSON.stringify({ ...result, archive_id: saved.id }),
            );
          }
          if (url.pathname === "/scenarios" && request.method === "POST")
            return send(201, JSON.stringify(await store.save(body)));
          if (url.pathname === "/scenarios" && request.method === "GET")
            return send(200, JSON.stringify({ items: await store.list() }));
          const match = url.pathname.match(
            /^\/scenarios\/([a-f0-9-]{36})(?:\/(outcomes|export))?$/,
          );
          if (match && request.method === "GET" && match[2] !== "outcomes")
            return send(
              200,
              JSON.stringify(
                await (match[2] === "export"
                  ? store.export(match[1])
                  : store.read(match[1])),
              ),
            );
          if (match && request.method === "POST" && match[2] === "outcomes")
            return send(
              200,
              JSON.stringify(await store.outcome(match[1], body)),
            );
          return send(404, '{"detail":"Unknown local scenario route"}');
        } catch (error) {
          if (response.destroyed) return;
          const message = String(
            error.message || "Local scenario request failed",
          );
          const safe =
            (ai.apiKey && message.includes(ai.apiKey)) ||
            (ai.url && message.includes(ai.url))
              ? "Local AI request failed; check provider configuration."
              : message;
          return send(
            error.status || (error.code === "ENOENT" ? 404 : 400),
            JSON.stringify({ detail: safe }),
          );
        } finally {
          response.removeListener("close", abort);
        }
      }
      if (url.pathname.startsWith("/proxy/")) {
        const path = url.pathname.slice(6);
        if (url.search || !allowed(request.method, path))
          return send(403, '{"detail":"Proxy route is not permitted"}');
        const chunks = [];
        let size = 0;
        for await (const chunk of request) {
          size += chunk.length;
          if (size > 256 * 1024)
            return send(413, '{"detail":"Payload exceeds 256 KiB"}');
          chunks.push(chunk);
        }
        const headers = {
          Accept: "application/json",
          "Content-Type": "application/json",
        };
        if (request.headers.authorization)
          headers.Authorization = request.headers.authorization;
        if (request.headers["idempotency-key"])
          headers["Idempotency-Key"] = request.headers["idempotency-key"];
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 15000);
        const disconnected = () => controller.abort();
        response.on("close", disconnected);
        try {
          // Request input can change only the pathname, never the upstream authority.
          const selected = request.headers["x-sandbox-target"] || target.origin;
          if (!targets.some((item) => item.target === selected))
            return send(
              400,
              '{"detail":"Target is not configured on this sandbox"}',
            );
          const destination = new URL(selected);
          destination.pathname = path;
          destination.search = "";
          destination.hash = "";
          const result = await upstreamFetch(destination, {
            method: request.method,
            headers,
            body: request.method === "GET" ? undefined : Buffer.concat(chunks),
            redirect: "manual",
            signal: controller.signal,
          });
          if (result.status >= 300 && result.status < 400)
            return send(502, '{"detail":"Upstream redirects are not allowed"}');
          const blocks = [];
          let length = 0;
          for await (const block of result.body) {
            length += block.length;
            if (length > 2 * 1024 * 1024) throw new Error();
            blocks.push(block);
          }
          send(result.status, Buffer.concat(blocks));
        } catch {
          send(502, '{"detail":"TierX request failed or exceeded limits"}');
        } finally {
          clearTimeout(timer);
          response.removeListener("close", disconnected);
        }
        return;
      }
      const file = url.pathname === "/" ? "index.html" : url.pathname.slice(1);
      if (
        request.method !== "GET" ||
        ![
          "index.html",
          "app.js",
          "style.css",
          "scenario.mjs",
          "runner.mjs",
          "scenario-ui.js",
        ].includes(file)
      )
        return send(404, "Not found", "text/plain");
      try {
        send(
          200,
          await readFile(new URL(file, import.meta.url)),
          file === "index.html"
            ? "text/html"
            : file === "style.css"
              ? "text/css"
              : "text/javascript",
        );
      } catch {
        send(500, "File unavailable", "text/plain");
      }
    } catch {
      if (!response.headersSent && !response.destroyed)
        send(400, '{"detail":"Request could not be read"}');
      else response.destroy();
    }
  });
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.SANDBOX_PORT || 4174);
  const target = process.env.TIERX_TARGET || "http://127.0.0.1:8080";
  createSandbox(target, fetch, process.env.TIERX_UI_ORIGIN || target).listen(
    port,
    "127.0.0.1",
    () => console.log(`TierX Workflow Sandbox: http://127.0.0.1:${port}`),
  );
}
