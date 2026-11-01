"""The right country and place, no flags, no brands (owner's decision 1 of 16 Oct 2026 on section 6 of
Works/output/v6_quality_report.md), and the repeat limit (decision 2).

Decision 1: when the narration is about Egypt or the Egyptian government (or "our"/"your" country, "here", the
government with no country named: the channel speaks to Egyptians), the picture shows Egypt: Egyptian streets, Egyptian
government buildings and places, never another country (v10 showed a German flag on «الحكومة»). No flags on screen. For a
brand, a place or scene of that kind without its logo or brand name.
  - the plan marks such shots place = "EGY"; their searches must name Egypt or an Egyptian place;
  - their candidates must name Egypt or an Egyptian place and no other country or foreign city (checked on the tags or
    title in code, then by the brain on the thumbnail);
  - every candidate whose words hold a flag or a known brand is dropped in code; the brain refuses flags, logos and brand
    names it sees on the thumbnails, in the clip review and in the drawn images.
Owner's answer 12 of 18 Oct 2026 (channel profiles) lifts the flag and brand part for REAL footage and photos in every
profile (materials.flags_in_real_footage / brand_logos_in_real_footage in the profile, monteer/core/profile.py): a flag
or a brand logo may be seen, searched for and chosen. Drawn (AI) images still never draw a flag or a logo, and their
prompts never ask for one. allowed(p) says which applies; a project with no profile (the classic same-result tests)
keeps the ban above. Kept in every profile: the right country (Egypt), stock watermarks refused, "no text" in drawn
images, no close-up faces of private people.
Decision 2: the same picture may repeat, but not 3 times within 75 s. "The same picture" is the same file, and also the
same thing seen (v10's Earth was three different clips): the plan names each shot's subject, and code counts both.
"""
import re
from functools import lru_cache

HOME = "EGY"
REPEAT_WINDOW_S = 75.0
REPEAT_MAX = 2                      # at most 2 showings of one picture or subject in any 75 s
# owner, Phase 2 (16 Oct 2026): "repeat pictures less": one picture FILE at most twice in the whole video, and its two
# showings at least FILE_GAP_S apart (subjects keep the 75 s rule above)
FILE_MAX, FILE_GAP_S = 2, 60.0

EGYPT = {"egypt", "egyptian", "egyptians", "cairo", "giza", "alexandria", "luxor", "aswan", "nile", "suez", "sinai",
         "ismailia", "hurghada", "mansoura", "tanta", "tahrir", "zamalek", "heliopolis", "maadi", "mogamma", "مصر", "القاهرة"}
# Arabic words that make a phrase about a country: the plan must then say which one (place = "EGY" or the ISO-3 meant),
# so «الحكومة» can never again get a picture of some other government by default (compared after script.text.norm)
COUNTRY_CUES = ("مصر", "مصري", "المصري", "المصريين", "المصريه", "الحكومه", "حكومه", "حكومتنا", "الدوله", "دولتنا", "بلدك",
                "بلدنا", "بلادنا", "الجنيه", "البرلمان", "الوزير", "الوزاره", "رئيس الوزراء")
# cities and demonyms that stock tags use for a place (country names come from the map data)
FOREIGN_EXTRA = {
    "berlin", "munich", "hamburg", "frankfurt", "cologne", "german", "london", "english", "british", "britain", "manchester",
    "paris", "french", "lyon", "rome", "italian", "milan", "venice", "madrid", "barcelona", "spanish", "lisbon", "amsterdam",
    "dutch", "brussels", "vienna", "austrian", "zurich", "geneva", "swiss", "prague", "budapest", "warsaw", "polish",
    "moscow", "russian", "kyiv", "kiev", "ukrainian", "istanbul", "ankara", "turkish", "athens", "greek", "stockholm",
    "oslo", "copenhagen", "helsinki", "dublin", "irish", "american", "washington", "york", "chicago", "angeles", "texas",
    "california", "florida", "capitol", "congress", "canadian", "toronto", "ottawa", "vancouver", "mexican", "brazilian",
    "rio", "tokyo", "japanese", "beijing", "shanghai", "chinese", "hong", "seoul", "korean", "delhi", "mumbai", "indian",
    "dubai", "abu", "dhabi", "emirates", "riyadh", "saudi", "doha", "qatari", "kuwaiti", "tehran", "iranian", "baghdad",
    "iraqi", "damascus", "beirut", "amman", "jerusalem", "israeli", "tel", "aviv", "sydney", "melbourne", "australian",
    "singapore", "bangkok", "thai", "jakarta", "manila", "hanoi", "vietnamese", "kremlin", "bundestag", "reichstag",
    "westminster", "parlament", "big ben", "white house", "eiffel"}
