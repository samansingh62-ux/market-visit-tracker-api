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


# ---------------- Zone A data tools (read only, whole zone) ----------------
ZONE = {'name': 'Manager', 'role': 'MANAGER', 'tl': None, 'ss': None, 'rds': None}
data_read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)
Name = Annotated[str, Field(min_length=2, max_length=80)]


def _main():
    from . import main   # imported late: main imports this module
    return main


async def _run(fn, *args, **kwargs):
    import anyio
    try:
        return await anyio.to_thread.run_sync(lambda: fn(*args, **kwargs))
    except HTTPException as exc:
        return {'error': exc.detail, 'status': exc.status_code}


@mcp.tool(annotations=data_read)
async def get_review(role: Annotated[str, Field(pattern=r'^(TL|SS|KAM|RDS)$')], name: Name) -> dict:
    """Review of one TL, SS, KAM or RDS: month so far, today's sale, flags, TLs under them,
    counters (up to 40, biggest first) and a 5-point action plan."""
    m = _main()
    d = await _run(m.person_review, role=role, name=name, user=ZONE)
    if 'error' in d:
        return d
    d['counters_total'] = len(d['counters'])
    d['counters'] = d['counters'][:40]
    return d


@mcp.tool(annotations=data_read)
async def get_tl_ftd(kam: Name | None = None) -> dict:
    """Today's sale (FTD) by TL against the units each needs per day to reach the month target."""
    m = _main()
    perf = await _run(m.performance_dashboard, ZONE)
    left = max(int((perf.get('period') or {}).get('days_remaining') or 1), 1)
    rows = []
    for t in (perf.get('hierarchy') or {}).get('tl') or []:
        if not t.get('name') or t['name'] in ('Unassigned',) or (kam and t.get('kam') != kam):
            continue
        before = int(t.get('sales') or 0) - int(t.get('ftd_sales') or 0)
        need = -(-max(int(t.get('target') or 0) - before, 0) // left) if t.get('target') else None
        rows.append({'tl': t['name'], 'kam': t.get('kam'), 'ss': t.get('ss'), 'ftd_units': t.get('ftd_sales'),
                     'ftd_value': round(t.get('ftd_sales_value') or 0), 'need_today': need,
                     'pct_of_need': round(t['ftd_sales'] * 100 / need, 1) if need else None,
                     'counters_sold_today': t.get('ftd_counters'), 'counters': t.get('retailers'),
                     'mtd': t.get('sales'), 'target': t.get('target')})
    rows.sort(key=lambda r: -(r['ftd_units'] or 0))
    return {'date': (perf.get('period') or {}).get('end'), 'days_left_incl_today': left,
            'total_ftd': sum(r['ftd_units'] or 0 for r in rows), 'total_need': sum(r['need_today'] or 0 for r in rows), 'tls': rows}


@mcp.tool(annotations=data_read)
async def get_scheme_payout(retailer: Annotated[str, Field(min_length=3, max_length=120)]) -> dict:
    """November scheme payout for one retailer (code or part of the name): booster, focus, clearance,
    additional and back support, with stock on hand per series and the payout if it is all sold."""
    m = _main()
    perf = await _run(m.performance_dashboard, ZONE)
    q = retailer.strip().lower()
    hits = [r for r in perf.get('retailers') or [] if r.get('code', '').lower() == q] or \
           [r for r in perf.get('retailers') or [] if q in str(r.get('name') or '').lower()]
    if not hits:
        return {'error': 'No retailer matches that code or name.'}
    if len({(r.get('schemes') or {}).get('shared', {}).get('retailer_code') or r['code'] for r in hits}) > 1:
        return {'matches': [{'code': r['code'], 'name': r['name'], 'tl': r.get('tl')} for r in hits[:15]],
                'note': 'Several retailers match; ask again with the code.'}
    r = hits[0]
    return {'code': r['code'], 'name': r['name'], 'tl': r.get('tl'), 'club': r.get('club'), 'schemes': r.get('schemes')}


@mcp.tool(annotations=data_read)
async def get_focus_models(variant: Annotated[str, Field(max_length=80)] | None = None) -> dict:
    """Focus-model target vs achievement for Zone A; with a variant, the counters not moving it,
    counters with a target but no stock, and VBAs at zero."""
    m = _main()
    d = await _run(m.focus_models_view, variant, ZONE)
    det = d.get('detail') if isinstance(d, dict) else None
    if det:
        for k in ('not_moving', 'no_stock_with_target', 'vbas_zero'):
            det[k + '_total'] = len(det[k])
            det[k] = det[k][:40]
    return d


@mcp.tool(annotations=data_read)
async def get_punched_sales(kam: Name | None = None) -> dict:
    """VBA / RVBA / FVBA punched sales against target and what TLs and SSs punched themselves,
    from the latest uploaded tertiary dashboard."""
    m = _main()
    d = await _run(m.punched_sales, None, ZONE)
    if 'error' in d or not d.get('as_of'):
        return d
    vb = [v for v in d['vbas'] if not kam or v.get('kam') == kam]
    own = [o for o in d['own'] if not kam or o.get('kam') == kam]
    return {'as_of': d['as_of'], 'totals': d['totals'], 'vbas_total': len(vb), 'vbas_zero_sale': sum(1 for v in vb if not v['units']),
            'lowest_vbas': vb[:30], 'tl_ss_own': own[:40]}


@mcp.tool(annotations=data_read)
async def get_visit_report(date_from: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')] | None = None,
                           date_to: Annotated[str, Field(pattern=r'^\d{4}-\d{2}-\d{2}$')] | None = None,
                           kam: Name | None = None) -> dict:
    """Outlets visited and remarks by TL, SS and KAM, and TL-wise outlets per day (default: this month)."""
    m = _main()
    d = await _run(m.visit_report_view, date_from, date_to, ZONE)
    if 'error' in d:
        return d
    people = [p for p in d['people'] if not kam or p['kam'] == kam or p['name'] == kam]
    for p in people:
        p['recent_visits'] = p.pop('visits')[-10:]
    return {'date_from': d['date_from'], 'date_to': d['date_to'], 'people': people,
            'tl_daily': [t for t in d['tl_daily'] if not kam or t['kam'] == kam], 'dates': d['dates']}


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
