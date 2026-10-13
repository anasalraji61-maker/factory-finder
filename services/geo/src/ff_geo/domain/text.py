import re
import unicodedata

_DIACRITICS = re.compile("[ً-ٰٟۖ-ۭ]")
_MAP = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه", "ـ": None})


def normalize(text: str) -> str:
    """Normalize Arabic/Latin text for search: strip diacritics & tatweel, unify alef/ya/ta-marbuta."""
    t = unicodedata.normalize("NFKC", text).strip().lower()
    t = _DIACRITICS.sub("", t)
    t = t.translate(_MAP)
    return re.sub(r"\s+", " ", t)