FLAG = {"flag", "flags", "banner of", "national emblem", "coat of arms"}
# brands and chains seen in stock tags and Commons titles (oil, fuel, cars, shops, banks, drinks, tech); words that are
# also common nouns (total, shell's "sea shell" aside, apple, amazon, visa, ford) are left to the brain, which refuses any
# brand it sees; this list only drops the obvious ones before it looks
BRANDS = {"shell", "exxon", "exxonmobil", "mobil", "esso", "bp", "chevron", "texaco", "totalenergies", "omv",
          "aramco", "adnoc", "enoc", "emarat", "lukoil", "gazprom", "rosneft", "petrobras", "pemex", "agip", "repsol",
          "cepsa", "valero", "sunoco", "citgo", "phillips 66", "conoco", "conocophillips", "gulf oil",
          "wawa", "sheetz", "cumberland farms", "7-eleven", "circle k", "costco", "walmart", "aldi", "lidl",
          "tesco", "carrefour", "mcdonald", "mcdonalds", "starbucks", "coca", "pepsi", "samsung",
          "google", "tesla", "toyota", "bmw", "mercedes", "volkswagen", "hyundai", "nissan", "uber", "ikea",
          "wataniya", "misr petroleum", "chillout", "mastercard", "hsbc", "citibank", "jpmorgan", "bolmart"}


def _toks(text):
    return re.findall(r"[a-z0-9؀-ۿ]+(?:-[a-z0-9]+)?", (text or "").lower())


def _phrases(text):
    """every single word and every pair of neighbouring words, lower case"""
    t = _toks(text)
    return set(t) | {f"{a} {b}" for a, b in zip(t, t[1:])}


@lru_cache(maxsize=1)
def countries():
    """country names (English) -> ISO-3, from the map data (Natural Earth, public domain)"""
    from .maps import _load
    out = {}
    for f in _load("50m"):
        pr = f["properties"]
        iso = pr.get("ADM0_A3") or pr.get("ISO_A3")
        for k in ("NAME", "NAME_EN", "NAME_LONG", "ADMIN", "SOVEREIGNT"):
            n = (pr.get(k) or "").lower().strip()
            if n and len(n) > 3:
                out.setdefault(n, iso)
    out.update({"usa": "USA", "america": "USA", "uk": "GBR", "england": "GBR", "russia": "RUS"})
    return out


def country_cue(phrase):
    """the first Arabic word of the phrase that makes it about a country, or "" """
    from ..script.text import norm
    n = f" {norm(phrase)} "
    return next((c for c in COUNTRY_CUES if f" {norm(c)} " in n or f" {norm('و' + c)} " in n or f" {norm('ل' + c)} " in n
                 or f" {norm('بال' + c[2:] if c.startswith('ال') else 'ب' + c)} " in n), "")


def egypt_in(text):
    return bool(_phrases(text) & EGYPT)


def foreign_in(text):
    """another country's or a foreign city's name in the text (Egypt's own never counts)"""
    ph = _phrases(text)
    found = sorted(n for n, iso in countries().items() if iso != HOME and n in ph)
    return found + sorted(ph & FOREIGN_EXTRA)


NEGATED = re.compile(r"\b(no|without|never|not)\s+(any\s+|a\s+|visible\s+|readable\s+)*(flags?|logos?|brands?|brand names?|text|letters)\b", re.I)


def asked(text):
    """the text minus what it says NOT to show («no flags», «without a logo»): a prompt that forbids a flag asks for none"""
    return NEGATED.sub(" ", text or "")


def flag_in(text):
    return sorted(_phrases(asked(text)) & FLAG)


def brand_in(text):
    return sorted(_phrases(asked(text)) & BRANDS)


def allowed(p):
    """(flags, brand logos) allowed in real footage and photos for this project: from its profile (answer 12 of 18 Oct
    2026: yes in every profile); (False, False) without a profile, the earlier ban"""
    m = (p.profile_montage() if p is not None else {}).get("materials") or {}
    return bool(m.get("flags_in_real_footage")), bool(m.get("brand_logos_in_real_footage"))


