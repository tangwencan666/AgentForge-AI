"""Reviewed DeepSeek Chat Completions profile, not a general endpoint override."""
from urllib.parse import urlsplit
from app.core.errors import AppError
from app.providers.base import ProviderFailure
from app.providers.openai_compatible import OpenAICompatible

MODELS = frozenset({'deepseek-flash', 'deepseek-v4-pro'})


def uses_deepseek_profile(config):
    return config.get('provider') == 'deepseek' or (config.get('provider') == 'openai_compatible'
        and urlsplit(config.get('base_url') or '').hostname == 'api.deepseek.com')


def validate_profile(config):
    url = urlsplit(config.get('base_url') or '')
    if (url.scheme != 'https' or url.hostname != 'api.deepseek.com' or url.port not in {None, 443}
            or url.username or url.password or url.query or url.fragment
            or url.path not in {'', '/', '/v1', '/v1/'}):
        raise AppError('MODEL_ENDPOINT_BLOCKED', 'DeepSeek requires its exact reviewed HTTPS endpoint', 409)
    if config.get('model') not in MODELS:
        raise AppError('MODEL_CAPABILITY_INVALID', 'DeepSeek model has not been reviewed', 409)
    if config.get('thinking_mode', 'disabled') not in {'enabled', 'disabled'} or config.get('reasoning_effort', 'high') not in {'low', 'high', 'max'}:
        raise AppError('MODEL_CAPABILITY_INVALID', 'Unsupported DeepSeek thinking configuration', 409)


class DeepSeek(OpenAICompatible):
    def request_body(self, config, messages):
        validate_profile(config)
        body = {'model': config['model'], 'messages': messages, 'stream': True,
                'stream_options': {'include_usage': True}, 'max_tokens': config['max_tokens'],
                'thinking': {'type': config.get('thinking_mode', 'disabled')}}
        if body['thinking']['type'] == 'enabled':
            body['reasoning_effort'] = config.get('reasoning_effort', 'high')
        else:
            body['temperature'] = config['temperature']
        return body

    def parse_usage(self, usage):
        counts = super().parse_usage(usage)
        if usage is None:
            return counts
        hit, miss = usage.get('prompt_cache_hit_tokens'), usage.get('prompt_cache_miss_tokens')
        if hit is not None or miss is not None:
            if any(type(v) is not int or v < 0 for v in (hit, miss)) or hit + miss != counts[0]:
                raise ProviderFailure('MODEL_USAGE_INVALID')
        for name, key, maximum in (('prompt_tokens_details', 'cached_tokens', counts[0]),
                                   ('completion_tokens_details', 'reasoning_tokens', counts[1])):
            detail = usage.get(name)
            if detail is not None:
                if not isinstance(detail, dict):
                    raise ProviderFailure('MODEL_USAGE_INVALID')
                value = detail.get(key)
                if value is not None and (type(value) is not int or value < 0 or value > maximum):
                    raise ProviderFailure('MODEL_USAGE_INVALID')
                if name == 'prompt_tokens_details' and hit is not None and value is not None and value != hit:
                    raise ProviderFailure('MODEL_USAGE_INVALID')
        # completion_tokens already includes reasoning_tokens: never add them again.
        return counts
