"""Authenticated, fail-closed WhatsApp MCP tools; no credentials in responses."""
import hashlib
import hmac
import json
import os
import re
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import HTTPException
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.responses import JSONResponse


def env(name):
    return os.getenv(name, '').strip()


def phone(value):
    value = value.removeprefix('+')
    if not re.fullmatch(r'[1-9][0-9]{7,14}', value):
        raise ValueError('Use an international number with country code.')
    return value


def require_recipient(number):
    number = phone(number)
    allowed = {x.strip().removeprefix('+') for x in env('WHATSAPP_ALLOWED_RECIPIENTS').split(',') if x.strip()}
    test = env('WHATSAPP_TEST_RECIPIENT').removeprefix('+')
    if not test:
        raise HTTPException(503, 'WHATSAPP_TEST_RECIPIENT is not configured.')
    if not broadcasts_enabled() and number != test:
        raise HTTPException(403, 'Only the test recipient is enabled.')
    if number != test and number not in allowed:
        raise HTTPException(403, 'Recipient is not on the server allowlist.')
    return number


def broadcasts_enabled():
    return (env('WHATSAPP_BROADCAST_ENABLED').lower() == 'true'
            and env('WHATSAPP_TEST_DELIVERY_CONFIRMED').lower() == 'true')


def require_broadcast():
    if not broadcasts_enabled():
        raise HTTPException(403, 'Broadcasts disabled until test delivery is confirmed and broadcasts are enabled in Render.')


def graph(method, resource, *, params=None, payload=None):
    token = env('WHATSAPP_ACCESS_TOKEN')
    version = env('WHATSAPP_GRAPH_VERSION') or 'v26.0'
    if not token or not re.fullmatch(r'v[0-9]+\.[0-9]+', version):
        raise ValueError('WhatsApp token or Graph version is not configured correctly.')
    # Resource paths are constructed by this module, never supplied by the caller.
    try:
        with httpx.Client(timeout=30, follow_redirects=False) as client:
            response = client.request(method, f'https://graph.facebook.com/{version}/{resource}',
                headers={'Authorization': f'Bearer {token}'}, params=params, json=payload)
        if response.is_error:
            raise ValueError(f'Meta request failed (HTTP {response.status_code}).')
        return response.json()
    except (httpx.HTTPError, json.JSONDecodeError):
        raise ValueError('Meta request failed; delivery may be unknown. Do not retry with a new request ID.') from None


def numeric_id(name):
    value = env(name)
    if not re.fullmatch(r'[0-9]+', value):
        raise ValueError(f'{name} is missing or invalid.')
    return value


def template_page(after=None):
    params = {'limit': 50, 'fields': 'name,status,language,components'}
    if after:
        params['after'] = after
    data = graph('GET', f"{numeric_id('WHATSAPP_WABA_ID')}/message_templates", params=params)
    # Do not return Meta paging URLs: these can contain access tokens.
    return {'templates': [{k: t.get(k) for k in ('name', 'status', 'language', 'components')}
                          for t in data.get('data', [])],
            'after': data.get('paging', {}).get('cursors', {}).get('after') if data.get('paging', {}).get('next') else None}


def init_tables():
    from .database import get_conn
    with get_conn() as conn:
        conn.execute('''CREATE TABLE IF NOT EXISTS whatsapp_mcp_requests (
            request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
            state TEXT NOT NULL, result JSONB, created_at TIMESTAMPTZ NOT NULL DEFAULT now())''')


def once(request_id, payload, action):
    """Reserve before sending. Unknown outcomes remain reserved across restarts."""
    from .database import get_conn
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    with get_conn() as conn:
        inserted = conn.execute('''INSERT INTO whatsapp_mcp_requests (request_id, fingerprint, state)
            VALUES (%s, %s, 'pending') ON CONFLICT DO NOTHING RETURNING request_id''',
            (request_id, fingerprint)).fetchone()
        if not inserted:
            row = conn.execute('SELECT fingerprint, state, result FROM whatsapp_mcp_requests WHERE request_id=%s',
                               (request_id,)).fetchone()
            if row['fingerprint'] != fingerprint:
                raise ValueError('Request ID already used with different arguments.')
            return row['result'] or {'state': row['state'], 'retry_allowed': False}
    try:
        result = action()
    except Exception:
        result = {'state': 'failed_or_unknown', 'retry_allowed': False}
    with get_conn() as conn:
        conn.execute('UPDATE whatsapp_mcp_requests SET state=%s, result=%s::jsonb WHERE request_id=%s',
                     (result.get('state', 'completed'), json.dumps(result), request_id))
    return result


RequestID = Annotated[str, Field(min_length=8, max_length=100, pattern=r'^[a-zA-Z0-9_-]+$')]
ShortText = Annotated[str, Field(min_length=1, max_length=4096)]
mcp = FastMCP('Zone A WhatsApp', stateless_http=True, json_response=True, streamable_http_path='/',
    transport_security=TransportSecuritySettings(
        allowed_hosts=['market-visit-tracker-api.onrender.com', 'localhost', 'localhost:*', '127.0.0.1:*'],
        allowed_origins=[x.strip() for x in env('WHATSAPP_MCP_ALLOWED_ORIGINS').split(',') if x.strip()]))
read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
write = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)


