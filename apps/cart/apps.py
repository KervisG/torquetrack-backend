from django.apps import AppConfig


def _merge_guest_cart(sender, request, user, **kwargs):
    """Todo `login()` (login, activación del portal, `force_login`) fusiona el
    carrito invitado de la sesión con el de la cuenta."""
    from apps.cart.services import merge_session_cart

    session = getattr(request, "session", None)
    if session is not None:
        merge_session_cart(user, session)


class CartConfig(AppConfig):
    name = "apps.cart"

    def ready(self):
        # Una señal y no una llamada desde `apps.authentication`: así la
        # dependencia va de `cart` hacia la autenticación de Django y
        # `authentication` no conoce el carrito.
        from django.contrib.auth.signals import user_logged_in

        from apps.cart.docs import extensions  # noqa: F401

        user_logged_in.connect(_merge_guest_cart, dispatch_uid="cart_merge_guest_cart")
