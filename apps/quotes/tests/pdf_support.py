"""Guard compartido por los tests que renderizan el PDF con WeasyPrint.

WeasyPrint se instala desde pip, pero al importarse carga con `cffi` las
librerías nativas de GTK (gobject, Pango, Cairo). En Windows sin un runtime
GTK3 el import lanza `OSError`, no `ImportError`, así que `importorskip` no
alcanza. Estos tests se saltan solo en ese caso y siguen corriendo en el
contenedor Linux de `backend/Dockerfile`, que sí trae las librerías.
"""

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
