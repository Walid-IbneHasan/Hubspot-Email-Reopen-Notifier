/**
 * Repeat Open Alert - HubSpot custom code action (Node.js 20)
 *
 * The workflow enrolls a contact every time they open an email (event "Opened email",
 * re-enrollment on). This action counts real opens per marketing email for the enrolled
 * contact. The first time an email reaches OPEN_THRESHOLD opens, it flags the contact so the
 * next workflow step emails Joe Davis and Riley Simpson. Each email alerts at most once per
 * contact. Opens that HubSpot filtered as bot / privacy-proxy opens are ignored.
 *
 * Required secret on this action: HUBSPOT_TOKEN
 *   (private app token with scopes: content, crm.objects.contacts.read/write)
 *
 * Contact properties used (group "Repeat Open Alerts"):
 *   repeat_open_alert_pending   true while the notification step runs, reset to false after
 *   repeat_open_alert_email     name | subject of the email that triggered the latest alert
 *   repeat_open_alert_count     open count at the time of that alert
 *   repeat_open_alert_total     total alerts ever sent for this contact
 *   repeat_open_alert_last_date when the latest alert fired
 *   repeat_open_alert_state     internal JSON: { "<campaignId>": "a" (alerted) | "s" (skipped) }
 */
const axios = require('axios');

const CONFIG = {
  // Alert only for marketing emails whose internal NAME or SUBJECT contains one of these
  // words (case-insensitive). Use [] to alert for every marketing email.
  NAME_KEYWORDS: [],
  // Ignore opens that happened before this date (YYYY-MM-DD). '' = no limit.
  SENT_AFTER: '2026-10-14',
  // Number of real opens of the same email that triggers the alert.
  OPEN_THRESHOLD: 2,
  // Skip opens HubSpot flagged as filtered (bots, Apple Mail Privacy proxy, scanners).
  IGNORE_FILTERED_OPENS: true,
};

const API = 'https://api.hubapi.com';

exports.main = async (event, callback) => {
  const token = process.env.HUBSPOT_TOKEN;
  if (!token) throw new Error('Secret HUBSPOT_TOKEN is not set on this custom code action');
  const http = axios.create({ baseURL: API, headers: { Authorization: `Bearer ${token}` }, timeout: 8000 });

  const contactId = event.object.objectId;
  const contact = await getJson(http, `/crm/v3/objects/contacts/${contactId}`, {
    params: { properties: 'email,repeat_open_alert_state,repeat_open_alert_total' },
  });
  const email = contact.properties.email;
  if (!email) return callback({ outputFields: { notify: 'no', reason: 'contact has no email' } });

  const state = parseState(contact.properties.repeat_open_alert_state);
  const totalAlerts = Number(contact.properties.repeat_open_alert_total || 0);

  // 1. Every open event for this recipient since SENT_AFTER.
  const opens = await fetchOpens(http, email);

  // 2. Real opens per email campaign.
  const counts = {};
  for (const ev of opens) {
    if (CONFIG.IGNORE_FILTERED_OPENS && ev.filteredEvent) continue;
    const id = String(ev.emailCampaignId);
    counts[id] = (counts[id] || 0) + 1;
  }

  // 3. Campaigns at/over the threshold that were never alerted or skipped before.
  const candidates = Object.keys(counts).filter((id) => counts[id] >= CONFIG.OPEN_THRESHOLD && !state[id]);
  let alert = null;
  for (const id of candidates) {
    const campaign = await getJson(http, `/email/public/v1/campaigns/${id}`).catch(() => null);
    const name = campaign && campaign.name ? campaign.name : `Email campaign ${id}`;
    const subject = campaign && campaign.subject ? campaign.subject : '';
    if (!matchesKeywords(name, subject)) { state[id] = 's'; continue; }
    state[id] = 'a';
    alert = { id, name, subject, count: counts[id] };
    break; // one alert per run; another qualifying email is picked up on the next open
  }

  if (!alert) {
    if (candidates.length) await patchContact(http, contactId, { repeat_open_alert_state: JSON.stringify(state) });
    return callback({ outputFields: { notify: 'no', reason: candidates.length ? 'no matching email' : 'below threshold' } });
  }

  await patchContact(http, contactId, {
    repeat_open_alert_pending: 'true',
    repeat_open_alert_email: alert.subject ? `${alert.name} | ${alert.subject}` : alert.name,
    repeat_open_alert_count: String(alert.count),
    repeat_open_alert_total: String(totalAlerts + 1),
    repeat_open_alert_last_date: String(Date.now()),
    repeat_open_alert_state: JSON.stringify(state),
  });

  callback({ outputFields: { notify: 'yes', email_name: alert.name, open_count: String(alert.count) } });
};

function matchesKeywords(name, subject) {
  if (!CONFIG.NAME_KEYWORDS.length) return true;
  const hay = `${name} ${subject}`.toLowerCase();
  return CONFIG.NAME_KEYWORDS.some((k) => hay.includes(k.toLowerCase()));
}

function parseState(raw) {
  try {
    const s = JSON.parse(raw || '{}');
    return s && typeof s === 'object' && !Array.isArray(s) ? s : {};
  } catch (e) {
    return {};
  }
}

async function fetchOpens(http, email) {
  const params = { recipient: email, eventType: 'OPEN', limit: 300 };
  if (CONFIG.SENT_AFTER) params.startTimestamp = Date.parse(`${CONFIG.SENT_AFTER}T00:00:00Z`);
  const events = [];
  let offset;
  for (let page = 0; page < 5; page++) {
    const data = await getJson(http, '/email/public/v1/events', { params: offset ? { ...params, offset } : params });
    events.push(...(data.events || []));
    if (!data.hasMore || !data.offset) break;
    offset = data.offset;
  }
  return events;
}

async function patchContact(http, id, properties) {
  await withRetry(() => http.patch(`/crm/v3/objects/contacts/${id}`, { properties }));
}

async function getJson(http, url, config) {
  const res = await withRetry(() => http.get(url, config));
  return res.data;
}

// Retry on rate limits (429) and server errors (5xx) with a short backoff.
async function withRetry(fn, attempts = 3) {
  let lastErr;
  for (let i = 0; i < attempts; i++) {
    try {
      return await fn();
    } catch (err) {
      lastErr = err;
      const status = err.response && err.response.status;
      if (status !== 429 && !(status >= 500)) throw err;
      await new Promise((r) => setTimeout(r, 1000 * (i + 1)));
    }
  }
  throw lastErr;
}
