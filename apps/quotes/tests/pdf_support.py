"""Sin las librerías nativas (Pango, Cairo) el import de WeasyPrint lanza
`OSError`, no `ImportError`, así que `importorskip` no alcanza."""

import pytest


def _weasyprint_native_libs_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True


requires_weasyprint = pytest.mark.skipif(
    not _weasyprint_native_libs_available(),
    reason="WeasyPrint native libraries (GTK/Pango) are not installed",
)
