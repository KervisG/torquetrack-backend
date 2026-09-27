"""Solo `apps/checkout/services/payments.py` abre, registra o expira pagos de Stripe:
así el monto, su redondeo y el `provider_id` que concilia el webhook salen de
un único lugar."""
import ast
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
APPS_DIR = BACKEND_DIR / "apps"
INTEGRATIONS_DIR = APPS_DIR / "integrations"
OWNER = APPS_DIR / "checkout" / "services" / "payments.py"


def _domain_modules():
    for path in APPS_DIR.rglob("*.py"):
        parts = path.relative_to(APPS_DIR).parts
        if {"tests", "migrations", "__pycache__"} & set(parts):
            continue
        if path.is_relative_to(INTEGRATIONS_DIR):
            continue
        yield path


def _attribute_calls(path):
    """Devuelve el texto de cada llamada `a.b(...)`/`a.b.c(...)` del módulo."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            yield ast.unparse(node.func)


def test_only_checkout_services_opens_stripe_sessions_or_creates_payments():
    offenders = []
    for path in _domain_modules():
        if path == OWNER:
            continue
        for call in _attribute_calls(path):
            if call.endswith(".create_checkout_session") or call == "Payment.objects.create":
                offenders.append(f"{path.relative_to(BACKEND_DIR).as_posix()}: {call}")

    assert offenders == []


def test_checkout_services_still_owns_both_operations():
    calls = set(_attribute_calls(OWNER))

    assert "stripe_payments.create_checkout_session" in calls
    assert "Payment.objects.create" in calls


def _status_bulk_updates(path):
    """Llamadas `Payment.objects....update(status=...)` del módulo."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        func = ast.unparse(node.func)
        if (
            func.startswith("Payment.objects")
            and func.endswith(".update")
            and any(keyword.arg == "status" for keyword in node.keywords)
        ):
            yield func


def test_pending_payments_are_cancelled_only_through_cancel_pending_payment():
    # Un `update(status=...)` masivo cancelaría el pago sin expirar su
    # Checkout Session, y el cliente podría seguir pagándola.
    offenders = []
    for path in _domain_modules():
        relative = path.relative_to(BACKEND_DIR).as_posix()
        offenders.extend(f"{relative}: {call}" for call in _status_bulk_updates(path))
        if path != OWNER:
            offenders.extend(
                f"{relative}: {call}"
                for call in _attribute_calls(path)
                if call.endswith(".expire_checkout_session")
            )

    assert offenders == []
    assert "stripe_payments.expire_checkout_session" in set(_attribute_calls(OWNER))
