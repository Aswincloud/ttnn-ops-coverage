// Worker entry for the TTNN Ops Coverage dashboard.
//
// The site is otherwise a static-assets deployment: every request is served
// from ./public via the ASSETS binding. The ONE dynamic route is
//   POST /api/feedback
// which collects a suggestion / data-mismatch / bug report from the dashboard
// and emails it to the maintainer through Resend.
//
// Secrets / vars (set in the Cloudflare dashboard or via `wrangler secret`):
//   RESEND_API_KEY  (secret, required)  — Resend API key
//   FEEDBACK_TO     (var, optional)     — recipient; defaults to aswin@aswincloud.com
//   FROM_EMAIL      (var, optional)     — sender; defaults to Resend's shared domain

const RESEND_URL = 'https://api.resend.com/emails';
const DEFAULT_TO = 'aswin@aswincloud.com';
const DEFAULT_FROM = 'TTNN Ops Feedback <ttnn-ops@aswincloud.com>';

const TYPES = {
  suggestion: 'Suggestion / improvement',
  mismatch: 'Result mismatch (mislabeled pass/fail)',
  bug: 'Bug / site issue',
  other: 'Other',
};

const MAX = { message: 4000, op: 80, email: 200, type: 20, page: 300 };

const json = (data, status = 200) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { 'content-type': 'application/json; charset=utf-8' },
  });

const esc = (s) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

// crude email sanity check — we never trust it for auth, only for reply-to
const looksEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s);

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);

    if (url.pathname === '/api/feedback') {
      if (request.method === 'POST') return handleFeedback(request, env, ctx);
      return json({ error: 'method not allowed' }, 405);
    }

    // Everything else → static assets.
    return env.ASSETS.fetch(request);
  },
};

async function handleFeedback(request, env, ctx) {
  // ---- per-IP rate limit via the native Rate Limiting binding (shared across
  // isolates/edge — an in-memory counter does NOT work on Workers because
  // requests are spread over many isolates). CF-Connecting-IP is set at the edge
  // and not spoofable. ----
  const ip = request.headers.get('CF-Connecting-IP') || 'unknown';
  if (env.FEEDBACK_LIMITER) {
    const { success } = await env.FEEDBACK_LIMITER.limit({ key: ip });
    if (!success) return json({ error: 'Too many messages — please wait a minute and try again.' }, 429);
  }

  // ---- parse ----
  let data;
  try {
    data = await request.json();
  } catch {
    return json({ error: 'Invalid request body.' }, 400);
  }

  // honeypot: real users never fill the hidden "website" field
  if (data && typeof data.website === 'string' && data.website.trim() !== '') {
    return json({ ok: true }); // silently accept + drop
  }

  const type = String(data?.type || 'other').slice(0, MAX.type);
  const op = String(data?.op || '').trim().slice(0, MAX.op);
  const email = String(data?.email || '').trim().slice(0, MAX.email);
  const page = String(data?.page || '').trim().slice(0, MAX.page);
  const message = String(data?.message || '').trim().slice(0, MAX.message);

  if (message.length < 3) return json({ error: 'Please enter a message (at least 3 characters).' }, 400);
  if (email && !looksEmail(email)) return json({ error: 'That email address looks invalid.' }, 400);

  if (!env.RESEND_API_KEY) {
    // Not yet configured — tell the user honestly rather than pretend success.
    return json({ error: 'Feedback is not configured on the server yet. Please try again later.' }, 503);
  }

  const typeLabel = TYPES[type] || TYPES.other;
  const to = env.FEEDBACK_TO || DEFAULT_TO;
  const from = env.FROM_EMAIL || DEFAULT_FROM;
  const ua = request.headers.get('user-agent') || '';
  const country = request.headers.get('CF-IPCountry') || '';
  const when = new Date().toISOString();

  const subject = `[TTNN Ops] ${typeLabel}${op ? ` · ${op}` : ''}`;
  const html = buildHtml({ typeLabel, op, email, page, message, ip, ua, country, when });
  const text = buildText({ typeLabel, op, email, page, message, when });

  const payload = {
    from,
    to: [to],
    subject,
    html,
    text,
    ...(email ? { reply_to: email } : {}),
  };

  const res = await fetch(RESEND_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const body = await res.text().catch(() => '');
    console.error(`resend send failed: ${res.status} ${body}`);
    return json({ error: 'Could not send your message right now. Please try again later.' }, 502);
  }

  // ---- acknowledgement to the submitter (best-effort) ----
  // If they left a valid email, send a confirmation back. This is fire-and-
  // forget via waitUntil: the user's success response never waits on it, and a
  // failed ack must NOT fail the feedback (their message already went through).
  if (email) {
    const ack = sendAck(env, { email, from, typeLabel, op, message, when })
      .catch((e) => console.error(`ack send failed: ${e}`));
    if (ctx && ctx.waitUntil) ctx.waitUntil(ack);
  }

  return json({ ok: true });
}

