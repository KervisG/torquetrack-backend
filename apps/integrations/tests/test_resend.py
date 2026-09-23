import pytest
import requests

from apps.integrations.email import resend
from apps.integrations.tests.support import FakeResponse, RecordingPost


@pytest.fixture
def configured(settings):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = "TorqueTrack <no-reply@example.com>"
    return settings


def test_is_configured_needs_key_and_sender(settings):
    settings.RESEND_API_KEY = "re_test_fake"
    settings.FROM_EMAIL = ""
    assert resend.is_configured() is False

    settings.FROM_EMAIL = "no-reply@example.com"
    assert resend.is_configured() is True


def test_not_configured_never_calls_the_provider(settings, monkeypatch):
    settings.RESEND_API_KEY = ""

    def _boom(*args, **kwargs):
        raise AssertionError("Resend must not be called without a key")

    monkeypatch.setattr("apps.integrations.email.resend.requests.post", _boom)

    result = resend.send_email(to="pat@example.com", subject="Hi", html="<p>Hi</p>")

    assert result == {"sent": False, "reason": "Email provider not configured"}


def test_builds_the_resend_request(configured, monkeypatch):
    post = RecordingPost(FakeResponse({"id": "email_1"}))
    monkeypatch.setattr("apps.integrations.email.resend.requests.post", post)

    result = resend.send_email(
        to="pat@example.com",
        subject="Your quote",
        html="<p>Quote</p>",
        reply_to="sales@example.com",
        attachments=[{"filename": "Q1.pdf", "content": "UERG", "contentType": "application/pdf"}],
    )

    assert result == {"sent": True, "id": "email_1"}
    call = post.calls[0]
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer re_test_fake"
    assert call["json"] == {
        "from": "TorqueTrack <no-reply@example.com>",
        "to": ["pat@example.com"],
        "subject": "Your quote",
        "html": "<p>Quote</p>",
        "reply_to": "sales@example.com",
        "attachments": [
            {"filename": "Q1.pdf", "content": "UERG", "content_type": "application/pdf"}
        ],
    }


def test_provider_error_maps_to_not_sent_with_reason(configured, monkeypatch):
    post = RecordingPost(FakeResponse({"message": "Invalid from"}, ok=False, status_code=422))
    monkeypatch.setattr("apps.integrations.email.resend.requests.post", post)

    result = resend.send_email(to=["a@example.com"], subject="s", html="h")

    assert result == {"sent": False, "reason": "Invalid from"}


def test_network_error_maps_to_not_sent(configured, monkeypatch):
    def _raise(*args, **kwargs):
        raise requests.ConnectionError("network unreachable")

    monkeypatch.setattr("apps.integrations.email.resend.requests.post", _raise)

    result = resend.send_email(to="a@example.com", subject="s", html="h")

    assert result == {"sent": False, "reason": "network unreachable"}


def test_non_json_error_body_uses_generic_reason(configured, monkeypatch):
    post = RecordingPost(FakeResponse(ok=False, status_code=500, invalid_json=True))
    monkeypatch.setattr("apps.integrations.email.resend.requests.post", post)

    result = resend.send_email(to="a@example.com", subject="s", html="h")

    assert result == {"sent": False, "reason": "Email failed"}
