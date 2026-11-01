"""Text helpers for the script tool: Arabic normalisation, numbers, word runs for the copy check.

Numbers: digits (Latin or Arabic-Indic, with "," / "٬" thousands and "." / "٫" decimals) are read with the scale word
that follows them (ألف/مليون/مليار/تريليون, thousand/million/billion/trillion, k/m/bn), so "1.25 تريليون" and
"1250 مليار" and "$1.25 trillion" are the same value. Numbers spelled as words («عشر سنين», «نص تريليون») are not
read as values; a line that has them is warned, not passed silently.
"""
import re
import unicodedata

from ..cut.common import normalize_ar

AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
SCALES = {"ألف": 1e3, "الف": 1e3, "آلاف": 1e3, "الاف": 1e3, "thousand": 1e3, "k": 1e3,
          "مليون": 1e6, "ملايين": 1e6, "million": 1e6, "millions": 1e6, "m": 1e6, "mn": 1e6,
          "مليار": 1e9, "مليارات": 1e9, "billion": 1e9, "billions": 1e9, "bn": 1e9, "b": 1e9,
          "تريليون": 1e12, "تريليونات": 1e12, "trillion": 1e12, "trillions": 1e12, "tn": 1e12}
NUM = re.compile(r"(?<![0-9A-Za-z.٫])(\d{1,3}(?:[,٬]\d{3})+|\d+)(?:[.٫](\d+))?(?:\s*(%|٪|في المية|في المائة|بالمئة|بالمائة|percent))?"
                 r"(?:\s*-?\s*(ألف|الف|آلاف|الاف|مليون|ملايين|مليار|مليارات|تريليون|تريليونات|thousand|millions?|billions?|"
                 r"trillions?|k|mn?|bn|b|tn)(?![\w]))?", re.I)
SPELLED = re.compile(r"(?<!\w)(?:و|ب|ل|وال|بال|لل|ال)?(واحد|اتنين|اثنين|تلات|ثلاث|اربع|أربع|خمس|ست|سبع|تمان|ثمان|تسع|عشر|عشرين|تلاتين|ثلاثين|"
                     r"اربعين|أربعين|خمسين|ستين|سبعين|تمانين|ثمانين|تسعين|مية|مائة|مئة|ميتين|ألف|الف|مليون|مليار|تريليون|نص|ربع)"
                     r"(?:ة|ات|ه)?(?!\w)")


def nfkc(text):
    """undo Arabic "presentation forms" (project 4's script stores them) and other compatibility characters"""
    return unicodedata.normalize("NFKC", text or "")


def norm(text):
    """the normalisation every comparison uses (diacritics, alef forms, punctuation, digits)"""
    return normalize_ar(nfkc(text).translate(AR_DIGITS))


def words(text):
    return norm(text).split()


def numbers(text):
    """[{raw, value, scaled, percent}] for every digit number in the text"""
    t = nfkc(text).translate(AR_DIGITS)
    out = []
    for m in NUM.finditer(t):
        whole = m.group(1).replace(",", "").replace("٬", "")
        v = float(whole + ("." + m.group(2) if m.group(2) else ""))
        scale = SCALES.get((m.group(4) or "").lower(), 1)
        out.append({"raw": m.group(0).strip(), "value": v, "scaled": v * scale, "percent": bool(m.group(3)),
                    "decimals": len(m.group(2) or ""), "scale": scale})
    return out


def same_number(a, b):
    """a (as written in our text) says the same as b (in the source): equal as written, equal after their scale words,
    or b rounded to a's decimals (13.5492 -> "13.5", 53.5134 -> "53.51"; never the other way round)"""
    def eq(x, y):
        return abs(x - y) <= 1e-9 * max(1, abs(x), abs(y))
    if eq(a["value"], b["value"]) or eq(a["scaled"], b["scaled"]):
        return True
    da, db = a.get("decimals", 0), b.get("decimals", 0)
    return da < db and eq(a["value"], round(b["value"], da)) and a.get("scale", 1) == b.get("scale", 1)


def number_found(n, pool):
    return any(same_number(n, m) for m in pool)


ONE_NOT_NUMBER = {"كل", "ولا", "اي", "أي", "حد"}             # «كل واحد», «ولا واحد»: someone, not a count
SCALE_AFTER = re.compile(r"^(?:ال)?(?:ألف|الف|آلاف|الاف|مليون|ملايين|مليار|مليارات|تريليون|تريليونات|مية|مائة|مئة|\d)")


