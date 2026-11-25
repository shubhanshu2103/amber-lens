"""Field names that perception emits in ReadField.name.

These are the shared keys for records (Submittal.ratings) and verdict checks. Values are always
copied exactly as printed, with whitespace collapsed; unit and alias normalisation happens in records.
"""

from __future__ import annotations

# Fields labels.csv carries; the reader spike (#8) read exactly these.
LABELLED_FIELDS: tuple[str, ...] = (
    "model_number",
    "voltage",
    "rated_current",
    "power",
    "frequency",
    "manufacturer",
)

# Fields the nameplate reader emits. Each identifier is read under its own printed label:
# model_number under MODEL / MOD / TYPE, catalog_number under CAT. NO. / CATALOG / ORD. NO.
NAMEPLATE_FIELDS: tuple[str, ...] = (
    "model_number",
    "catalog_number",
    "voltage",
    "rated_current",
    "power",
    "frequency",
    "manufacturer",
)

# Product identifiers; a labels.csv model_number matches either one.
IDENTIFIER_FIELDS: tuple[str, ...] = ("catalog_number", "model_number")

# The model number plus the two key ratings.
KEY_FIELDS: tuple[str, ...] = ("model_number", "voltage", "rated_current")
