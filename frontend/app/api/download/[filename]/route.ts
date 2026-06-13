/**
 * Same-origin proxy for .pptx downloads.
 *
 * Why this exists:
 *   The browser's `download` attribute on <a> tags only works for same-origin
 *   URLs. Our FastAPI backend runs on a different port (8000) so the browser
 *   ignores `download` and opens a blank tab instead of saving the file.
 *
 * How it works:
 *   Browser  →  GET /api/download/deck.pptx  (same origin: port 3000)
 *   Next.js  →  GET http://localhost:8000/api/download/deck.pptx  (server-to-server, no CORS)
 *   FastAPI  →  streams file bytes back to Next.js
 *   Next.js  →  streams those bytes straight to the browser
 *
 *   Server-to-server calls are not subject to CORS — CORS is a browser-only rule.
 *   The browser sees the response coming from port 3000 (same origin) and the
 *   `download` attribute saves the file correctly.
 */

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ filename: string }> }
) {
  const { filename } = await params;
  const upstream = `${BACKEND}/api/download/${encodeURIComponent(filename)}`;

  let upstreamRes: Response;
  try {
    upstreamRes = await fetch(upstream, { cache: "no-store" });
  } catch {
    return new Response("Backend unreachable", { status: 502 });
  }

  if (!upstreamRes.ok) {
    return new Response(await upstreamRes.text(), {
      status: upstreamRes.status,
    });
  }

  // Stream the bytes straight through — no buffering in memory.
  // Content-Disposition tells the browser to save the file with the correct name.
  const headers = new Headers({
    "Content-Type":
      "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "Content-Disposition": `attachment; filename="${filename}"`,
  });

  // Forward Content-Length if the backend sent it (enables a progress bar in browser)
  const contentLength = upstreamRes.headers.get("content-length");
  if (contentLength) headers.set("Content-Length", contentLength);

  return new Response(upstreamRes.body, { status: 200, headers });
}