def candidate_problem(shot, text, flags_ok=False, brands_ok=False):
    """why a candidate (its tags, title or description) may not be shown for this shot, or "" """
    if flag_in(text) and not flags_ok:
        return f"a flag ({', '.join(flag_in(text))})"
    if brand_in(text) and not brands_ok:
        return f"a brand ({', '.join(brand_in(text))})"
    if shot.get("place") == HOME:
        if foreign_in(text):
            return f"about Egypt but names {', '.join(foreign_in(text)[:3])}"
        if not egypt_in(text):
            return "about Egypt but does not name Egypt or an Egyptian place"
    return ""


def search_problem(searches, ai_prompt, flags_ok=False, brands_ok=False):
    """the flags and brands a plan may not ask for: in its searches unless the profile allows them in real footage, and
    never in a drawn image's prompt -> [words found]"""
    found = (flag_in(ai_prompt) + brand_in(ai_prompt)
             + ([] if flags_ok else flag_in(searches)) + ([] if brands_ok else brand_in(searches)))
    return sorted(set(found))


def rule_text(p):
    """the flag and brand rule, as the brain's requests say it for this project"""
    flags_ok, brands_ok = allowed(p)
    f = ("FLAGS are allowed in real footage and photos (owner, 18 Oct 2026): search for and choose them where they show "
         "the phrase" if flags_ok else "NO FLAGS on screen, of any country: never search for or prompt a flag")
    b = ("BRAND LOGOS and names are allowed in real footage and photos (owner, 18 Oct 2026)" if brands_ok else
         "A BRAND or company: show a place or scene of that kind without its logo or name; never put a brand name in a "
         "search or a prompt")
    return f + ". " + b + (". Drawn (AI) images never draw a flag or a logo" if flags_ok or brands_ok else "")


def topic_query(shot, q):
    """the words a candidate must hold for the topic filter: an Egypt shot's place word is checked apart (Commons says
    "Egyptian", Pixabay says "cairo"), so «cairo government building» needs "government building" plus any Egypt word"""
    if shot.get("place") != HOME:
        return q
    return " ".join(w for w in q.split() if w.lower() not in EGYPT) or q


def subject_key(s):
    return " ".join(_toks(s))


def subject_use(shot):
    """the repeat-limit key of a shot's subject ("" when it has none: never counted)"""
    k = subject_key(shot.get("subject", ""))
    return f"subject:{k}" if k else ""


def repeats(uses, window=REPEAT_WINDOW_S, most=REPEAT_MAX):
    """uses: [(time s, key, label)] -> [(key, [times])] where one key is shown more than `most` times within `window` s"""
    by = {}
    for t, key, label in uses:
        if key:
            by.setdefault(key, []).append((t, label))
    out = []
    for key, xs in by.items():
        xs.sort()
        for j in range(len(xs) - most):
            if xs[j + most][0] - xs[j][0] < window:
                out.append((key, xs[j:j + most + 1]))
                break
    return out


def too_many(uses, t, key, window=REPEAT_WINDOW_S, most=REPEAT_MAX):
    """True when showing `key` at time t would make it more than `most` showings within `window` s"""
    if not key or key == "pic:":
        return False
    ts = sorted([u for u, k, *_ in uses if k == key] + [t])
    return any(ts[j + most] - ts[j] < window for j in range(len(ts) - most))


def file_ok(uses, t, key):
    """may picture file `key` be shown at time t, given uses [(time, key, ...)]? (Phase 2: at most twice per video, the
    two showings at least FILE_GAP_S apart)"""
    if not key or key in ("pic:", "file:"):
        return True
    ts = [u for u, k, *_ in uses if k == key]
    return len(ts) < FILE_MAX and all(abs(t - u) >= FILE_GAP_S for u in ts)


def file_problems(uses):
    """[(key, [times])] for files shown more than FILE_MAX times or twice within FILE_GAP_S"""
    by = {}
    for t, key, *_ in uses:
        if key:
            by.setdefault(key, []).append(t)
    out = []
    for key, ts in by.items():
        ts.sort()
        if len(ts) > FILE_MAX or any(b - a < FILE_GAP_S for a, b in zip(ts, ts[1:])):
            out.append((key, ts))
    return out
