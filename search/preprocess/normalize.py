import re
import unicodedata

# 1. كلمات عامة (Conversational & Stop Words)
GENERAL_STOP_WORDS = {
    # English
    "a", "an", "the", "and", "or", "but", "if", "then", "else",
    "when", "where", "why", "how", "what", "which", "is", "are",
    "was", "were", "can", "could", "would", "please",

    # Arabic Prepositions & Pronouns
    "في", "علي", "على", "من", "الي", "إلى", "الى", "عن", "مع", "حتي", "حتى",
    "بعد", "قبل", "خلال", "بين", "حول", "تحت", "فوق", "امام", "خلف", "داخل", "خارج",
    "او", "ثم", "كما", "هل", "لو", "اذا", "هذا", "هذه", "ذلك", "تلك",
    "هو", "هي", "هم", "انا", "انت", "انتي", "احنا", "نحن",

    # Egyptian dialect
    "عايز", "عايزه", "عايزين", "عاوز", "عاوزه", "عاوزين", "محتاج", "محتاجه", "محتاجين",
    "ممكن", "سمحت", "لوسمحت", "لو", "بعداذنك", "نفسي", "حابب", "حابه", "حابين", "ياريت",
    "فين", "عندكم", "عندكو", "عندكوا", "فيه", "فيها", "فيهم", "اي", "ايه", "ايش",
    "ده", "دي", "دول", "بقي", "بقا", "كده", "كدا", "بس", "كمان", "برضو", "بردو",
    "خالص", "اوي", "قوي", "تمام", "تماما", "ماشي", "اوكي", "اوك", "بتاع", "بتاعة", "بتاعت",
}

# 2. كلمات المجال الطبي والمخبري التي تسبب تشويش في الاسكور (Domain-Specific Noise Words)
MEDICAL_STOP_WORDS = {
    # عربي (بكل أشكال المفرد والجمع والتعريف)
    "تحليل", "التحليل", "تحاليل", "التحاليل", "تحليلات",
    "فحص", "الفحص", "فحوصات", "الفحوصات", "فحوص", "الفحوص",
    "اختبار", "الاختبار", "اختبارات", "الاختبارات",
    "كشف", "الكشف", "كشوفات", "اشعه", "اشعة", "الاشعة", "الاشعه",
    "رسم", "الرسم", "مقياس", "قياس", "معمل", "المعمل", "لاب",
    "نسبه", "نسبة", "النسبه", "النسبة", "معدل", "المعدل", "فحصين", "تحليلين",

    # English medical noise words
    "test", "tests", "testing",
    "analysis", "analyses",
    "check", "checkup", "checks",
    "exam", "examination", "examinations",
    "profile", "panel", "screen", "screening",
    "level", "levels", "count", "rate",
    "lab", "laboratory", "scan", "assay",
}

STOP_WORDS = GENERAL_STOP_WORDS | MEDICAL_STOP_WORDS

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
    Normalize user query or database candidate before fuzzy matching:
    1. lowercase
    2. remove diacritics (tashkeel)
    3. normalize Arabic letters (أ/إ/آ -> ا, ة -> ه, ى -> ي)
    4. remove punctuation
    5. strip domain noise words (تحليل, فحص, test, etc.) and general stop words
    """
    if not text:
        return ""

    # 1. Lowercase
    text = text.lower()

    # 2. Remove Tashkeel
    text = "".join(
        c
        for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

    # 3. Normalize Arabic letters
    for old, new in ARABIC_REPLACEMENTS.items():
        text = text.replace(old, new)

    # 4. Replace punctuation & special chars with spaces
    text = re.sub(r"[^\w\s]", " ", text)

    # 5. Remove duplicated spaces
    text = re.sub(r"\s+", " ", text).strip()

    # 6. Filter Stop Words & Medical Noise Words
    tokens = text.split()
    filtered_tokens = [
        token
        for token in tokens
        if token not in STOP_WORDS
    ]

    # حماية: إذا كان نص البحث بالكامل عبارة عن كلمة stop word فقط (مثلاً العميل كتب "تحليل")
    # نرجع التوكنز الأصلية عشان النص ميبقاش فاضي تماماً
    if not filtered_tokens and tokens:
        return " ".join(tokens)

    return " ".join(filtered_tokens)