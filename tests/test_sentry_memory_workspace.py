"""Regression coverage for the private-memory proxy; no live Gateway required."""
from __future__ import annotations
import importlib.util
import io
import json
import sys
import types
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('workspace_proxy_test',ROOT/'api/sentry_memory_workspace.py')
proxy=importlib.util.module_from_spec(spec);spec.loader.exec_module(proxy)

class Handler:
    def __init__(self,command='GET',body=None,headers=None):
        self.command=command;self.response_headers={};self.status=None
        raw=json.dumps(body).encode() if body is not None else b''
        self.rfile=io.BytesIO(raw);self.wfile=io.BytesIO()
        self.headers={'Host':'localhost:8787','Origin':'http://localhost:8787','X-Sentry-Workspace':'1','Content-Type':'application/json','Content-Length':str(len(raw)),**(headers or {})}
    def send_response(self,status):self.status=status
    def send_header(self,key,value):self.response_headers[key]=value
    def end_headers(self):pass
    @property
    def data(self):return json.loads(self.wfile.getvalue()) if self.wfile.getvalue() else None

@pytest.fixture
def routes(monkeypatch):
    state=types.SimpleNamespace(token=str(uuid4()),dialect='sentry',calls=[],failure=None)
    package=types.ModuleType('api'); package.__path__=[];monkeypatch.setitem(sys.modules,'api',package)
    gateway=types.ModuleType('api.gateway_chat')
    gateway._gateway_dialect=lambda:state.dialect
    gateway.sentry_access_token_from_handler=lambda handler:state.token
    monkeypatch.setitem(sys.modules,gateway.__name__,gateway)
    client=types.ModuleType('api.sentry_gateway_client')
    class Error(Exception):
        def __init__(self,message,status=None):super().__init__(message);self.status=status
    client.SentryGatewayError=Error;state.Error=Error
    def call(method,path,token,payload=None):
        state.calls.append((method,path,token,payload))
        if state.failure:raise state.failure
        if method=='GET':return {'profile_id':state.token,'sections':[]}
        if method=='PUT':return {'section':'memory','content':payload['content'],'updated_at':'2026-09-09T00:00:00Z'}
        return None
    client.get_json=lambda path,token:call('GET',path,token)
    client.put_json=lambda path,token,body:call('PUT',path,token,body)
    client.delete_json=lambda path,token:call('DELETE',path,token)
    monkeypatch.setitem(sys.modules,client.__name__,client)
    state.wrapped=proxy.wrap_memory_route(lambda h,p:'original-route')
    return state

def body(routes):return {'content':'hello','expected_updated_at':None,'expected_profile_id':routes.token}
def request(routes,handler,path=proxy.PREFIX):return routes.wrapped(handler,urlsplit(path))

def test_other_routes_unchanged(routes):
    assert request(routes,Handler(),'/api/memory')=='original-route'
    assert request(routes,Handler(),'/api/agent/pending/memory')=='original-route'
    assert routes.calls==[]

def test_no_local_memory_fallback(routes):
    routes.dialect='hermes';h=Handler();request(routes,h)
    assert h.status==404 and not routes.calls

def test_sign_in_required(routes):
    routes.token=None;h=Handler();request(routes,h)
    assert h.status==401 and not routes.calls

@pytest.mark.parametrize('headers',[{'Origin':'https://evil.test'}, {'Origin':'null'}, {'Sec-Fetch-Site':'cross-site'}, {'Origin':'http://localhost:9999'}])
def test_cross_origin_blocked(routes,headers):
    h=Handler('PUT',body(routes),headers);request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==403 and not routes.calls

def test_existing_caller_token_only(routes):
    h=Handler();request(routes,h)
    assert routes.calls==[('GET','/api/memory/workspace',routes.token,None)]
    assert h.response_headers['Cache-Control']=='no-store'

def test_csrf_workspace_header_required(routes):
    h=Handler('PUT',body(routes),{'X-Sentry-Workspace':''});request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==403 and not routes.calls

def test_put_forwards_version_and_expected_profile(routes):
    payload=body(routes);h=Handler('PUT',payload);request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==200 and routes.calls[-1][3]==payload

@pytest.mark.parametrize('change',[{'target_profile_id':'forged'}, {'token':'secret'}, {'content':5}])
def test_unknown_authority_or_invalid_body_rejected(routes,change):
    h=Handler('PUT',{**body(routes),**change});request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==400 and not routes.calls

def test_delete_requires_original_version(routes):
    h=Handler('DELETE');request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==400 and not routes.calls

def test_delete_encodes_query_and_has_no_body(routes):
    h=Handler('DELETE');request(routes,h,proxy.PREFIX+f'/memory?expected_updated_at=2026-09-09T00%3A00%3A00%2B00%3A00&expected_profile_id={routes.token}')
    assert h.status==204 and not h.wfile.getvalue()
    assert '%2B00%3A00' in routes.calls[-1][1]

def test_duplicate_delete_parameter_rejected(routes):
    h=Handler('DELETE');request(routes,h,proxy.PREFIX+f'/memory?expected_updated_at=a&expected_updated_at=b&expected_profile_id={routes.token}')
    assert h.status==400 and not routes.calls

def test_conflict_preserves_status(routes):
    routes.failure=routes.Error('This section changed.',409);h=Handler('PUT',body(routes));request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==409 and h.data['error']=='This section changed.'

def test_transport_details_not_disclosed(routes):
    routes.failure=routes.Error('secret internal address',None);h=Handler();request(routes,h)
    assert h.status==503 and 'secret' not in str(h.data)

def test_request_body_size_checked_before_read(routes):
    h=Handler('PUT',body(routes),{'Content-Length':str(2*1024*1024+1)});request(routes,h,proxy.PREFIX+'/memory')
    assert h.status==400 and h.rfile.tell()==0


@pytest.mark.parametrize('path,mime',[('/static/sentry_workspace.js','text/javascript'),('/sentry_workspace.css','text/css')])
def test_only_constant_workspace_assets_are_served(routes,path,mime):
    h=Handler();request(routes,h,path)
    assert h.status==200 and h.response_headers['Content-Type'].startswith(mime)
    assert h.response_headers['Cache-Control']=='no-cache'
    assert len(h.wfile.getvalue())>100
    assert not routes.calls


def test_unknown_static_files_are_not_exposed(routes):
    h=Handler();assert request(routes,h,'/static/../api/sentry_memory_workspace.py')=='original-route'
    assert h.status is None
