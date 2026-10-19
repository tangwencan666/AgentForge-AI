"""Opt-in pytest plugin: no project dotenv reads or real socket connections."""
import os
from pathlib import Path
import sys
import dotenv
from app.core.config import ROOT, Settings


def audit(event, args):
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        if Path(os.fsdecode(args[0])).resolve() == (ROOT / '.env').resolve():
            raise RuntimeError('OFFLINE_PROJECT_ENV_READ_FORBIDDEN')
    # CPython on Windows implements socketpair with a loopback self-pipe.
    # Permit only that stdlib call site, not HTTP, DNS, DB or provider traffic.
    if event == 'socket.connect' and sys.platform == 'win32':
        caller = sys._getframe(1).f_code
        if caller.co_name == '_fallback_socketpair' and Path(caller.co_filename).name == 'socket.py' and args[1][0] in {'127.0.0.1', '::1'}:
            return
    if event in {'socket.connect', 'socket.getaddrinfo'}:
        raise RuntimeError('OFFLINE_NETWORK_FORBIDDEN')


def pytest_configure(config):
    sys.addaudithook(audit)
    Settings.model_config = {**Settings.model_config, 'env_file': None}
    dotenv.dotenv_values = lambda *args, **kwargs: {}
