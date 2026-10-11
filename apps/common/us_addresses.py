"""Única lista de estados de EE. UU. a los que envía la tienda y la forma
válida del ZIP. La usan el checkout, la estimación de impuestos, la dirección
de una cotización y el perfil del cliente; el SPA tiene su espejo en
`src/lib/us-states.ts`.

Entran los 50 estados, DC y los cinco territorios habitados (EasyPost cotiza
con USPS los códigos postales de todos ellos). Quedan fuera los militares
(`AA`, `AE`, `AP`) y los estados libremente asociados (`FM`, `MH`, `PW`):
UPS y FedEx no entregan allí. Solo se aceptan códigos: un nombre como
"Florida" se rechaza en lugar de mapearse, así hay una sola forma canónica.

El paquete va al ZIP, así que el ZIP manda: un ZIP de otro estado se rechaza
(con un ZIP de FL y estado "GA" se esquivaría el impuesto de FL).
"""
from __future__ import annotations

import re

US_STATE_CODES = frozenset(
    {
        "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
        "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
        "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
        "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
        "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
        "DC", "PR", "VI", "GU", "AS", "MP",
    }
)

SHIPPING_STATE_REQUIRED = "Shipping state is required"
INVALID_SHIPPING_STATE = "Shipping state must be a valid 2-letter US state code"
INVALID_SHIPPING_ZIP = "Shipping ZIP must be 5 digits or ZIP+4"
UNKNOWN_SHIPPING_ZIP = "ZIP code is not a valid US ZIP code."
ZIP_STATE_MISMATCH = "ZIP code does not match the selected state."

_ZIP_CODE = re.compile(r"\d{5}(-\d{4})?")


def normalize_state_code(value) -> str | None:
    """El código en mayúsculas, o `None` si no es un estado de la lista."""
    if not isinstance(value, str):
        return None
    code = value.strip().upper()
    return code if code in US_STATE_CODES else None


def is_valid_zip(value) -> bool:
    """Solo texto: un ZIP numérico perdería los ceros a la izquierda."""
    return isinstance(value, str) and _ZIP_CODE.fullmatch(value) is not None


