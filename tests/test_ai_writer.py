import os
from ai_writer import AIWriter


def test_aiwriter_uses_stub_by_default():
    os.environ.pop('AI_PROVIDER', None)
    writer = AIWriter()
    assert writer.provider.__class__.__name__ == 'StubProvider'


def test_aiwriter_unknown_provider_fallback():
    os.environ['AI_PROVIDER'] = 'inconnu'
    writer = AIWriter()
    assert writer.provider.__class__.__name__ == 'StubProvider'


def test_aiwriter_generates_string():
    os.environ['AI_PROVIDER'] = 'stub'
    writer = AIWriter()
    result = writer.generate_content({'type': 'add_comment'})
    assert isinstance(result, str)
    assert result
