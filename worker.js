// Serves site/ under https://theaipipe.com/demos/livekit-morning-brief/ (static files only).
// Byte ranges are answered here so the film plays in Safari on iPhone, which needs 206 responses.
const BASE = '/demos/livekit-morning-brief';
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === BASE) return Response.redirect(`${url.origin}${BASE}/`, 308);
    if (!url.pathname.startsWith(BASE + '/')) return new Response('Not found', { status: 404 });
    const path = url.pathname.slice(BASE.length) || '/';
    const res = await env.ASSETS.fetch(new Request(new URL(path, url.origin), { method: request.method, headers: { Accept: request.headers.get('Accept') || '*/*' } }));
    const range = request.headers.get('Range');
    let out;
    const m = range && res.status === 200 ? /^bytes=(\d*)-(\d*)$/.exec(range.trim()) : null;
    if (m && (m[1] || m[2])) {
      const buf = await res.arrayBuffer();
      const size = buf.byteLength;
      let start, end;
      if (m[1]) { start = +m[1]; end = m[2] ? Math.min(+m[2], size - 1) : size - 1; }
      else { start = Math.max(0, size - +m[2]); end = size - 1; }
      if (start > end || start >= size) {
        out = new Response(null, { status: 416, headers: { 'Content-Range': `bytes */${size}` } });
      } else {
        const h = new Headers(res.headers);
        h.set('Content-Range', `bytes ${start}-${end}/${size}`);
        h.set('Content-Length', String(end - start + 1));
        out = new Response(buf.slice(start, end + 1), { status: 206, headers: h });
      }
    } else {
      out = new Response(res.body, res);
    }
    const loc = out.headers.get('Location');
    if (loc && loc.startsWith('/')) out.headers.set('Location', BASE + loc);
    out.headers.set('Accept-Ranges', 'bytes');
    out.headers.set('X-Robots-Tag', 'noindex, nofollow');
    return out;
  },
};
