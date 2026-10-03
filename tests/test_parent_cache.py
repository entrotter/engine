"""Actual bounded loopback bridge: immutable cache, faults and owned lifetime."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import socket
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from entrotter_engine._parent_cache import (
    Bridge,
    MAX_CACHE,
    MAX_ENTRY,
    MAX_REQUESTS,
    Server,
    Handler,
    result_bytes,
)
from entrotter_engine.parent_cache import ParentCache

PARENT = {"chain_id": 1, "block_number": 2, "block_hash": "0x" + "ab" * 32}
ADDRESS = "0x" + "cd" * 20
SECRET = "PRIVATE_PROVIDER_TOKEN_AND_BODY"


class Provider:
    def __init__(self):
        self.requests = Counter()
        self.mode = "normal"
        self.entered = threading.Event()
        self.release = threading.Event()
        self.condition = threading.Condition()
        self.calls = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                request = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"]))
                )
                key = json.dumps(
                    [request["method"], request["params"]], separators=(",", ":")
                )
                with owner.condition:
                    owner.requests[key] += 1
                    owner.calls.append(request)
                    call_number = len(owner.calls)
                    owner.condition.notify_all()
                owner.entered.set()
                if owner.mode == "stall" or owner.mode.startswith("barrier"):
                    owner.release.wait(6)
                if owner.mode in {"http", "redirect"}:
                    self.send_response(500 if owner.mode == "http" else 302)
                    self.send_header("Location", "http://127.0.0.1:1/" + SECRET)
                    self.end_headers()
                    return
                rid = request["id"]
                if owner.mode == "id":
                    rid = rid + 1
                if owner.mode == "error" or owner.mode == "barrier_error" and call_number == 1:
                    raw = json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": rid,
                            "error": {"code": -1, "message": SECRET},
                        }
                    ).encode()
                elif owner.mode == "malformed":
                    raw = SECRET.encode()
                else:
                    result = '"0x01"'
                    if request["method"] == "eth_getBlockByNumber":
                        result = json.dumps(
                            {
                                "hash": PARENT["block_hash"]
                                if owner.mode != "wrong_parent"
                                else "0x" + "ee" * 32
                            }
                        )
                    if owner.mode in {"large", "barrier_large"}:
                        result = '"' + "x" * (MAX_ENTRY + 1) + '"'
                    if owner.mode == "overflow":
                        result = '"' + "x" * (4 * 1024 * 1024) + '"'
                    if owner.mode in {"lexical", "barrier", "barrier_error"} and request['method'] != 'eth_getBlockByNumber':
                        result = '{ "n" : 1.00, "text": "\\u007f" }'
                    if owner.mode in {"null", "barrier_null"}:
                        result = 'null'
                    raw = (
                        '{"jsonrpc":"2.0","id":'
                        + json.dumps(rid)
                        + ',"result":'
                        + result
                        + "}"
                    ).encode()
                try:
                    self.send_response(200)
                    self.send_header(
                        "Content-Length",
                        str(len(raw) + (10 if owner.mode == "truncated" else 0)),
                    )
                    self.end_headers()
                    self.wfile.write(raw)
                except (OSError, ConnectionError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/{SECRET}"

    def wait_calls(self, count, timeout=2):
        with self.condition:
            return self.condition.wait_for(lambda: len(self.calls) >= count, timeout)

    def close(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)


def request(method="eth_getBalance", params=None, rid=1):
    return {
        "jsonrpc": "2.0",
        "id": rid,
        "method": method,
        "params": params if params is not None else [ADDRESS, PARENT["block_hash"]],
    }


def post(url, value):
    return (
        build_opener(ProxyHandler({}))
        .open(
            Request(
                url, json.dumps(value).encode(), {"Content-Type": "application/json"}
            ),
            timeout=5,
        )
        .read()
    )


class ParentCacheTests(unittest.TestCase):
    def setUp(self):
        self.provider = Provider()
        self.addCleanup(self.provider.close)

    def bridge(self):
        return ParentCache(self.provider.url, PARENT, time.monotonic() + 30)

    def reply_thread(self, bridge, value, responses):
        def reply():
            responses[value['id']] = bridge.reply(value)
        thread = threading.Thread(target=reply)
        thread.start()
        return thread

    def finish_replies(self, threads):
        self.provider.release.set()
        for thread in threads:
            thread.join(5)
            self.assertFalse(thread.is_alive(), 'Bounded reply thread remained active')

    def test_brief_handler_overlap_admits_next_read_without_extra_active_handlers(self):
        bridge = Bridge(self.provider.url, PARENT, time.monotonic() + 30)
        server = Server(bridge, "0" * 32)
        entered = threading.Event()
        condition = threading.Condition()
        active = 0
        peak = 0
        accepted = 0
        handle = Handler.handle
        dispatch = server.process_request
        idle = []

        def counted(handler):
            nonlocal active, peak
            with condition:
                active += 1
                peak = max(peak, active)
                condition.notify_all()
            try:
                handle(handler)
            finally:
                with condition:
                    active -= 1
                    condition.notify_all()

        def accepting(connection, address):
            nonlocal accepted
            accepted += 1
            if accepted == 5:
                entered.set()
            dispatch(connection, address)

        def release_one():
            if entered.wait(2):
                time.sleep(0.02)
                idle[0].shutdown(socket.SHUT_RDWR)
                idle[0].close()

        serving = threading.Thread(target=server.serve_forever)
        releaser = threading.Thread(target=release_one)
        try:
            with (
                patch.object(Handler, "handle", counted),
                patch.object(server, "process_request", side_effect=accepting),
            ):
                serving.start()
                for _ in range(4):
                    idle.append(socket.create_connection(server.server_address, timeout=1))
                with condition:
                    self.assertTrue(condition.wait_for(lambda: active == 4, timeout=2))
                releaser.start()
                url = "http://127.0.0.1:" + str(server.server_port) + "/" + "0" * 32
                value = json.loads(post(url, request("eth_chainId", [], rid=5)))
                self.assertEqual(value, {"jsonrpc": "2.0", "id": 5, "result": "0x01"})
                self.assertEqual(bridge.stats["refused_handlers"], 0)
                self.assertEqual(peak, 4)
                self.assertEqual(bridge.stats["upstream"], 1)
        finally:
            if releaser.ident is not None:
                releaser.join(2)
            for connection in idle:
                connection.close()
            server.shutdown()
            server.server_close()
            serving.join(2)
        self.assertFalse(serving.is_alive())
        self.assertFalse(releaser.is_alive())

    def test_persistent_handler_pressure_refuses_without_extending_deadline(self):
        bridge = Bridge(self.provider.url, PARENT, time.monotonic() + 0.02)
        server = Server(bridge, "0" * 32)
        for _ in range(4):
            self.assertTrue(server.slots.acquire(blocking=False))
        connection, peer = socket.socketpair()
        started = time.monotonic()
        try:
            server.process_request(connection, ("127.0.0.1", 1))
            self.assertEqual(bridge.stats["refused_handlers"], 1)
            self.assertLess(time.monotonic() - started, 0.2)
            peer.settimeout(0.2)
            self.assertEqual(peer.recv(1), b"")
        finally:
            connection.close()
            peer.close()
            server.server_close()

    def duplicate_replies(self, bridge, first, second):
        responses={};initial=len(self.provider.calls)
        threads=[self.reply_thread(bridge,first,responses)]
        try:
            self.assertTrue(self.provider.wait_calls(initial+1))
            threads.append(self.reply_thread(bridge,second,responses))
            deadline=time.monotonic()+2
            while bridge.stats['requests']<2 and time.monotonic()<deadline:time.sleep(.01)
            admitted=bridge.stats['requests']==2
        finally:
            self.finish_replies(threads)
        self.assertTrue(admitted,'Duplicate request was not admitted before releasing its owner')
        return responses

    def test_distinct_pinned_reads_enter_real_provider_concurrently(self):
        self.provider.mode = 'barrier'
        bridge = Bridge(self.provider.url, PARENT, time.monotonic()+30)
        responses = {}
        threads = [self.reply_thread(bridge, request(rid=1), responses)]
        try:
            self.assertTrue(self.provider.wait_calls(1))
            threads.append(self.reply_thread(bridge, request(params=['0x'+'ef'*20,PARENT['block_hash']],rid=2), responses))
            concurrent = self.provider.wait_calls(2)
        finally:
            self.finish_replies(threads)
        self.assertTrue(concurrent, 'A different pinned key was blocked by another upstream read')
        self.assertEqual({key:json.loads(raw)['id'] for key,raw in responses.items()},{1:1,2:2})
        self.assertEqual(bridge.stats['upstream'],2)

    def test_same_key_waiter_admitted_during_read_and_coalesces_raw_result(self):
        self.provider.mode = 'barrier'
        bridge = Bridge(self.provider.url, PARENT, time.monotonic()+30)
        responses = {}
        threads = [self.reply_thread(bridge, request(rid=1), responses)]
        try:
            self.assertTrue(self.provider.wait_calls(1))
            threads.append(self.reply_thread(bridge, request(rid='fresh'), responses))
            deadline=time.monotonic()+2
            while bridge.stats['requests']<2 and time.monotonic()<deadline:time.sleep(.01)
            admitted=bridge.stats['requests']==2
            upstream_before_release=len(self.provider.calls)
        finally:
            self.finish_replies(threads)
        self.assertTrue(admitted, 'The waiter could not be admitted while remote I/O held the global lock')
        self.assertEqual(upstream_before_release,1)
        self.assertEqual(sum(self.provider.requests.values()),1)
        self.assertEqual(json.loads(responses['fresh'])['id'],'fresh')
        self.assertIn(b'{ "n" : 1.00, "text": "\\u007f" }',responses['fresh'])
        self.assertEqual(bridge.stats['hits'],1)
        self.assertEqual(len(bridge.pending),0)

    def test_owner_error_wakes_waiter_and_only_success_is_cached(self):
        self.provider.mode='barrier_error'
        bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
        responses=self.duplicate_replies(bridge,request(rid=1),request(rid=2))
        self.assertEqual(json.loads(responses[1])['error']['message'],'rejected')
        self.assertIn('result',json.loads(responses[2]))
        self.assertNotIn(SECRET.encode(),responses[1])
        self.assertEqual(bridge.stats['upstream'],2)
        self.assertEqual(bridge.stats['errors'],1)
        self.assertEqual(bridge.stats['hits'],0)
        self.assertEqual(len(bridge.cache),1)
        self.assertEqual(len(bridge.pending),0)
        self.assertEqual(json.loads(bridge.reply(request(rid=3)))['id'],3)
        self.assertEqual(bridge.stats['upstream'],2)

    def test_matching_parent_header_coalesces_with_fresh_ids(self):
        self.provider.mode='barrier'
        bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
        first=request('eth_getBlockByNumber',['0x2',True],rid=1)
        second=request('eth_getBlockByNumber',['0x2',True],rid=2)
        responses=self.duplicate_replies(bridge,first,second)
        self.assertEqual(json.loads(responses[2])['result']['hash'],PARENT['block_hash'])
        self.assertEqual(bridge.stats['upstream'],1)
        self.assertEqual(bridge.stats['hits'],1)
        self.assertFalse(bridge.pending)

    def test_receipt_and_volatile_reads_remain_independently_concurrent(self):
        self.provider.mode='barrier'
        for value in [request('eth_getTransactionReceipt',['0x'+'ef'*32]),
                      request('eth_gasPrice',[]),request(params=[ADDRESS,'latest']),
                      request(params=[ADDRESS,'0x2']),request(params=[ADDRESS,'0x'+'ee'*32])]:
            with self.subTest(method=value['method'],params=value['params']):
                self.provider.release.clear()
                initial=len(self.provider.calls)
                bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
                responses={}
                threads=[self.reply_thread(bridge,value,responses)]
                try:
                    self.assertTrue(self.provider.wait_calls(initial+1))
                    threads.append(self.reply_thread(bridge,{**value,'id':2},responses))
                    concurrent=self.provider.wait_calls(initial+2)
                finally:
                    self.finish_replies(threads)
                self.assertTrue(concurrent,'An uncached read was wrongly coalesced')
                self.assertEqual(bridge.stats['upstream'],2)
                self.assertEqual(bridge.stats['uncached'],2)
                self.assertFalse(bridge.cache)
                self.assertFalse(bridge.pending)

    def test_null_and_oversized_successes_release_waiters_without_sharing(self):
        for mode in ['barrier_null','barrier_large']:
            with self.subTest(mode=mode):
                self.provider.mode=mode
                self.provider.release.clear()
                bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
                responses=self.duplicate_replies(bridge,request(rid=1),request(rid=2))
                self.assertEqual(json.loads(responses[2])['id'],2)
                self.assertEqual(bridge.stats['upstream'],2)
                self.assertEqual(bridge.stats['uncached'],2)
                self.assertFalse(bridge.cache)
                self.assertFalse(bridge.pending)

    def test_pending_keys_are_bounded_without_discarding_admitted_reads(self):
        self.provider.mode='barrier'
        bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
        responses={};threads=[]
        try:
            for number in range(4):
                value=request(params=['0x'+format(number,'040x'),PARENT['block_hash']],rid=number)
                threads.append(self.reply_thread(bridge,value,responses))
            self.assertTrue(self.provider.wait_calls(4))
            self.assertEqual(len(bridge.pending),4)
            refused=bridge.reply(request(params=['0x'+format(5,'040x'),PARENT['block_hash']],rid=5))
            self.assertEqual(json.loads(refused)['error']['message'],'limit')
            self.assertEqual(len(self.provider.calls),4)
        finally:
            self.finish_replies(threads)
        self.assertEqual(len(responses),4)
        self.assertFalse(bridge.pending)
        self.assertEqual(bridge.stats['upstream'],4)

    def test_deadline_releases_pending_owner_and_waiter_with_finite_errors(self):
        self.provider.mode='stall'
        bridge=Bridge(self.provider.url,PARENT,time.monotonic()+.3)
        responses={};threads=[self.reply_thread(bridge,request(rid=1),responses)]
        try:
            self.assertTrue(self.provider.wait_calls(1))
            threads.append(self.reply_thread(bridge,request(rid=2),responses))
            for thread in threads:
                thread.join(2)
                self.assertFalse(thread.is_alive())
            self.assertEqual(len(responses),2)
            for raw in responses.values():
                self.assertIn(json.loads(raw)['error']['message'],{'timeout','limit'})
                self.assertNotIn(SECRET.encode(),raw)
            self.assertFalse(bridge.pending)
            self.assertFalse(bridge.cache)
        finally:
            self.finish_replies(threads)

    def test_owner_cancellation_releases_waiter_and_preserves_exact_exception(self):
        bridge=Bridge(self.provider.url,PARENT,time.monotonic()+30)
        entered=threading.Event();release=threading.Event();responses={};errors={}
        original=KeyboardInterrupt(SECRET)
        calls=0
        def fetch(*args):
            nonlocal calls
            calls+=1
            if calls==1:
                entered.set()
                release.wait(3)
                raise original
            return b'"0x02"','0x02'
        def reply(rid):
            try:responses[rid]=bridge.reply(request(rid=rid))
            except BaseException as error:errors[rid]=error
        threads=[]
        with patch.object(bridge,'fetch',side_effect=fetch):
            try:
                threads.append(threading.Thread(target=reply,args=(1,)));threads[-1].start()
                self.assertTrue(entered.wait(2))
                threads.append(threading.Thread(target=reply,args=(2,)));threads[-1].start()
                end=time.monotonic()+2
                while bridge.stats['requests']<2 and time.monotonic()<end:time.sleep(.01)
                self.assertEqual(bridge.stats['requests'],2)
            finally:
                release.set()
                for thread in threads:
                    thread.join(3)
                    self.assertFalse(thread.is_alive())
        self.assertIs(errors[1],original)
        self.assertEqual(json.loads(responses[2])['result'],'0x02')
        self.assertEqual(calls,2)
        self.assertFalse(bridge.pending)

    def test_cache_preserves_raw_result_and_binds_new_id(self):
        self.provider.mode = "lexical"
        with self.bridge() as cache:
            first = post(cache.url, request(rid=1))
            second = post(cache.url, request(rid="next"))
            self.assertEqual(json.loads(second)["id"], "next")
            token = b'{ "n" : 1.00, "text": "\\u007f" }'
            self.assertIn(token, first)
            self.assertIn(token, second)
            self.assertEqual(sum(self.provider.requests.values()), 1)
        self.assertEqual(cache.stats["hits"], 1)
        self.assertEqual(cache.stats["entries"], 1)
        self.assert_closed(cache)

    def test_full_method_params_key_and_only_parent_hash_cache(self):
        with self.bridge() as cache:
            values = [
                request(),
                request("eth_getCode"),
                request(params=["0x" + "ef" * 20, PARENT["block_hash"]]),
                request(params=[ADDRESS, "latest"]),
                request(params=[ADDRESS, "pending"]),
                request(params=[ADDRESS, "0x2"]),
                request(params=[ADDRESS, "0x" + "11" * 32]),
                request("eth_gasPrice", []),
                request("eth_chainId", []),
            ]
            for value in values:
                post(cache.url, value)
                post(cache.url, value)
        self.assertEqual(cache.stats["entries"], 3)
        self.assertEqual(sum(self.provider.requests.values()), 15)

    def test_checked_parent_header_and_misbound_refusal(self):
        with self.bridge() as cache:
            value = request("eth_getBlockByNumber", ["0x2", True])
            post(cache.url, value)
            post(cache.url, value)
        self.assertEqual(cache.stats["hits"], 1)
        self.provider.mode = "wrong_parent"
        with self.bridge() as cache:
            for _ in range(2):
                self.assertEqual(
                    json.loads(post(cache.url, value))["error"]["message"],
                    "invalid_response",
                )
        self.assertEqual(cache.stats["entries"], 0)

    def test_errors_and_bad_wire_never_cached_or_leak(self):
        for mode, code in [
            ("http", "http_error"),
            ("redirect", "http_error"),
            ("error", "rejected"),
            ("id", "invalid_response"),
            ("malformed", "invalid_response"),
            ("truncated", "invalid_response"),
            ("overflow", "response_too_large"),
        ]:
            self.provider.mode = mode
            with self.subTest(mode=mode), self.bridge() as cache:
                for _ in range(2):
                    raw = post(cache.url, request())
                    self.assertNotIn(SECRET.encode(), raw)
                    self.assertEqual(json.loads(raw)["error"]["message"], code)
            self.assertEqual(cache.stats["entries"], 0)
            self.assert_closed(cache)

    def test_oversized_entry_forwarded_without_cache(self):
        self.provider.mode = "large"
        with self.bridge() as cache:
            for _ in range(2):
                self.assertIn("result", json.loads(post(cache.url, request())))
        self.assertEqual(cache.stats["entries"], 0)
        self.assertEqual(cache.stats["upstream"], 2)

    def test_request_limits_unknown_writes_and_duplicate_keys(self):
        with self.bridge() as cache:
            for value in [
                request("eth_sendRawTransaction", ["0x00"]),
                request("anvil_nodeInfo", []),
                request(params=[ADDRESS, {"blockHash": PARENT["block_hash"]}]),
                [request()] * 9,
                request(rid=True),
            ]:
                self.assertIn("error", json.loads(post(cache.url, value)))
            with self.assertRaises(HTTPError):
                post(cache.url, "x" * 4096)
            raw = (
                build_opener(ProxyHandler({}))
                .open(
                    Request(
                        cache.url,
                        b'{"id":1,"id":2}',
                        {"Content-Type": "application/json"},
                    )
                )
                .read()
            )
            self.assertEqual(json.loads(raw)["error"]["message"], "invalid_request")
        self.assertEqual(sum(self.provider.requests.values()), 0)

    def test_anvil_optional_params_and_unsupported_method_id(self):
        with self.bridge() as cache:
            metadata = {"jsonrpc": "2.0", "id": 41, "method": "eth_chainId"}
            self.assertEqual(json.loads(post(cache.url, metadata))["id"], 41)
            metadata["method"] = "anvil_nodeInfo"
            refused = json.loads(post(cache.url, metadata))
            self.assertEqual(refused["id"], 41)
            self.assertEqual(refused["error"]["code"], -32601)
        self.assertEqual(sum(self.provider.requests.values()), 1)

    def test_receipt_fallback_always_forwards_without_cache(self):
        with self.bridge() as cache:
            value = request("eth_getTransactionReceipt", ["0x" + "ef" * 32])
            for _ in range(2):
                self.assertIn("result", json.loads(post(cache.url, value)))
        self.assertEqual(cache.stats["upstream"], 2)
        self.assertEqual(cache.stats["entries"], 0)
        self.assertEqual(cache.stats["hits"], 0)

    def test_owner_close_kills_blocked_handler_and_preserves_primary(self):
        self.provider.mode = "stall"
        cache = self.bridge()
        cache.__enter__()
        finished = threading.Event()

        def blocked():
            try:
                post(cache.url, request())
            except Exception:
                pass
            finally:
                finished.set()

        thread = threading.Thread(target=blocked)
        thread.start()
        self.assertTrue(self.provider.entered.wait(2))
        started = time.monotonic()
        cache.__exit__(ValueError, ValueError("primary"), None)
        self.assertLess(time.monotonic() - started, 4)
        self.assertTrue(finished.wait(2))
        thread.join(2)
        self.assert_closed(cache)

    def test_deadline_terminates_without_owner_close(self):
        cache = ParentCache(self.provider.url, PARENT, time.monotonic() + 1)
        cache.__enter__()
        cache.process.wait(timeout=3)
        cache.__exit__(None, None, None)
        self.assert_closed(cache)

    def test_http_timeout_returns_only_finite_error(self):
        self.provider.mode = "stall"
        bridge = Bridge(self.provider.url, PARENT, time.monotonic() + 0.15)
        raw = bridge.reply(request())
        self.assertEqual(json.loads(raw)["error"]["message"], "timeout")
        self.assertNotIn(SECRET.encode(), raw)
        self.assertEqual(len(bridge.cache), 0)

    def test_wait_failure_still_kills_reaps_and_closes_owned_process(self):
        cache = self.bridge()
        cache.__enter__()
        original_wait = cache.process.wait
        calls = 0

        def failed_first_wait(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError(SECRET)
            return original_wait(*args, **kwargs)

        with patch.object(cache.process, "wait", side_effect=failed_first_wait):
            # Cleanup must not replace an already active primary trace failure.
            cache.__exit__(ValueError, ValueError("primary"), None)
        self.assertIsNotNone(cache.process.returncode)
        self.assertTrue(cache.process.stdin.closed)
        self.assertTrue(cache.process.stdout.closed)
        with self.assertRaises(ProcessLookupError):
            os.kill(cache.process.pid, 0)

    def test_invalid_startup_config_is_closed_without_provider_text(self):
        cache = ParentCache(
            self.provider.url, {**PARENT, "block_hash": "bad"}, time.monotonic() + 30
        )
        with self.assertRaisesRegex(Exception, "exited before startup") as failure:
            cache.__enter__()
        self.assertNotIn(SECRET, str(failure.exception))
        self.assertIsNotNone(cache.process.returncode)
        self.assertTrue(cache.process.stdin.closed)
        self.assertTrue(cache.process.stdout.closed)

    def assert_closed(self, cache):
        self.assertEqual(cache.process.returncode, 0)
        self.assertTrue(cache.process.stdin.closed)
        self.assertTrue(cache.process.stdout.closed)
        with self.assertRaises(ProcessLookupError):
            os.kill(cache.process.pid, 0)
        with socket.socket() as sock:
            sock.settimeout(0.2)
            self.assertNotEqual(
                sock.connect_ex(
                    ("127.0.0.1", int(cache.url.split(":")[2].split("/")[0]))
                ),
                0,
            )

    def test_cache_byte_and_call_caps_no_provider_fallback_value(self):
        bridge = Bridge(self.provider.url, PARENT, time.monotonic() + 30)
        bridge.bytes = MAX_CACHE
        self.assertIn("result", json.loads(bridge.reply(request())))
        self.assertEqual(len(bridge.cache), 0)
        bridge.stats["requests"] = MAX_REQUESTS
        self.assertEqual(
            json.loads(bridge.reply(request()))["error"]["message"], "limit"
        )
        self.assertEqual(sum(self.provider.requests.values()), 1)

    def test_strict_response_ids_duplicate_keys_and_untrusted_types(self):
        for raw in [
            b'{"jsonrpc":"2.0","id":true,"result":"x"}',
            b'{"jsonrpc":"2.0","id":1,"result":1,"result":2}',
            b'{"jsonrpc":"2.0","id":1,"result":NaN}',
        ]:
            with self.assertRaises(Exception):
                result_bytes(raw, 1)
