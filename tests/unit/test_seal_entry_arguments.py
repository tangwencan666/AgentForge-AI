"""Reject ambiguous image rotation flags before configuration access; offline."""
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('flag', ['--replace', '--replace-approved-imag'])
def test_image_rotation_cannot_use_argparse_abbreviation(monkeypatch, flag):
    root = ROOT / 'work/seal-fixes' / ('arguments-' + uuid4().hex)
    (root / 'scripts').mkdir(parents=True)
    source = root / 'scripts/bootstrap-sandbox.py'
    source.write_bytes((ROOT / 'scripts/bootstrap-sandbox.py').read_bytes())
    monkeypatch.setitem(sys.modules, 'maintenance_policy', SimpleNamespace(
        cli_gate=lambda *_: None, maintenance_action=lambda *_: lambda function: function))
    def forbidden(*args, **kwargs):
        raise AssertionError('Ambiguous arguments must be rejected before dotenv access')
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(dotenv_values=forbidden))
    monkeypatch.setattr(sys, 'argv', [str(source), '--image-id', 'sha256:' + 'a' * 64, flag])
    spec = importlib.util.spec_from_file_location('seal_argument_' + uuid4().hex, source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert not (root / '.env').exists()
