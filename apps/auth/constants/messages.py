# --- errores ---

# views.py, docs/examples.py
INCORRECT_CREDENTIALS = "Incorrect email or password"
UNAUTHORIZED = "Unauthorized"

# services/credentials.py, customers/services/storefront.py
EMAIL_ALREADY_EXISTS = "Email already exists"

# services/password_reset.py, docs/examples.py
INVALID_RESET_LINK = "Invalid or expired reset link"
PASSWORD_REQUIRED = "Password required"

# --- éxitos ---

# views.py, docs/extensions.py
LOGGED_OUT = "Logged out"

# services/password_reset.py, docs/extensions.py
PASSWORD_UPDATED = "Password updated"

# services/email_verification.py, docs/extensions.py
VERIFICATION_EMAIL_SENT = "Verification email sent"
EMAIL_ALREADY_VERIFIED = "Email already verified"

# services/password_reset.py, docs/extensions.py
PASSWORD_RESET_SENT = (
    "If an account exists for that email, we sent a link to reset the password."
)
