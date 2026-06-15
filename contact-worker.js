const BREVO_ENDPOINT = 'https://api.brevo.com/v3/smtp/email';
const TO_EMAIL = 'hello@optiimind.com';
const CC_EMAIL = 'max@optiimind.com';
const FROM_EMAIL = 'hello@optiimind.com';
const FROM_NAME = 'Optiimind Contact';

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store'
    }
  });
}

function clean(value, maxLength) {
  return String(value || '').trim().slice(0, maxLength);
}

function isEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value);
}

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return json({ error: 'Method not allowed' }, 405);
    }

    let body;
    try {
      body = await request.json();
    } catch {
      return json({ error: 'Invalid JSON' }, 400);
    }

    if (clean(body.company, 100)) {
      return json({ ok: true });
    }

    const name = clean(body.name, 120);
    const email = clean(body.email, 180);
    const subject = clean(body.subject, 160);
    const message = clean(body.message, 5000);

    if (!name || !isEmail(email) || !subject || !message) {
      return json({ error: '請填寫完整且有效的聯絡資料。' }, 400);
    }

    if (!env.BREVO_API_KEY) {
      return json({ error: 'Email service is not configured.' }, 500);
    }

    const text = [
      `Name: ${name}`,
      `Email: ${email}`,
      `Subject: ${subject}`,
      '',
      message
    ].join('\n');

    const brevoResponse = await fetch(BREVO_ENDPOINT, {
      method: 'POST',
      headers: {
        'accept': 'application/json',
        'api-key': env.BREVO_API_KEY,
        'content-type': 'application/json'
      },
      body: JSON.stringify({
        sender: { name: FROM_NAME, email: FROM_EMAIL },
        to: [{ email: TO_EMAIL }],
        cc: [{ email: CC_EMAIL }],
        replyTo: { name, email },
        subject: `[Optiimind] ${subject}`,
        textContent: text,
        htmlContent: `
          <p><strong>Name:</strong> ${escapeHtml(name)}</p>
          <p><strong>Email:</strong> ${escapeHtml(email)}</p>
          <p><strong>Subject:</strong> ${escapeHtml(subject)}</p>
          <hr>
          <p>${escapeHtml(message).replace(/\n/g, '<br>')}</p>
        `
      })
    });

    if (!brevoResponse.ok) {
      const detail = await brevoResponse.text();
      console.error('Brevo error', brevoResponse.status, detail);
      return json({ error: 'Email delivery failed.' }, 502);
    }

    return json({ ok: true });
  }
};

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
