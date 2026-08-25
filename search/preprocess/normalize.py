import re
import unicodedata

# Common conversational words that add no search value.
STOP_WORDS = {
    # English
    "a", "an", "the",
    "and", "or", "but",
    "if", "then", "else",
    "when", "where", "why",
    "how", "what", "which",
    "is", "are", "was", "were",
    "can", "could", "would",
    "please",

    # Arabic
    "في", "على", "من", "الى", "إلى",
    "عن", "مع", "حتى", "بعد", "قبل",
    "خلال", "بين", "حول", "تحت", "فوق",
    "امام", "أمام", "خلف", "داخل", "خارج",
    "او", "أو", "و", "ثم", "كما",
    "هل", "لو", "اذا", "إذا",
    "هذا", "هذه", "ذلك", "تلك",
    "هو", "هي", "هم", "انا", "أنا",
    "انت", "أنت", "انتي", "أنتي",
    "احنا", "نحن",

    # Egyptian dialect
    "عايز", "عايزة", "عايزين", "عايزه",
    "عاوز", "عاوزه", "عاوزين",
    "محتاج", "محتاجة", "محتاجين",
    "ممكن",
    "سمحت",
    "لوسمحت",
    "بعداذنك",
    "بعدإذنك",
    "نفسي",
    "حابب",
    "حابه",
    "حابين",
    "ياريت",
    "فين",
    "عندكم",
    "عندكو",
    "عندكوا",
    "فيه",
    "فيها",
    "فيهم",
    "اي",
    "إيه",
    "ايه",
    "ايش",
    "ده",
    "دى",
    "دي",
    "دول",
    "بقى",
    "بقا",
    "كده",
    "كدا",
    "بس",
    "كمان",
    "برضو",
    "بردو",
    "خالص",
    "اوي",
    "قوي",
    "تمام",
    "تماما",
    "ماشي",
    "اوكي",
    "اوك",
}

ARABIC_REPLACEMENTS = {
    "أ": "ا",
    "إ": "ا",
    "آ": "ا",
    "ٱ": "ا",
    "ى": "ي",
    "ة": "ه",
    "ؤ": "و",
    "ئ": "ي",
}


def normalize(text: str) -> str:
    """
    Normalize user text before searching.

    Steps:
    1. lowercase
    2. remove Arabic diacritics
    3. normalize Arabic letters
    4. remove punctuation
    5. collapse spaces
    6. remove stop words
    """

    if not text:
        return ""

    # lowercase
    text = text.lower()

    # remove tashkeel
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

    # normalize Arabic letters
    for old, new in ARABIC_REPLACEMENTS.items():
        text = text.replace(old, new)

    # replace punctuation with spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # remove duplicated spaces
    text = re.sub(r"\s+", " ", text).strip()

    # remove stop words
    tokens = [
        token
        for token in text.split()
        if token not in STOP_WORDS
    ]

    return " ".join(tokens)