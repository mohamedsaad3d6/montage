"""Numbers said in words (owner's answer 1 of the first real test, 18 Oct 2026): the transcript often writes them as
words, «خمسة ألاف عام», «مليون ومئتي ألف جنيه», «وأربع واربعون دولة», where the plan's number graphics hold 5000,
1200000, 44. Read here: units, teens, tens, hundreds, ألف/آلاف/مليون/مليار/تريليون (and their duals), joined with «و», in
standard and Egyptian colloquial forms. Ordinals («السابع», «الأول») are NOT numbers here (owner's answer 2: a number
graphic «7» for «القرن السابع» would mislead on screen); ordinal() tells them apart for the check's message.

  value_at(words, i)   the number said in words starting at word i, or None
  ordinal(word)        True for «الأول … العاشر» (and without ال)
"""
from ..script.text import norm

_UNITS = {1: "واحد واحدة", 2: "اتنين اثنين اثنان اثنتين اتنتين", 3: "ثلاث ثلاثة تلات تلاتة", 4: "اربع اربعة أربع أربعة",
          5: "خمس خمسة", 6: "ست ستة", 7: "سبع سبعة", 8: "ثمان ثماني ثمانية تمن تمانية تماني", 9: "تسع تسعة", 10: "عشر عشرة"}
_TEENS = {11: "حداشر احداشر", 12: "اتناشر اطناشر", 13: "تلتاشر تلاتاشر", 14: "اربعتاشر اربعطاشر", 15: "خمستاشر خمسطاشر",
          16: "ستاشر سطاشر", 17: "سبعتاشر سبعطاشر", 18: "تمنتاشر تمنطاشر", 19: "تسعتاشر تسعطاشر"}
_TENS = {20: "عشرين عشرون", 30: "ثلاثين ثلاثون تلاتين", 40: "اربعين اربعون أربعين أربعون", 50: "خمسين خمسون",
         60: "ستين ستون", 70: "سبعين سبعون", 80: "ثمانين ثمانون تمانين", 90: "تسعين تسعون"}
_HUND = {100: "مية مائة مئة ميه", 200: "ميتين مئتين مئتي مائتين مائتي ميتين", 300: "ثلاثمائة ثلاثمية تلتمية ثلثمائة",
         400: "اربعمائة أربعمائة اربعمية", 500: "خمسمائة خمسمية", 600: "ستمائة ستمية", 700: "سبعمائة سبعمية",
         800: "ثمانمائة ثمانمية تمنمية", 900: "تسعمائة تسعمية"}
_SCALE = {1e3: "ألف الف آلاف الاف ألاف", 2e3: "ألفين الفين ألفان", 1e6: "مليون ملايين", 2e6: "مليونين مليونان",
          1e9: "مليار مليارات", 2e9: "مليارين", 1e12: "تريليون تريليونات"}
_ORD = "الأول الاول الثاني التاني الثالث التالت الرابع الخامس السادس السابع الثامن التامن التاسع العاشر أول اول ثاني تاني ثالث رابع خامس سادس سابع ثامن تاسع عاشر"


def _table(d):
    return {norm(w): v for v, ws in d.items() for w in ws.split()}


NUM = {**_table(_UNITS), **_table(_TEENS), **_table(_TENS), **_table(_HUND)}
SCALE = _table(_SCALE)
ORD = {norm(w) for w in _ORD.split()}


def _tok(w):
    """a word's number meaning: ("n", value) | ("s", scale) | None; one joined «و» is allowed"""
    t = norm(w)
    for x in (t, t[1:] if t.startswith("و") and len(t) > 2 else None):
        if x is None:
            continue
        if x in NUM:
            return ("n", NUM[x])
        if x in SCALE:
            return ("s", SCALE[x])
    return None


def value_at(words, i):
    """the number said in words from word i on («خمسة ألاف» 5000, «مليون ومئتي ألف» 1200000, «وأربع واربعون» 44), or None"""
    total, cur, seen, j = 0.0, 0.0, False, i
    while j < len(words):
        k = _tok(words[j]["w"] if isinstance(words[j], dict) else words[j])
        if not k:
            break
        seen = True
        if k[0] == "n":
            cur += k[1]
        else:
            s = k[1]
            if s in (2e3, 2e6, 2e9):                        # a dual is the number itself («ألفين» = 2000)
                total += (cur or 1) * s if cur else s
            else:
                total += (cur or 1) * s
            cur = 0.0
        j += 1
    return total + cur if seen else None


def ordinal(word):
    return norm(word) in ORD


__all__ = ["value_at", "ordinal"]
