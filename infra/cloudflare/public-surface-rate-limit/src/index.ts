interface Env {
  PUBLIC_SURFACE_RATE_LIMITER: RateLimit;
  ORIGIN_BASE_URL: string;
}

const RATE_LIMITED_JSON = JSON.stringify({ error: "rate_limited" });

function protectedSurface(pathname: string): string | null {
  if (pathname === "/api/auth/pair") {
    return "pair";
  }
  if (/^\/u\/[^/]+$/.test(pathname)) {
    return "upload-link";
  }
  return null;
}

function remoteKey(request: Request): string {
  const connectingIp = request.headers.get("cf-connecting-ip");
  if (connectingIp) {
    return connectingIp.trim();
  }
  const forwardedFor = request.headers.get("x-forwarded-for");
  if (forwardedFor) {
    return forwardedFor.split(",", 1)[0].trim();
  }
  return "unknown";
}

function originUrl(requestUrl: URL, originBaseUrl: string): URL {
  const normalizedOrigin = originBaseUrl.trim().replace(/\/+$/, "");
  if (!normalizedOrigin) {
    throw new Error("ORIGIN_BASE_URL is not configured");
  }
  return new URL(`${requestUrl.pathname}${requestUrl.search}`, normalizedOrigin);
}

function proxyHeaders(request: Request, publicHost: string): Headers {
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.set("x-forwarded-host", publicHost);
  headers.set("x-edge-rate-limit", "cloudflare-worker");
  return headers;
}

export default {
  async fetch(request, env): Promise<Response> {
    const incomingUrl = new URL(request.url);
    const surface = protectedSurface(incomingUrl.pathname);
    if (surface !== null) {
      const key = `${surface}:${remoteKey(request)}`;
      const { success } = await env.PUBLIC_SURFACE_RATE_LIMITER.limit({ key });
      if (!success) {
        return new Response(RATE_LIMITED_JSON, {
          status: 429,
          headers: {
            "content-type": "application/json; charset=utf-8",
            "retry-after": "60",
          },
        });
      }
    }

    let target: URL;
    try {
      target = originUrl(incomingUrl, env.ORIGIN_BASE_URL);
    } catch (error) {
      return new Response((error as Error).message, { status: 500 });
    }

    return fetch(target, {
      method: request.method,
      headers: proxyHeaders(request, incomingUrl.host),
      body: request.method === "GET" || request.method === "HEAD" ? null : request.body,
      redirect: "manual",
    });
  },
} satisfies ExportedHandler<Env>;
