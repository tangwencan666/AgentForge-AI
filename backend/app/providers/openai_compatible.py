"""Pinned public HTTPS, verified SNI, no redirects/proxies; bounded streaming chat."""
import asyncio
import ipaddress
import json
import socket
from time import monotonic
from urllib.parse import urlsplit
import httpx
from app.providers.base import ModelReply, ProviderFailure


async def public_address(host):
    entries = await asyncio.wait_for(asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM), timeout=5)
    addresses = sorted({entry[4][0] for entry in entries})
    if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
        raise ProviderFailure('MODEL_ENDPOINT_BLOCKED')
    return addresses[0]


class OpenAICompatible:
    async def complete(self, config, messages, credential, delta):
        started = monotonic()
        try:
            async with asyncio.timeout(config['timeout']):
                url = httpx.URL(config['base_url'].rstrip('/') + '/chat/completions')
                host = url.host
                address = await public_address(host)
                pinned = url.copy_with(host=address)
                body = {'model': config['model'], 'messages': messages, 'stream': True,
                        'stream_options': {'include_usage': True}, 'temperature': config['temperature'],
                        config.get('token_parameter', 'max_completion_tokens'): config['max_tokens']}
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=config['timeout']) as client:
                    async with client.stream('POST', pinned, headers={'Host': host, 'Authorization': 'Bearer ' + credential,
                        'Accept': 'text/event-stream'}, json=body, extensions={'sni_hostname': host}) as response:
                        if response.status_code != 200:
                            status = response.status_code
                            code = {401: 'MODEL_AUTH_INVALID', 403: 'MODEL_ACCESS_DENIED', 429: 'MODEL_RATE_LIMIT'}.get(status, 'MODEL_SERVER_ERROR' if status >= 500 else 'MODEL_REQUEST_REJECTED')
                            raise ProviderFailure(code, status == 429 or status >= 500, status)
                        if 'text/event-stream' not in response.headers.get('content-type', ''):
                            raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                        raw, frame, size, first, usage, finished, done = '', b'', 0, None, None, False, False
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > 262144:
                                raise ProviderFailure('MODEL_RESPONSE_LIMIT')
                            frame += chunk
                            if len(frame) > 65536:
                                raise ProviderFailure('MODEL_FRAME_LIMIT')
                            while b'\n' in frame:
                                line, frame = frame.split(b'\n', 1)
                                line = line.rstrip(b'\r')
                                if not line.startswith(b'data:'):
                                    continue
                                data = line[5:].strip()
                                if data == b'[DONE]':
                                    done = True
                                    break
                                item = json.loads(data)
                                if 'error' in item:
                                    raise ProviderFailure('MODEL_STREAM_ERROR')
                                if item.get('usage') is not None:
                                    usage = item['usage']
                                for choice in item.get('choices', []):
                                    if choice.get('index', 0) != 0:
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    if choice.get('delta', {}).get('tool_calls'):
                                        raise ProviderFailure('MODEL_NATIVE_TOOL_CALL_REJECTED')
                                    text = choice.get('delta', {}).get('content') or ''
                                    if not isinstance(text, str):
                                        raise ProviderFailure('MODEL_PROTOCOL_INVALID')
                                    if text:
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
                        if not done or not finished or not raw:
                            raise ProviderFailure('MODEL_STREAM_INCOMPLETE')
                        counts = [None, None, None]
                        if usage is not None:
                            counts = [usage.get(k) for k in ('prompt_tokens', 'completion_tokens', 'total_tokens')]
                            if any(type(v) is not int or v < 0 for v in counts) or sum(counts[:2]) != counts[2]:
                                raise ProviderFailure('MODEL_USAGE_INVALID')
                        return ModelReply(raw, *counts, first, int((monotonic() - started) * 1000))
        except ProviderFailure:
            raise
        except (TimeoutError, httpx.TimeoutException):
            raise ProviderFailure('MODEL_TIMEOUT', True) from None
        except httpx.HTTPError:
            raise ProviderFailure('MODEL_NETWORK_ERROR', True) from None
        except (ValueError, TypeError, KeyError, AttributeError, OSError):
            raise ProviderFailure('MODEL_PROTOCOL_INVALID') from None