def spelled_numbers(text):
    """number words not attached to digits ("عشر سنين", "نص تريليون"); scale words after digits are not counted. Not
    numbers (owner, 20 Oct 2026): «واحد» after «كل» / «ولا» / «أي» / «حد» or before «من» («واحد من أهم»), and «نص» / «ربع»
    unless an amount follows («نص تريليون»; «نص الصورة» is not a figure)"""
    t = NUM.sub(" ", nfkc(text).translate(AR_DIGITS))
    out = []
    for m in SPELLED.finditer(t):
        before, after = t[:m.start()].split()[-1:], t[m.end():].split()[:1]
        w = m.group(1)
        if w == "واحد" and ((before and before[0] in ONE_NOT_NUMBER) or (after and after[0].startswith("من"))):
            continue
        if w in ("نص", "ربع") and not (after and SCALE_AFTER.match(after[0])):
            continue
        out.append(m.group(0))
    return out


# Fixed phrases (report decision 4b): a price line has no other wording — «53.42 جنيه للشراء و53.52 جنيه للبيع», «عيار 21
# 6205 جنيه» — so a 6-word run made ONLY of numbers and these words (normalised forms), with at least two numbers, is not
# counted as copying. Everything else stays strict.
FIXED_WORDS = set("""جنيه جنيها جنيهات الجنيه دولار دولارا دولارات الدولار يورو اليورو ريال الريال درهم الدرهم قرش قرشا قروش
للشراء للبيع شراء بيع الشراء البيع والشراء والبيع وللشراء وللبيع سعر وسعر عيار جرام الجرام للجرام اوقيه الاوقيه للاوقيه اونصه الاونصه للاونصه الذهب
و مقابل عند الي من في egp usd eur buy sell""".split())
_NUMTOK = re.compile(r"^[وبل]?\d+%?$")


def is_fixed(run):
    ws = run.split()
    nums = sum(1 for w in ws if _NUMTOK.match(w))
    return nums >= 2 and all(_NUMTOK.match(w) or w in FIXED_WORDS for w in ws)


def runs(text, n=6, skip_fixed=True):
    """every run of n consecutive normalised words (fixed price phrases left out: report decision 4b)"""
    w = words(text)
    out = {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    return {r for r in out if not is_fixed(r)} if skip_fixed else out


def shared_run(text, source_runs, n=6):
    """the first run of n words of `text` found in source_runs (a set from runs()), or None; a fixed price phrase
    (is_fixed) never counts"""
    w = words(text)
    for i in range(len(w) - n + 1):
        r = " ".join(w[i:i + n])
        if r in source_runs and not is_fixed(r):
            return r
    return None


def contains(haystack, needle):
    """needle appears word-for-word in haystack (after normalisation: spacing, diacritics, punctuation, alef forms)"""
    n = norm(needle)
    return bool(n) and n in norm(haystack)


QUOTED = re.compile(r"[«\"“”„]([^«»\"“”„]{2,600})[»\"“”]")


def quoted_spans(text):
    return [m.group(1).strip() for m in QUOTED.finditer(nfkc(text))]


def word_count(text):
    return len(words(text))


STOP = set("في من علي على الي إلى ان إن و ده دي اللي مش هو هي كان عن مع لو ما كل بعد قبل يعني بس لكن او أو حتى لحد زي اكتر "
           "كمان دول بقي بقى الى عند انه انها ولا لما وده ودي فيه".split())


def content_words(text):
    """rough content words (prefixes ال/و/ب/ف/ل off, first 4 letters): enough to see whether a card and a line talk about
    the same thing at all"""
    out = set()
    for w in norm(text).split():
        if len(w) >= 3 and w not in STOP and not w.isdigit():
            out.add(re.sub(r"^(وال|بال|فال|لل|ال|و|ب|ف|ل)(?=..)", "", w)[:4])
    return out


EN_MONTHS = {m: i + 1 for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"])}


def norm_date(raw):
    """a page's date as YYYY-MM-DD (or YYYY-MM, YYYY), or "" when it holds no year: «Fri Jun 01» and «أربعاء, 03» carry no
    year, so they are no date at all (agent readiness report, must-do g: a card's date always carries a year)"""
    from .sources import AR_MONTHS
    s = (raw or "").strip()
    m = re.match(r"(\d{4})-(\d{2})(?:-(\d{2}))?", s)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})\b", s)            # 01 Jun 2026
    if m and m.group(2).lower()[:3] in EN_MONTHS:
        return f"{m.group(3)}-{EN_MONTHS[m.group(2).lower()[:3]]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", s)             # June 1, 2026
    if m and m.group(1).lower()[:3] in EN_MONTHS:
        return f"{m.group(3)}-{EN_MONTHS[m.group(1).lower()[:3]]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})\s+(" + "|".join(sorted(AR_MONTHS, key=len, reverse=True)) + r")\s+(\d{4})", s)
    if m:
        return f"{m.group(3)}-{AR_MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", s)                                # day/month/year (Arabic sites)
    if m and int(m.group(2)) <= 12:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    return ""


def has_year(d):
    return bool(re.search(r"\b(1[89]|20)\d{2}\b", d or ""))
