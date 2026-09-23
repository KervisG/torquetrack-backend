"""`run_in_background` de `apps/auth/utils/background.py`.

Es lo que saca los correos de cuenta del request. No hay worker asíncrono,
así que corre en un hilo daemon: un fallo ahí no le llega a nadie más que al
log, y estos tests fijan que quede registrado.
"""
import logging
import threading

from apps.auth.utils.background import run_in_background


def test_runs_the_function_in_another_thread():
    ran_in = []

    thread = run_in_background(lambda value: ran_in.append((threading.get_ident(), value)), 7)
    thread.join(5)

    assert ran_in and ran_in[0][1] == 7
    assert ran_in[0][0] != threading.get_ident()
    assert thread.daemon is True


def test_logs_an_exception_raised_by_the_function(caplog):
    def _fail():
        raise RuntimeError("provider exploded")

    with caplog.at_level(logging.ERROR, logger="apps.auth.utils.background"):
        run_in_background(_fail).join(5)

    assert "provider exploded" in caplog.text
