"""Las demás apps solo usan `record_activity`; `list_activity_page` es de la
view del panel de esta app."""
from apps.audit.services.listing import list_activity_page
from apps.audit.services.recording import record_activity

__all__ = ["list_activity_page", "record_activity"]