// Confirmation email to the person who submitted feedback. Reply-to points at
// the maintainer so a reply from them reaches a human, not the no-reply sender.
async function sendAck(env, { email, from, typeLabel, op, message, when }) {
  const to = env.FEEDBACK_TO || DEFAULT_TO;
  const payload = {
    from,
    to: [email],
    reply_to: to,
    subject: 'We got your feedback — TTNN Ops Coverage',
    html: buildAckHtml({ typeLabel, op, message, when }),
    text: buildAckText({ typeLabel, op, message, when }),
  };
  const res = await fetch(RESEND_URL, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.RESEND_API_KEY}`,
      'content-type': 'application/json',
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => '');
    throw new Error(`${res.status} ${body}`);
  }
}

function buildAckText({ typeLabel, op, message, when }) {
  return [
    'Thanks — we received your feedback on the TTNN Ops Coverage dashboard.',
    '',
    "It's been sent to the maintainer. We read everything, but can't promise an",
    'individual reply. If a response is needed, we\'ll get back to you at this address.',
    '',
    `Type:    ${typeLabel}`,
    op ? `Op:      ${op}` : null,
    `Sent:    ${when}`,
    '',
    '--- your message ---',
    message,
    '',
    '— TTNN Ops Coverage',
    'https://ttnn-ops-coverage.aswincloud.com/',
  ].filter(Boolean).join('\n');
}

function buildAckHtml({ typeLabel, op, message, when }) {
  const row = (k, v) =>
    v ? `<tr><td style="padding:5px 12px;color:#64748b;white-space:nowrap;vertical-align:top">${esc(k)}</td><td style="padding:5px 12px;color:#0f172a">${esc(v)}</td></tr>` : '';
  return `<!doctype html><html><head><meta charset="utf-8"></head>
  <body style="margin:0;background:#f1f5f9;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a">
    <div style="max-width:560px;margin:0 auto;padding:24px">
      <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
        <div style="background:linear-gradient(135deg,#065f46,#10b981);padding:18px 22px;color:#fff">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85">TTNN Ops Coverage</div>
          <div style="font-size:18px;font-weight:700;margin-top:3px">Thanks — we got your feedback</div>
        </div>
        <div style="padding:18px 22px;font-size:14px;line-height:1.6;color:#334155">
          Your message has been sent to the maintainer. We read everything, though we
          can't promise an individual reply. If a response is needed, we'll reach you
          at this address.
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:13px;border-top:1px solid #e2e8f0">
          ${row('Type', typeLabel)}
          ${row('Op', op)}
          ${row('Sent', when)}
        </table>
        <div style="padding:16px 22px;border-top:1px solid #e2e8f0">
          <div style="font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Your message</div>
          <div style="white-space:pre-wrap;line-height:1.55;font-size:14px;color:#0f172a">${esc(message)}</div>
        </div>
        <div style="padding:12px 22px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:11px">
          <a href="https://ttnn-ops-coverage.aswincloud.com/" style="color:#3b82f6;text-decoration:none">ttnn-ops-coverage.aswincloud.com</a>
        </div>
      </div>
    </div>
  </body></html>`;
}

function buildText({ typeLabel, op, email, page, message, when }) {
  return [
    `Type:    ${typeLabel}`,
    op ? `Op:      ${op}` : null,
    email ? `Reply:   ${email}` : `Reply:   (none provided)`,
    page ? `Page:    ${page}` : null,
    `Time:    ${when}`,
    '',
    '--- message ---',
    message,
  ].filter(Boolean).join('\n');
}

function buildHtml({ typeLabel, op, email, page, message, ip, ua, country, when }) {
  const row = (k, v) =>
    v ? `<tr><td style="padding:6px 12px;color:#64748b;white-space:nowrap;vertical-align:top">${esc(k)}</td><td style="padding:6px 12px;color:#0f172a">${esc(v)}</td></tr>` : '';
  return `<!doctype html><html><head><meta charset="utf-8"></head>
  <body style="margin:0;background:#f1f5f9;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a">
    <div style="max-width:640px;margin:0 auto;padding:24px">
      <div style="background:#fff;border:1px solid #e2e8f0;border-radius:14px;overflow:hidden">
        <div style="background:linear-gradient(135deg,#1e3a8a,#3b82f6);padding:18px 22px;color:#fff">
          <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.85">TTNN Ops Coverage · Feedback</div>
          <div style="font-size:18px;font-weight:700;margin-top:3px">${esc(typeLabel)}</div>
        </div>
        <table style="width:100%;border-collapse:collapse;font-size:14px;border-bottom:1px solid #e2e8f0">
          ${row('Op', op)}
          ${row('From', email || '(anonymous)')}
          ${row('Page', page)}
          ${row('Time', when)}
          ${row('IP', `${ip}${country ? ` (${country})` : ''}`)}
        </table>
        <div style="padding:18px 22px">
          <div style="font-size:12px;color:#64748b;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px">Message</div>
          <div style="white-space:pre-wrap;line-height:1.55;font-size:15px">${esc(message)}</div>
        </div>
        <div style="padding:12px 22px;border-top:1px solid #e2e8f0;color:#94a3b8;font-size:11px;word-break:break-all">
          ${esc(ua)}
        </div>
      </div>
    </div>
  </body></html>`;
}
