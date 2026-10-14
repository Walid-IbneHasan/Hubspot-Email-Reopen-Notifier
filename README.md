# HubSpot Repeat Open Alerts

Notifies Joe Davis and Riley Simpson by internal HubSpot email the first time a contact opens
the same promotional marketing email 2 or more times. One alert per contact per email.

Portal: The Good Game (43646194)
Active build: "Repeat Open Alerts - KSHSAA High School AD List (351) - Slack on 2+ opens"
https://app.hubspot.com/workflows/43646194/platform/flow/1901845776/edit
Only contacts in list 1135 "KSHSAA High School AD List - 8.20.26" pass the first step; the alert goes to Slack.

Previous build (switched OFF, internal email to Joe and Riley, all contacts):
https://app.hubspot.com/workflows/43646194/platform/flow/1901586010/edit

## How it works
1. Trigger: event "Opened email" on any email, re-enrolling the contact on every open.
   First step is a branch: contacts not in list 1135 exit immediately (HubSpot's API does not
   allow a list condition inside an event trigger, so the gate is a branch).
2. Custom code (`repeat-open-alert.js`): counts real opens per marketing email for the contact
   via the Email Events API, ignoring opens HubSpot flagged as bot / privacy-proxy opens.
   When an email reaches the threshold for the first time, it writes the alert details to the
   contact's "Repeat Open Alerts" properties and sets `repeat_open_alert_pending` = true.
3. Branch on `repeat_open_alert_pending` = true.
4. Slack notification (channel/users set on that step), then reset the pending flag.
   `NOTIFY_VIA = "email"` in build-workflow.py switches back to internal email to Joe and Riley.

## Which emails count
Edit `CONFIG` at the top of `repeat-open-alert.js`:
- `NAME_KEYWORDS: []` - currently empty, so every marketing email counts. Add words like `['promo']`
  to restrict alerts to emails whose internal name or subject contains one of them.
- `SENT_AFTER` - ignore opens before this date.
- `OPEN_THRESHOLD: 2` - opens needed to alert.

## Deploying a change (code, recipients, or message)
```
python build-workflow.py 1901845776
```
Reads the token from `.env` (copy `.env.example` to `.env` and fill it in; never commit it). Pushes `repeat-open-alert.js` into the workflow and
resets the notification step (recipients JOE_DAVIS / RILEY_SIMPSON, subject, body) to what this
script defines. Saving a file alone changes nothing in HubSpot; the deploy command does.

## Secret
The custom code action needs a secret named `HUBSPOT_TOKEN` (the private app token).
Add it in the workflow editor: open the custom code action, Secrets, Add secret.
If the private app token is rotated, update the secret too.
