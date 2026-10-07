# WhatsApp MCP deployment

The WhatsApp Cloud API and TL performance/broadcast code lives in
`market-visit-tracker-api`. `vwork-live-api` supplies sales/inventory data.
Configure WhatsApp on the tracker service, where it is consumed.

## Render settings

Keep all credentials in Render, never in source or client-visible responses.

Required on `market-visit-tracker-api`:

- `WHATSAPP_ACCESS_TOKEN`: existing authorized Meta token.
- `WHATSAPP_PHONE_NUMBER_ID`: Meta phone-number ID.
- `WHATSAPP_WABA_ID`: WhatsApp Business Account ID.
- `WHATSAPP_TEST_RECIPIENT`: one explicitly chosen international test number.
- `WHATSAPP_MCP_API_KEY`: a separate, strong secret for the MCP client.

Optional existing settings:

- `WHATSAPP_GRAPH_VERSION` (default `v26.0`).
- `WHATSAPP_TEMPLATE_NAME` (default `zone_a_incentive_update_v2`).
- `WHATSAPP_TEMPLATE_LANGUAGE` (default `en`).

Leave `WHATSAPP_BROADCAST_ENABLED=false` and
`WHATSAPP_TEST_DELIVERY_CONFIRMED=false` until a real recipient confirms delivery.
Meta accepting a message ID does not prove delivery.
After verification and explicit broadcast authorization, set both to `true` and
set `WHATSAPP_ALLOWED_RECIPIENTS` to the intended comma-separated international
recipient numbers. These gates apply to the existing scheduled and manual sends
as well as MCP. The existing database schedule remains subject to the gate.

## Connect and test

Streamable HTTP endpoint: `https://market-visit-tracker-api.onrender.com/mcp/`.
Authenticate with `Authorization: Bearer <WHATSAPP_MCP_API_KEY>`.
The endpoint returns 401 when its key is missing or wrong.
For a browser client, explicitly allow its Origin using
`WHATSAPP_MCP_ALLOWED_ORIGINS`; server clients need no Origin.

The five tools are `get_whatsapp_status`, `list_templates`,
`send_template_message`, `send_text_message`, and `send_tl_broadcast`.

1. Check status: Meta must authenticate, the phone-number ID must belong to the
   configured WABA, and template listing must succeed.
2. List templates and select an approved name/language. This minimal sender
   supports text body parameters; media/header/button templates need more work.
3. Preview a template send to the test recipient (`confirm_send=false`).
4. Send that same approved template to the test recipient with
   `confirm_send=true` and a unique `request_id`.
5. Confirm actual receipt. Keep broadcasts disabled if delivery is unverified.

Text sends require explicit confirmation that the recipient is within the
customer-service window; otherwise use an approved template. Meta still enforces
its own eligibility rules.

Write tools reserve a request ID in PostgreSQL before sending. Repeat the same
ID after a timeout to avoid resending. Pending or failed/unknown outcomes are
never automatically retried. Do not submit a new ID merely to retry an uncertain
send. Request records contain a payload hash and minimal result, not tokens or
message text. For a broadcast, inspect the existing broadcast run for detailed
outcomes; it is never automatically replayed by MCP.

## Validation and rollback

Run `PYTHONPATH=. python -m pytest tests -q` with development pytest installed.
Also check the existing app lifespan, health route and authenticated MCP handshake
after deployment. Startup creates one additive request-deduplication table.
Rollback code using Render's previous deployment; preserve that table to retain
duplicate-send protection. Keep broadcasts disabled during rollback and do not
move credentials to a build without the safety gate.
