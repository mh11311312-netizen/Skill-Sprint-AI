"""Small, deterministic text helpers shared by the Python pipelines (no AI involved)."""
import re
from collections import Counter
from math import sqrt

STOPWORDS = set("""a an the and or of to in on for with by at from as is are be been being this that these those
it its their they them you your we our all any each every per into than then there here which who whom
must shall should may can will would not no only also more most less least up out over under about
employee employees staff new joiner joiners within before after during""".split())

# Words that appear in almost every onboarding clause; ignored when comparing topics
FILLER = set("""complete completed module modules day days week first joining training required
approval approved ensure use using""".split())


def normalize_word(w):
    w = w.lower()
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokens(text, drop_filler=False):
    words = [normalize_word(w) for w in re.findall(r"[A-Za-z]+", text or "")]
    out = [w for w in words if w not in STOPWORDS and len(w) > 1]
    if drop_filler:
        out = [w for w in out if w not in FILLER]
    return out


def cosine(a, b, drop_filler=False):
    ta, tb = Counter(tokens(a, drop_filler)), Counter(tokens(b, drop_filler))
    if not ta or not tb:
        return 0.0
    dot = sum(ta[k] * tb[k] for k in ta if k in tb)
    return dot / (sqrt(sum(v * v for v in ta.values())) * sqrt(sum(v * v for v in tb.values())))


def numbers(text):
    """Returns the set of numbers in a text: '9:00 AM', 'PKR 1,500,000', '14 days' -> {'9:00','1500000','14'}."""
    found = re.findall(r"\d+(?::\d+)?(?:[.,]\d+)*%?", text or "")
    return {n.replace(",", "") for n in found}


NEGATIVE = re.compile(r"\b(must not|shall not|not|no longer|without|cannot|prohibited|exempt|never)\b", re.I)


def is_negative(text):
    return bool(NEGATIVE.search(text or ""))


def version_number(v):
    try:
        return float(str(v).strip().lstrip("vV"))
    except ValueError:
        return 0.0
