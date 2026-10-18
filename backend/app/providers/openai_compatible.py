"""Pinned public HTTPS, verified SNI, no redirects/proxies; bounded streaming chat."""
import asyncio
import ipaddress
import json
import socket
import os
from time import monotonic
from urllib.parse import urlsplit
import httpx
from app.providers.base import ModelReply, ProviderFailure
from app.services.permit_authority import require_dispatch


def assert_model_egress():
    if os.environ.get('AGENTFORGE_EXTERNAL_MODELS_BLOCKED', '').lower() in {'1', 'true'}:
        raise ProviderFailure('MODEL_EGRESS_BLOCKED')


async def public_address(host):
    entries = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM), timeout=5)
    addresses = sorted({entry[4][0] for entry in entries})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ProviderFailure('MODEL_ENDPOINT_BLOCKED')
    return addresses[0]


class OpenAICompatible:
    def http_client(self, timeout):
        return httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=timeout,
                                 transport=httpx.AsyncHTTPTransport(retries=0))

    def usage_metadata(self, usage):
        if not isinstance(usage, dict): return None
        result = {}
        for source, target in [('prompt_cache_hit_tokens', 'cache_hit_tokens'), ('prompt_cache_miss_tokens', 'cache_miss_tokens')]:
            value = usage.get(source)
            if type(value) is int and value >= 0: result[target] = value
        for source, key, target in [('prompt_tokens_details', 'cached_tokens', 'cached_tokens'),
                                    ('completion_tokens_details', 'reasoning_tokens', 'reasoning_tokens')]:
            detail = usage.get(source)
            value = detail.get(key) if isinstance(detail, dict) else None
            if type(value) is int and value >= 0: result[target] = value
        return result or None

    def request_body(self, config, messages):
        return {'model': config['model'], 'messages': messages, 'stream': True,
                'stream_options': {'include_usage': True}, 'temperature': config['temperature'],
                config.get('token_parameter', 'max_completion_tokens'): config['max_tokens']}

    def parse_usage(self, usage):
        if usage is None:
            return [None, None, None]
        if not isinstance(usage, dict):
            raise ProviderFailure('MODEL_USAGE_INVALID')
        counts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
        if any(type(v) is not int or v < 0 for v in counts) or sum(counts[:2]) != counts[2]:
            raise ProviderFailure('MODEL_USAGE_INVALID')
        return counts

    async def complete(self, config, messages, credential, delta, *, dispatch=None):
        started = monotonic()
        response_status = None
        try:
            lease = require_dispatch(dispatch)
            assert_model_egress()
            async with asyncio.timeout(config['timeout']):
                url = httpx.URL(config['base_url'].rstrip('/') + '/chat/completions')
                host = url.host
                body = self.request_body(config, messages)
                address = await public_address(host)
                pinned = url.copy_with(host=address)
                await lease.commit(config, body)  # Durable intent, committed before entering HTTP transport.
                async with self.http_client(config['timeout']) as client:
                    async with client.stream('POST', pinned, headers={'Host': host, 'Authorization': 'Bearer ' + credential,
                        'Accept': 'text/event-stream'}, json=body, extensions={'sni_hostname': host}) as response:
                        response_status = response.status_code
                        if response.status_code != 200:
                            status = response.status_code
                            code = {401: 'MODEL_AUTH_INVALID', 402: 'MODEL_PAYMENT_REQUIRED', 403: 'MODEL_ACCESS_DENIED',
                                    422: 'MODEL_REQUEST_INVALID', 429: 'MODEL_RATE_LIMIT'}.get(status, 'MODEL_SERVER_ERROR' if status >= 500 else 'MODEL_REQUEST_REJECTED')
                            raise ProviderFailure(code, status == 429 or status >= 500, status)
                        if 'text/event-stream' not in response.headers.get('content-type', ''):
                            raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                        raw, frame, size, first, usage, finished, done = '', b'', 0, None, None, False, False
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 262144:
                                raise ProviderFailure('MODEL_RESPONSE_LIMIT')
                            frame += chunk
                            while b'\n' in frame:
                                line, frame = frame.split(b'\n', 1)
                                if len(line) > 65536:
                                    raise ProviderFailure('MODEL_FRAME_LIMIT')
                                line = line.rstrip(b'\r')
                                if not line.startswith(b'data:'):
                                    continue
                                data = line[5:].strip()
                                if data == b'[DONE]':
                                    done = True
                                    break
                                item = json.loads(data)
                                if not isinstance(item, dict):
                                    raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                if 'error' in item:
                                    raise ProviderFailure('MODEL_STREAM_ERROR')
                                if item.get('usage') is not None:
                                    usage = item['usage']
                                choices = item.get('choices', [])
                                if not isinstance(choices, list) or len(choices) > 1:
                                    raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                for choice in choices:
                                    if not isinstance(choice, dict) or choice.get('index', 0) != 0:
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    delta_body = choice.get('delta', {})
                                    if not isinstance(delta_body, dict):
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    if delta_body.get('tool_calls') or delta_body.get('function_call'):
                                        raise ProviderFailure('MODEL_NATIVE_TOOL_CALL_REJECTED')
                                    reasoning = delta_body.get('reasoning_content')
                                    if reasoning is not None and not isinstance(reasoning, str):
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    # Reasoning text is neither returned nor sent to delta/checkpoints/logs.
                                    text = delta_body.get('content')
                                    text = '' if text is None else text
                                    if not isinstance(text, str):
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    if text:
                                        if finished:
                                            raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                        first = first if first is not None else int((monotonic() - started) * 1000)
                                        raw += text
                                        if len(raw.encode()) > 65536:
                                            raise ProviderFailure('MODEL_OUTPUT_LIMIT')
                                        await delta(text)
                                    reason = choice.get('finish_reason')
                                    if reason:
                                        if reason != 'stop':
                                            raise ProviderFailure('MODEL_OUTPUT_INCOMPLETE')
                                        finished = True
                                if done:
                                    break
                            if done:
                                break
                            if len(frame) > 65536:
                                raise ProviderFailure('MODEL_FRAME_LIMIT')
                        if not done or not finished or not raw:
                            raise ProviderFailure('MODEL_STREAM_INCOMPLETE')
                        counts = self.parse_usage(usage)
                        return ModelReply(raw, *counts, first, int((monotonic() - started) * 1000),
                                          response_status, True, self.usage_metadata(usage))
        except ProviderFailure as exc:
            if exc.status is None and response_status is not None: exc.status = response_status
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderFailure('MODEL_TIMEOUT', True, response_status) from None
        except httpx.HTTPError:
            raise ProviderFailure('MODEL_NETWORK_ERROR', True, response_status) from None
        except OSError:
            raise ProviderFailure('MODEL_NETWORK_ERROR', True) from None
        except (ValueError, TypeError, KeyError, AttributeError):
            raise ProviderFailure('MODEL_PROTOCOL_INVALID') from None
