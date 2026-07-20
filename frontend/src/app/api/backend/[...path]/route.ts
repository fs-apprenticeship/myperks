import { type NextRequest, NextResponse } from "next/server";

// Edge runtime eliminates the ~6 s Node.js cold-start on this proxy route.
export const runtime = "edge";

const BACKEND_URL = (
  process.env.BACKEND_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://localhost:8000"
).replace(/\/+$/, "");

async function handler(
  req: NextRequest,
  context: { params: Promise<{ path: string[] }> },
): Promise<NextResponse> {
  const { path } = await context.params;

  // Strip Next.js routing params: nxtP* prefix and the catch-all "path" key
  const searchParams = new URL(req.url).searchParams;
  for (const key of [...searchParams.keys()]) {
    if (key.startsWith("nxtP") || key === "path") searchParams.delete(key);
  }
  const search = searchParams.size > 0 ? `?${searchParams.toString()}` : "";
  const url = `${BACKEND_URL}/${path.join("/")}${search}`;

  const headers = new Headers(req.headers);
  // Remove hop-by-hop headers and let fetch recalculate content-length
  headers.delete("host");
  headers.delete("connection");
  headers.delete("transfer-encoding");
  headers.delete("content-length");

  let body: ArrayBuffer | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    const buf = await req.arrayBuffer();
    if (buf.byteLength > 0) body = buf;
  }

  try {
    const upstream = await fetch(url, {
      body,
      headers,
      method: req.method,
    });

    // Strip hop-by-hop headers from the upstream response so the runtime
    // can manage framing for the (possibly streamed) body itself.
    const responseHeaders = new Headers(upstream.headers);
    responseHeaders.delete("connection");
    responseHeaders.delete("keep-alive");
    responseHeaders.delete("transfer-encoding");
    responseHeaders.delete("content-length");
    responseHeaders.delete("content-encoding");

    return new NextResponse(upstream.body, {
      headers: responseHeaders,
      status: upstream.status,
      statusText: upstream.statusText,
    });
  } catch (err) {
    return NextResponse.json(
      { detail: `Proxy error reaching backend: ${String(err)}` },
      { status: 502 },
    );
  }
}

export const GET = handler;
export const POST = handler;
export const PUT = handler;
export const PATCH = handler;
export const DELETE = handler;
