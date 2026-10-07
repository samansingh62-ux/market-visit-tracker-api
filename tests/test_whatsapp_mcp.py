import json
import sys
from contextlib import asynccontextmanager, contextmanager
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient
from app import whatsapp_mcp as wa


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    for key in list(wa.os.environ):
        if key.startswith('WHATSAPP_'):
            monkeypatch.delenv(key)


def test_fail_closed(monkeypatch):
    assert not wa.get_whatsapp_status()['connected']
    with pytest.raises(HTTPException):
        wa.require_recipient('919999999999')
    monkeypatch.setenv('WHATSAPP_TEST_RECIPIENT', '+919999999999')
    assert wa.require_recipient('919999999999') == '919999999999'
    with pytest.raises(HTTPException):
        wa.require_recipient('918888888888')
    monkeypatch.setenv('WHATSAPP_BROADCAST_ENABLED', 'true')
    with pytest.raises(HTTPException):
        wa.require_broadcast()
    monkeypatch.setenv('WHATSAPP_TEST_DELIVERY_CONFIRMED', 'true')
    wa.require_broadcast()
    with pytest.raises(HTTPException):
        wa.require_recipient('918888888888')
    monkeypatch.setenv('WHATSAPP_ALLOWED_RECIPIENTS', '918888888888')
    assert wa.require_recipient('918888888888') == '918888888888'


def test_graph_errors_do_not_leak_token(monkeypatch):
    monkeypatch.setenv('WHATSAPP_ACCESS_TOKEN', 'secret-test-token')
    class Client:
        def __init__(self, **kw):
            assert kw['follow_redirects'] is False
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def request(self, *args, **kw):
            assert kw['headers']['Authorization'] == 'Bearer secret-test-token'
            raise httpx.ConnectError('secret-test-token')
    monkeypatch.setattr(wa.httpx, 'Client', Client)
    with pytest.raises(ValueError) as exc:
        wa.graph('GET', '123')
    assert 'secret-test-token' not in str(exc.value)


def test_template_pagination_drops_token_urls(monkeypatch):
    monkeypatch.setenv('WHATSAPP_WABA_ID', '123')
    monkeypatch.setattr(wa, 'graph', lambda *a, **k: {
        'data': [{'name': 'hello', 'status': 'APPROVED'}],
        'paging': {'next': 'https://graph.facebook.com/?access_token=secret',
                   'cursors': {'after': 'cursor'}}})
    assert wa.template_page()['after'] == 'cursor'
    assert 'secret' not in json.dumps(wa.template_page())


def test_previews_and_window_gate(monkeypatch):
    monkeypatch.setenv('WHATSAPP_TEST_RECIPIENT', '919999999999')
    monkeypatch.setenv('WHATSAPP_WABA_ID', '123')
    def graph(method, *args, **kw):
        assert method == 'GET'
        return {'data': [{'name': 'hello', 'language': 'en', 'status': 'APPROVED'}]}
    monkeypatch.setattr(wa, 'graph', graph)
    assert wa.send_template_message('919999999999', 'hello', 'en', [], 'request-1')['state'] == 'preview'
    with pytest.raises(ValueError):
        wa.send_text_message('919999999999', 'Hi', 'request-2')
    assert wa.send_text_message('919999999999', 'Hi', 'request-2', True)['state'] == 'preview'


def test_dedup_and_unknown_outcomes(monkeypatch):
    records = {}
    class Result:
        def __init__(self, value): self.value = value
        def fetchone(self): return self.value
    class Conn:
        def execute(self, sql, args):
            if sql.startswith('INSERT'):
                rid, fp = args
                if rid in records: return Result(None)
                records[rid] = {'fingerprint': fp, 'state': 'pending', 'result': None}
                return Result({'request_id': rid})
            if sql.startswith('SELECT'): return Result(records[args[0]])
            state, result, rid = args
            records[rid].update(state=state, result=json.loads(result))
    @contextmanager
    def get_conn(): yield Conn()
    monkeypatch.setitem(sys.modules, 'app.database', SimpleNamespace(get_conn=get_conn))
    calls = []
    def action(): calls.append(1); return {'state': 'accepted'}
    assert wa.once('request-1', {'to': 'one'}, action)['state'] == 'accepted'
    assert wa.once('request-1', {'to': 'one'}, action)['state'] == 'accepted'
    assert len(calls) == 1
    with pytest.raises(ValueError): wa.once('request-1', {'to': 'two'}, action)
    def timeout(): calls.append(2); raise TimeoutError()
    assert wa.once('request-2', {}, timeout)['state'] == 'failed_or_unknown'
    wa.once('request-2', {}, timeout)
    assert calls == [1, 2]


def test_protocol_auth_and_tools(monkeypatch):
    monkeypatch.setenv('WHATSAPP_MCP_API_KEY', 'test-only-key')
    @asynccontextmanager
    async def lifespan(app):
        async with wa.mcp.session_manager.run(): yield
    app = FastAPI(lifespan=lifespan)
    app.mount('/mcp', wa.mcp_app)
    headers = {'Authorization': 'Bearer test-only-key', 'Accept': 'application/json, text/event-stream'}
    with TestClient(app, base_url='http://localhost') as client:
        assert client.post('/mcp/', json={}).status_code == 401
        assert client.post('/mcp/', json={}, headers={**headers, 'Origin': 'https://evil.invalid'}).status_code == 403
        init = client.post('/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
            'params': {'protocolVersion': '2025-06-18', 'capabilities': {},
                       'clientInfo': {'name': 'test', 'version': '1'}}})
        assert init.status_code == 200, init.text
        result = client.post('/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'}).json()
        assert {t['name'] for t in result['result']['tools']} == {
            'get_whatsapp_status', 'list_templates', 'send_template_message',
            'send_text_message', 'send_tl_broadcast'}
        result = client.post('/mcp/', headers=headers, json={
            'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call',
            'params': {'name': 'get_whatsapp_status', 'arguments': {}}}).json()
        assert 'test-only-key' not in json.dumps(result)
        assert not result['result'].get('isError'), result
        content = result['result'].get('structuredContent')
        if content is None:
            content = json.loads(result['result']['content'][0]['text'])
        assert content['connected'] is False


def test_existing_app_lifespan_and_broadcast_gates(monkeypatch):
    import importlib
    importlib.reload(wa)
    monkeypatch.setenv('DATABASE_URL', 'postgresql://test.invalid/test')
    from app import main
    calls = []
    monkeypatch.setattr(main.database, 'init_db', lambda: calls.append('database'))
    monkeypatch.setattr(wa, 'init_tables', lambda: calls.append('dedup'))
    monkeypatch.setattr(main.crud, 'get_whatsapp_broadcast_config', lambda: {'enabled': True})
    monkeypatch.setattr(main, '_claim_zone_broadcast', lambda *a: pytest.fail('Broadcast should not start'))
    with TestClient(main.app, base_url='http://localhost') as client:
        assert calls == ['database', 'dedup']
        assert client.get('/health').status_code == 200
        assert client.post('/mcp/', json={}).status_code == 401
        with pytest.raises(HTTPException):
            main.admin_whatsapp_broadcast_send_now(None)
    assert main.app.state.whatsapp_broadcast_task.done()
