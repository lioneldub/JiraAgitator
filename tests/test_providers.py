import pytest

# Skip automatiquement si les packages optionnels sont absents
genai = pytest.importorskip(
    "google.generativeai",
    reason="google-generativeai non installé — tests Gemini ignorés"
)
groq_pkg = pytest.importorskip(
    "groq",
    reason="groq non installé — tests Groq ignorés"
)

from providers.stub_provider import StubProvider


def test_stub_provider_covers_all_types():
    provider = StubProvider()
    assert provider.generate({'type': 'add_comment'})
    assert provider.generate({'type': 'nonexistent'})


def test_gemini_provider_interface():
    from providers.gemini_provider import GeminiProvider
    provider = GeminiProvider
    assert hasattr(provider, 'generate')
    assert hasattr(provider, '_describe_event_type')


def test_groq_provider_interface():
    from providers.groq_provider import GroqProvider
    provider = GroqProvider
    assert hasattr(provider, 'generate')
    assert hasattr(provider, '_describe_event_type')
