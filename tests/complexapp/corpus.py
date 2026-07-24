ARABIC_WORDS = [
    "المكتبة", "الوثائق", "استعادة", "النسخ", "الاحتياطي", "البيانات", "قاعدة",
    "التشفير", "السلامة", "الفهرس", "المجلد", "السلسلة", "الناشر", "الفرع",
    "الموظف", "الكاتب", "المراجعة", "التحقق", "الاسترجاع", "الملفات", "معلومة",
    "تقنية", "بحث", "تطوير", "جودة", "أمان", "سرية", "شبكة", "خادم", "تخزين",
]

ARABIC_DIACRITIC_WORDS = [
    "مُقَدِّمَةٌ", "كِتَابٌ", "تَجْرِبَةٌ", "مَعْرِفَةٌ", "حِمَايَةٌ",
    "سَلَامَةٌ", "نُسْخَةٌ", "مُسْتَنَدٌ", "مَحْفُوظَاتٌ", "اِسْتِعَادَةٌ",
]

ARABIC_FIRST_NAMES = [
    "أحمد", "فاطمة", "محمد", "عائشة", "خالد", "مريم",
    "سلمان", "نورة", "يوسف", "ليلى", "عبدالله", "هند",
]

ARABIC_LAST_NAMES = [
    "الهاشمي", "البلوشي", "الزهراني", "العامري",
    "الشامسي", "المعمري", "الكندي", "الرواحي",
]

ENGLISH_WORDS = [
    "library", "document", "restore", "backup", "container", "payload", "cipher",
    "integrity", "index", "volume", "series", "publisher", "branch", "employee",
    "writer", "review", "parity", "validate", "recover", "archive", "resilient",
    "durable", "checksum", "registry", "snapshot", "manifest", "envelope",
    "redundant", "healing", "storage",
]

ENGLISH_FIRST_NAMES = [
    "Ada", "Grace", "Alan", "Edsger", "Barbara", "Donald",
    "Radia", "Vint", "Margaret", "Dennis", "Ken", "Frances",
]

ENGLISH_LAST_NAMES = [
    "Lovelace", "Hopper", "Turing", "Dijkstra", "Liskov", "Knuth",
    "Perlman", "Cerf", "Hamilton", "Ritchie", "Thompson", "Allen",
]

EMOJI = ["📚", "🔐", "🗄️", "✅", "🌍", "💾", "🧭", "🪶"]

ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"

ROLES = ["محرر", "مدقق", "translator", "reviewer"]


def arabic_word(rng):
    source = ARABIC_WORDS if rng.random() < 0.8 else ARABIC_DIACRITIC_WORDS
    return rng.choice(source)


def arabic_sentence(rng, words=6):
    return " ".join(arabic_word(rng) for _ in range(words)) + "."


def english_sentence(rng, words=6):
    return " ".join(rng.choice(ENGLISH_WORDS) for _ in range(words)).capitalize() + "."


def arabic_name(rng):
    return f"{rng.choice(ARABIC_FIRST_NAMES)} {rng.choice(ARABIC_LAST_NAMES)}"


def english_name(rng):
    return f"{rng.choice(ENGLISH_FIRST_NAMES)} {rng.choice(ENGLISH_LAST_NAMES)}"


def arabic_digits(rng, count=4):
    return "".join(rng.choice(ARABIC_DIGITS) for _ in range(count))


def to_arabic_digits(number):
    return "".join(ARABIC_DIGITS[int(digit)] for digit in str(number))


def mixed_direction(rng):
    return (
        f"{arabic_sentence(rng, 3)} {rng.choice(ENGLISH_WORDS)} "
        f"{rng.randrange(1000)} {arabic_digits(rng)} {rng.choice(EMOJI)}"
    )


def bilingual_paragraph(rng, sentences=3):
    parts = []
    for _ in range(sentences):
        if rng.random() < 0.5:
            parts.append(arabic_sentence(rng, rng.randrange(4, 9)))
        else:
            parts.append(english_sentence(rng, rng.randrange(4, 9)))
    return " ".join(parts)


def bilingual_json(rng, depth=2):
    document = {
        "العنوان": arabic_sentence(rng, 3),
        "title": english_sentence(rng, 3),
        "وسوم": [arabic_word(rng) for _ in range(3)],
        "count": rng.randrange(1000),
        "نشط": rng.random() < 0.5,
        "note": mixed_direction(rng),
        "فارغ": None,
    }
    if depth > 1:
        document["تفاصيل"] = bilingual_json(rng, depth - 1)
    return document
