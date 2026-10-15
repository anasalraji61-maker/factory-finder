import re
import unicodedata

_MAP = str.maketrans(
    {
        "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",  # alef variants
        "ى": "ي", "ی": "ي", "ې": "ي",  # alef maqsura / Persian ya
        "ة": "ه",  # ta marbuta
        "ک": "ك",  # Persian kaf
        "ـ": None,  # tatweel
        "'": None, "’": None, "`": None, "ʻ": None,  # apostrophes: Xi'an == Xian
        "-": " ", "_": " ", ".": " ", ",": " ", "،": " ",
        "ß": "ss", "ø": "o", "ł": "l", "đ": "d", "æ": "ae", "œ": "oe", "ı": "i",
    }
)
_SPACES = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Normalize Arabic/Latin text for search.

    Strips Arabic diacritics/tatweel and Latin accents, unifies alef/ya/ta-marbuta (+ Persian ya/kaf),
    drops apostrophes and turns hyphens/underscores/dots into spaces.
    """
    t = unicodedata.normalize("NFKD", text).lower()
    t = "".join(ch for ch in t if not unicodedata.category(ch).startswith("M"))
    t = t.translate(_MAP)
    return _SPACES.sub(" ", t).strip()
