"""RED/GREEN evidence for the dual admin/customer session cookies (design
decision #5, task 3.2) — mirrors `lib/auth.ts`'s `tt_admin` / `tt_customer`
cookies: httpOnly, sameSite=lax, secure-in-prod, 7-day expiry, and expired
tokens treated as unauthenticated.
"""
import pytest
from django.contrib.sessions.models import Session
from django.http import HttpResponse
from django.test import RequestFactory, override_settings
from django.utils import timezone

from apps.accounts.sessions import AdminSessionMiddleware, CustomerSessionMiddleware

pytestmark = pytest.mark.django_db

SEVEN_DAYS_SECONDS = 7 * 24 * 60 * 60


def _request_with_cookie(cookie_name=None, cookie_value=None):
    request = RequestFactory().get("/")
    request.COOKIES = {cookie_name: cookie_value} if cookie_name else {}
    return request


def _run_writing(middleware_cls, session_attr, request):
    def get_response(req):
        getattr(req, session_attr)["probe"] = True
        return HttpResponse("ok")

    middleware = middleware_cls(get_response=get_response)
    return middleware(request)


def test_admin_session_sets_only_the_tt_admin_cookie():
    response = _run_writing(
        AdminSessionMiddleware, "admin_session", _request_with_cookie()
    )

    assert "tt_admin" in response.cookies
    assert "tt_customer" not in response.cookies


def test_customer_session_sets_only_the_tt_customer_cookie():
    response = _run_writing(
        CustomerSessionMiddleware, "customer_session", _request_with_cookie()
    )

    assert "tt_customer" in response.cookies
    assert "tt_admin" not in response.cookies


def test_admin_cookie_is_httponly_and_samesite_lax():
    response = _run_writing(
        AdminSessionMiddleware, "admin_session", _request_with_cookie()
    )

    cookie = response.cookies["tt_admin"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


@override_settings(DEBUG=True)
def test_admin_cookie_is_not_secure_when_debug_is_true():
    # pytest-django forces DEBUG=False for the whole test session by
    # default regardless of the active settings module (confirmed: even
    # though pytest.ini points DJANGO_SETTINGS_MODULE at config.settings.dev,
    # which sets DEBUG = True, `settings.DEBUG` reads False under pytest
    # unless explicitly overridden here) — so DEBUG must be forced
    # explicitly to exercise this branch.
    response = _run_writing(
        AdminSessionMiddleware, "admin_session", _request_with_cookie()
    )

    cookie = response.cookies["tt_admin"]
    assert cookie["secure"] == ""


@override_settings(DEBUG=False)
def test_admin_cookie_is_secure_when_debug_is_false():
    response = _run_writing(
        AdminSessionMiddleware, "admin_session", _request_with_cookie()
    )

    cookie = response.cookies["tt_admin"]
    assert cookie["secure"] is True


def test_admin_session_max_age_is_seven_days():
    response = _run_writing(
        AdminSessionMiddleware, "admin_session", _request_with_cookie()
    )

    cookie = response.cookies["tt_admin"]
    assert int(cookie["max-age"]) == SEVEN_DAYS_SECONDS


def test_expired_admin_session_is_treated_as_unauthenticated():
    session_key = "expiredsessionkey1234567890abcd"
    Session.objects.create(
        session_key=session_key,
        session_data="",
        expire_date=timezone.now() - timezone.timedelta(days=1),
    )
    captured = {}

    def get_response(req):
        # `.get()` triggers the lazy DB lookup (and, for an expired key,
        # resets `_session_key` to None) — `is_empty()` alone does NOT
        # trigger that lookup and would give a false negative if checked
        # first, before any read. Read data before asserting emptiness.
        captured["probe"] = req.admin_session.get("probe")
        captured["is_empty"] = req.admin_session.is_empty()
        return HttpResponse("ok")

    request = _request_with_cookie("tt_admin", session_key)
    middleware = AdminSessionMiddleware(get_response=get_response)
    middleware(request)

    assert captured["probe"] is None
    assert captured["is_empty"] is True


def test_admin_and_customer_sessions_are_independent_in_the_same_request():
    """Proves the two middlewares don't clobber each other's request
    attribute or cookie when both run chained in the same request/response
    cycle, the way `MIDDLEWARE` actually chains them."""

    def inner_get_response(req):
        req.admin_session["role"] = "admin"
        req.customer_session["role"] = "customer"
        return HttpResponse("ok")

    customer_mw = CustomerSessionMiddleware(get_response=inner_get_response)
    admin_mw = AdminSessionMiddleware(get_response=customer_mw)

    response = admin_mw(_request_with_cookie())

    assert "tt_admin" in response.cookies
    assert "tt_customer" in response.cookies
    assert response.cookies["tt_admin"].value != response.cookies["tt_customer"].value
