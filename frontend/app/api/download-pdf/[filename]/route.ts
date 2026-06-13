/**
 * Same-origin proxy for PDF downloads (PPTX → PDF via LibreOffice).
 * Identical pattern to /api/download/[filename] — see that file for the
 * full explanation of why this proxy is needed.
 */

const BACKEND = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ filename: string }> }
) {
  const { filename } = await params;
  const upstream = `${BACKEND}/api/download-pdf/${encodeURIComponent(filename)}`;

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

  const pdfFilename = filename.replace(/\.pptx$/i, ".pdf");

  const headers = new Headers({
    "Content-Type": "application/pdf",
    "Content-Disposition": `attachment; filename="${pdfFilename}"`,
  });

  const contentLength = upstreamRes.headers.get("content-length");
  if (contentLength) headers.set("Content-Length", contentLength);

  return new Response(upstreamRes.body, { status: 200, headers });
}