@mcp.tool(annotations=read)
def get_whatsapp_status() -> dict:
    """Check Meta connectivity and template readiness without revealing credentials."""
    names = ['WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_WABA_ID']
    result = {'configured': {name: bool(env(name)) for name in names},
              'connected': False, 'broadcasts_enabled': broadcasts_enabled()}
    if not all(result['configured'].values()):
        result['error'] = 'MISSING_CONFIGURATION'
        return result
    try:
        graph('GET', numeric_id('WHATSAPP_PHONE_NUMBER_ID'), params={'fields': 'id'})
        phone_id = numeric_id('WHATSAPP_PHONE_NUMBER_ID')
        found = False
        after = None
        for _ in range(10):
            params = {'fields': 'id', 'limit': 100}
            if after:
                params['after'] = after
            numbers = graph('GET', f"{numeric_id('WHATSAPP_WABA_ID')}/phone_numbers", params=params)
            if any(str(n.get('id')) == phone_id for n in numbers.get('data', [])):
                found = True
                break
            paging = numbers.get('paging', {})
            after = paging.get('cursors', {}).get('after') if paging.get('next') else None
            if not after:
                break
        if not found:
            raise ValueError('Configured phone number was not found in the configured WABA.')
        page = template_page()
        result.update(connected=True, template_count_on_page=len(page['templates']))
    except ValueError as exc:
        result['error'] = str(exc)
    return result


@mcp.tool(annotations=read)
def list_templates(after: Annotated[str, Field(max_length=2048)] | None = None) -> dict:
    """List template names, languages, approval status and components; use after for pagination."""
    return template_page(after)


def send_payload(payload):
    data = graph('POST', f"{numeric_id('WHATSAPP_PHONE_NUMBER_ID')}/messages", payload=payload)
    ids = [m['id'] for m in data.get('messages', []) if m.get('id')]
    return {'state': 'accepted' if ids else 'unknown', 'message_ids': ids, 'delivered': False}


@mcp.tool(annotations=write)
def send_template_message(to: str, template_name: Annotated[str, Field(pattern=r'^[a-z0-9_]{1,512}$')],
                          language: Annotated[str, Field(pattern=r'^[a-zA-Z_]{2,20}$')],
                          body_parameters: list[ShortText], request_id: RequestID,
                          confirm_send: bool = False) -> dict:
    """Send one approved text-body template. Preview by default; reuse request_id after any timeout."""
    number = require_recipient(to)
    if len(body_parameters) > 20:
        raise ValueError('At most 20 body parameters are supported.')
    data = graph('GET', f"{numeric_id('WHATSAPP_WABA_ID')}/message_templates",
                 params={'name': template_name, 'limit': 100})
    match = next((t for t in data.get('data', []) if t.get('name') == template_name
                  and t.get('language') == language and t.get('status') == 'APPROVED'), None)
    if not match:
        raise ValueError('No approved template found for this name and language.')
    payload = {'messaging_product': 'whatsapp', 'to': number, 'type': 'template',
               'template': {'name': template_name, 'language': {'code': language}}}
    if body_parameters:
        payload['template']['components'] = [{'type': 'body', 'parameters':
            [{'type': 'text', 'text': p} for p in body_parameters]}]
    if not confirm_send:
        return {'state': 'preview', 'template_name': template_name, 'language': language,
                'recipient_suffix': number[-4:], 'body_parameters': body_parameters}
    return once(request_id, payload, lambda: send_payload(payload))


@mcp.tool(annotations=write)
def send_text_message(to: str, text: ShortText, request_id: RequestID,
                      customer_service_window_confirmed: bool = False, confirm_send: bool = False) -> dict:
    """Send one text only within Meta's customer-service window. Explicit window confirmation required."""
    number = require_recipient(to)
    if not customer_service_window_confirmed:
        raise ValueError('Confirm a current customer-service window, or use an approved template.')
    payload = {'messaging_product': 'whatsapp', 'to': number, 'type': 'text', 'text': {'body': text}}
    if not confirm_send:
        return {'state': 'preview', 'recipient_suffix': number[-4:], 'text': text}
    return once(request_id, payload, lambda: send_payload(payload))


@mcp.tool(annotations=write)
def send_tl_broadcast(request_id: RequestID, confirm_send: bool = False) -> dict:
    """Preview or send the existing TL performance template to server-allowlisted active TLs.

    Broadcasts require confirmed test delivery and explicit Render enablement. Never automatically retry failures.
    """
    from . import main, crud
    recipients = crud.list_active_users_by_role('TL')
    if not confirm_send:
        return {'state': 'preview', 'audience': 'TL', 'recipient_count': len(recipients),
                'broadcasts_enabled': broadcasts_enabled(), 'template_name': main.WHATSAPP_TEMPLATE_NAME}
    require_broadcast()
    # Validate every recipient before starting, avoiding a partially allowlisted broadcast.
    for r in recipients:
        if r.get('whatsapp_number'):
            require_recipient(main._normalize_whatsapp_number(r['whatsapp_number']) or '')
    def action():
        run = main._claim_zone_broadcast('MCP')
        if not run:
            raise ValueError('Unable to reserve broadcast.')
        main._execute_zone_tl_broadcast(int(run['id']))
        result = crud.get_whatsapp_broadcast_run(int(run['id'])) or {}
        return {'state': str(result.get('status') or 'unknown'), 'run_id': int(run['id'])}
    return once(request_id, {'operation': 'tl_broadcast'}, action)


class BearerAuth:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            key = env('WHATSAPP_MCP_API_KEY')
            headers = dict(scope.get('headers', []))
            supplied = headers.get(b'authorization', b'')
            if not key or not hmac.compare_digest(supplied, ('Bearer ' + key).encode()):
                return await JSONResponse({'error': 'Unauthorized'}, status_code=401)(scope, receive, send)
            # Remote clients need no Origin; browser origins must be explicitly allowlisted.
            origin = headers.get(b'origin', b'').decode()
            if origin and origin not in env('WHATSAPP_MCP_ALLOWED_ORIGINS').split(','):
                return await JSONResponse({'error': 'Origin denied'}, status_code=403)(scope, receive, send)
        await self.app(scope, receive, send)


mcp_app = BearerAuth(mcp.streamable_http_app())