def shipping_state_error(value) -> str | None:
    """Mensaje para el cliente si el estado de envío falta o no es válido."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return SHIPPING_STATE_REQUIRED
    return None if normalize_state_code(value) else INVALID_SHIPPING_STATE


# Prefijo de 3 dígitos -> estado, como rangos `(primero, último, estado)`.
# Fuentes (consultadas el 2026-10-01):
# - Prefijos asignados: USPS L002 "3-Digit ZIP Code Prefix Matrix", vigente
#   desde 2026-10-01, https://fast.usps.com/fast/fastApp/resources/labelListFiles.action
#   Un prefijo fuera de L002 no está asignado. La etiqueta de L002 nombra la
#   planta que procesa (010-012 dicen "HARTFORD CT"), no el estado de destino,
#   así que el estado no sale de ahí.
# - Estado de cada ZIP: USPS ZIP Locale Detail (2026-09),
#   https://postalpro.usps.com/ZIP_Locale_Detail, contrastado ZIP por ZIP con
#   GeoNames (CC BY 4.0), https://download.geonames.org/export/zip/ (US, PR,
#   VI, GU, AS, MP). Las dos fuentes coinciden en el estado mayoritario de
#   todos los prefijos; 889 (Las Vegas) solo figura en GeoNames y en L002.
# Quedan afuera los prefijos militares de L002 (090-099 AE, 340 AA, 962-966 AP).
_ZIP_PREFIX_RANGES = (
    (5, 5, "NY"), (6, 7, "PR"), (8, 8, "VI"), (9, 9, "PR"), (10, 27, "MA"), (28, 29, "RI"),
    (30, 38, "NH"), (39, 49, "ME"), (50, 54, "VT"), (55, 55, "MA"), (56, 59, "VT"),
    (60, 69, "CT"), (70, 89, "NJ"), (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"),
    (200, 200, "DC"), (201, 201, "VA"), (202, 205, "DC"), (206, 212, "MD"), (214, 219, "MD"),
    (220, 246, "VA"), (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"),
    (320, 339, "FL"), (341, 342, "FL"), (344, 344, "FL"), (346, 347, "FL"), (349, 349, "FL"),
    (350, 352, "AL"), (354, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"),
    (400, 418, "KY"), (420, 427, "KY"), (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"),
    (500, 516, "IA"), (520, 528, "IA"), (530, 532, "WI"), (534, 535, "WI"), (537, 549, "WI"),
    (550, 551, "MN"), (553, 567, "MN"), (570, 577, "SD"), (580, 588, "ND"), (590, 599, "MT"),
    (600, 620, "IL"), (622, 629, "IL"), (630, 631, "MO"), (633, 641, "MO"), (644, 658, "MO"),
    (660, 662, "KS"), (664, 679, "KS"), (680, 681, "NE"), (683, 693, "NE"), (700, 701, "LA"),
    (703, 708, "LA"), (710, 714, "LA"), (716, 729, "AR"), (730, 731, "OK"), (733, 733, "TX"),
    (734, 741, "OK"), (743, 749, "OK"), (750, 770, "TX"), (772, 799, "TX"), (800, 816, "CO"),
    (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 853, "AZ"), (855, 857, "AZ"),
    (859, 860, "AZ"), (863, 865, "AZ"), (870, 871, "NM"), (873, 884, "NM"), (885, 885, "TX"),
    (889, 891, "NV"), (893, 895, "NV"), (897, 898, "NV"), (900, 908, "CA"), (910, 928, "CA"),
    (930, 961, "CA"), (967, 968, "HI"), (969, 969, "GU"), (970, 979, "OR"), (980, 986, "WA"),
    (988, 994, "WA"), (995, 999, "AK"),
)

# ZIPs que no son del estado de su prefijo o que cruzan una frontera: alguna
# de las dos fuentes los ubica en otro estado. Se aceptan todos los estados
# que den las fuentes; un conjunto vacío es Palau, Micronesia o Islas
# Marshall, a donde no se envía.
ZIP_STATE_EXCEPTIONS = {
    "02914": frozenset({"MA", "RI"}), "03609": frozenset({"NH", "VT"}),
    "03902": frozenset({"ME", "NH"}), "03903": frozenset({"ME", "NH"}),
    "03904": frozenset({"ME", "NH"}), "03905": frozenset({"ME", "NH"}),
    "03909": frozenset({"ME", "NH"}), "06390": frozenset({"NY"}),
    "19964": frozenset({"DE", "MD"}), "20020": frozenset({"DC", "MD"}),
    "20041": frozenset({"DC", "VA"}), "20588": frozenset({"DC", "MD"}),
    "20598": frozenset({"DC", "VA"}), "21875": frozenset({"DE", "MD"}),
    "24131": frozenset({"VA", "WV"}), "24605": frozenset({"VA", "WV"}),
    "30750": frozenset({"GA", "TN"}), "35739": frozenset({"AL", "TN"}),
    "37316": frozenset({"GA", "TN"}), "37620": frozenset({"TN", "VA"}),
    "37621": frozenset({"TN", "VA"}), "38257": frozenset({"KY", "TN"}),
    "41025": frozenset({"KY", "OH"}), "41101": frozenset({"KY", "WV"}),
    "41102": frozenset({"KY", "WV"}), "41169": frozenset({"KY", "WV"}),
    "41503": frozenset({"KY", "WV"}), "45275": frozenset({"KY", "OH"}),
    "45390": frozenset({"IN", "OH"}), "47003": frozenset({"IN", "OH"}),
    "47010": frozenset({"IN", "OH"}), "47060": frozenset({"IN", "OH"}),
    "47110": frozenset({"IN", "KY"}), "47142": frozenset({"IN", "KY"}),
    "51510": frozenset({"IA", "NE"}), "56520": frozenset({"MN", "ND"}),
    "56721": frozenset({"MN", "ND"}), "57640": frozenset({"ND", "SD"}),
    "57650": frozenset({"ND", "SD"}), "58568": frozenset({"ND", "SD"}),
    "59319": frozenset({"MT", "SD"}), "61252": frozenset({"IA", "IL"}),
    "61285": frozenset({"IA", "IL"}), "66630": frozenset({"KS", "MO"}),
    "71854": frozenset({"AR", "TX"}), "72643": frozenset({"AR", "MO"}),
    "73960": frozenset({"OK", "TX"}), "75504": frozenset({"AR", "TX"}),
    "79821": frozenset({"NM", "TX"}), "83414": frozenset({"ID", "WY"}),
    "83822": frozenset({"ID", "WA"}), "83824": frozenset({"ID", "WA"}),
    "83870": frozenset({"ID", "WA"}), "84784": frozenset({"AZ", "UT"}),
    "86044": frozenset({"AZ", "UT"}), "96799": frozenset({"AS"}), "96939": frozenset(),
    "96940": frozenset(), "96941": frozenset(), "96942": frozenset(), "96943": frozenset(),
    "96944": frozenset(), "96950": frozenset({"MP"}), "96951": frozenset({"MP"}),
    "96952": frozenset({"MP"}), "96960": frozenset(), "96970": frozenset(),
    "97901": frozenset({"ID", "OR"}), "99403": frozenset({"ID", "WA"}),
}


_STATE_BY_PREFIX = {
    f"{prefix:03d}": state
    for first, last, state in _ZIP_PREFIX_RANGES
    for prefix in range(first, last + 1)
}


def zip_states_by_prefix() -> dict[str, str]:
    """Copia de la tabla expandida, para los tests y la documentación."""
    return dict(_STATE_BY_PREFIX)


def states_for_zip(value) -> frozenset[str]:
    """Estados de la lista a los que pertenece el ZIP (5 dígitos o ZIP+4);
    vacío si el ZIP está mal formado, sin asignar o fuera de la lista."""
    if not is_valid_zip(value):
        return frozenset()
    five = value[:5]
    if five in ZIP_STATE_EXCEPTIONS:
        return ZIP_STATE_EXCEPTIONS[five]
    state = _STATE_BY_PREFIX.get(five[:3])
    return frozenset({state}) if state else frozenset()


def shipping_zip_error(zip_code, state) -> str | None:
    """Mensaje para el cliente si el ZIP está mal formado, no existe o no es
    del estado. `state` ya tiene que haber pasado `shipping_state_error`."""
    if not is_valid_zip(zip_code):
        return INVALID_SHIPPING_ZIP
    states = states_for_zip(zip_code)
    if not states:
        return UNKNOWN_SHIPPING_ZIP
    return None if normalize_state_code(state) in states else ZIP_STATE_MISMATCH
