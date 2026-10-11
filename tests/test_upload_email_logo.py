"""`upload_email_logo`: sube el PNG del logo al bucket con el nombre que usa
el layout de los correos."""
import pytest
from django.core.management import CommandError, call_command

from apps.integrations.exceptions import ProviderNotConfigured
from tests.fakes import SPACES, install_spaces


def test_uploads_the_logo_with_the_key_of_the_email_layout(monkeypatch, settings, capsys):
    spaces = install_spaces(monkeypatch)

    call_command("upload_email_logo")

    (key,) = spaces.objects
    assert key == settings.EMAIL_LOGO_KEY
    stored = spaces.objects[key]
    assert stored["content_type"] == "image/png"
    assert stored["content"].startswith(b"\x89PNG")
    assert f"https://cdn.test/{key}" in capsys.readouterr().out


def test_without_storage_keys_it_fails_with_the_reason(monkeypatch):
    def _missing(**kwargs):
        raise ProviderNotConfigured("SPACES_KEY not set")

    monkeypatch.setattr(f"{SPACES}.upload", _missing)

    with pytest.raises(CommandError, match="SPACES_KEY"):
        call_command("upload_email_logo")
