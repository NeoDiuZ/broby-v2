# Restricted WhatsApp trial

The Twilio One Console trial was activated after explicit user approval of the
WhatsApp/Meta terms. It is a test sender, not a production clinic sender. The
trial only supports Twilio-supplied ContentSid templates and verified recipients;
custom clinic messages require an upgraded account and a registered sender.
Provider source: https://www.twilio.com/docs/usage/trials/try-out-whatsapp .

Broby exposes a separate WhatsApp connection test in Settings > Integrations.
An administrator reviews the configured recipient and exact supplied template,
then requests a send explicitly. The server rejects mismatched previews, limits
requests to ten per UTC day, rechecks the operator before dispatch, and refuses
opted-out recipients. Existing patient drafts are never dispatched by this trial.

## Backend configuration

Set only on the Broby New Backend:

- `BROBY_TWILIO_MODE=trial`
- `BROBY_TWILIO_SEND_ENABLED=true` only after recipient linking and review
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`
- `BROBY_TWILIO_CLINIC_ID=clinic-east`
- `BROBY_TWILIO_FROM` and `BROBY_TWILIO_RECIPIENT` in `whatsapp:+E164` form
- `BROBY_TWILIO_CONTENT_SID` and `BROBY_TWILIO_TEMPLATE_TEXT`, copied from the
  exact provider template being tested; do not invent either value
- `BROBY_PUBLIC_URL`, the existing public HTTPS app origin

No token is returned to the browser. Missing configuration leaves the adapter
unavailable; sending defaults to disabled. V1 credentials/routing are untouched.
The Twilio page supplies the join phrase and test sender for recipient linking.
Recheck that UI instead of assuming a trial sender or join phrase is permanent.

## Delivery and recovery

A persistent claim precedes the external create request. Twilio message creation
is not assumed idempotent: a timeout or crash becomes uncertain and never causes
a blind resend. The unique signed callback route can recover the provider SID
when the create acknowledgement was lost. Known SIDs can be reconciled safely.

Callback `/api/integrations/twilio/status/{attempt_id}` is set on each send.
Twilio SDK signature validation covers the exact configured public URL and all
form fields. The account, sender, recipient and message ID must match; callbacks
are deduplicated and limited to 1 MB. Canonical Twilio retrieval, rather than an
unverified callback/HTTP success, updates accepted/sent/delivered/read states.
Delayed updates cannot regress proven delivery or read. Polling has bounded
backoff, ten consecutive failure attempts and a seven-day automatic window;
manual checks can reconcile older known messages. Uncertain requests with no
provider SID require a receipt or operator investigation, never a resend button.

Optional inbound URL: `/api/integrations/twilio/inbound`. Only the configured test
recipient is accepted. Signed incoming messages are deduplicated into a separate
trial inbox, with no guessed patient assignment or AI reply. Opt-out blocks
queued sends. Media is not imported. This is not an after-hours or emergency
monitoring service.

## Verification and outstanding acceptance

Twelve regression scenarios exercise scope/roles, disabled sending, preview
mismatch, daily caps, idempotent request replay, real SDK signature validation,
future form fields, duplicate/out-of-order callbacks, lost acknowledgements,
expired claims, revoked permissions, changed recipient configuration, provider
identity mismatch, opt-out, inbound replay, terminal read state and bounded
failed reconciliation. The complete backend and production frontend checks run
in CI. Provider calls in these regression tests are mocked.

Actual provider acceptance, own-number delivery/read, inbound callback and
provider reconciliation must still be demonstrated after the recipient is
linked and credentials/template are connected. Deployment of this code does
not prove WhatsApp delivery. The trial expires and cannot stand in for a
registered production sender, consent/template approval or a staffed escalation
policy.

## Read-only provider recheck — 25 September 2026

Using only the existing V2 trial credential, a read-only Content API request
returned HTTP 401, Twilio code 20003: “This feature is not available on a Trial
account. Please upgrade your account to gain access.” It returned no usable
template ID. The native WhatsApp app does not show Twilio account provisioning;
it was inspected without changing or sending a message. No provider account,
sender, webhook, backend configuration, customer data or original Broby service
was changed. Real Broby-originated template delivery remains unverified.
