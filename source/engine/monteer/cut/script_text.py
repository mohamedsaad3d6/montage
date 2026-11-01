"""Parse script.docx into spoken sentences (stage directions removed) and a flat word list."""
import re
import zipfile
from html import unescape

from .common import SCRIPT_DOCX, WORK, normalize_ar, save_json

OUT_JSON = WORK / "script.json" if WORK else None   # None when imported outside a run (the script tool)


def docx_paragraphs(path):
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    paras = []
    for p in re.findall(r"<w:p[ >].*?</w:p>", xml, flags=re.S):
        text = unescape("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, flags=re.S)))
        if text.strip():
            paras.append(text.strip())
    return paras


def is_stage_direction(para):
    return para.startswith("(") and para.rstrip().endswith(")")


LATIN = "A-Za-z\u00C0-\u00D6\u00D8-\u00F6\u00F8-\u024F\u1E00-\u1EFF"     # every Latin letter, also ø, é, ü, ł …
_G = f"[{LATIN}0-9 .\\-&'/’]"
GLOSS = re.compile(rf"\(\s*[{LATIN}]{_G}*(?:\({_G}*\){_G}*)?\)")


def strip_latin_glosses(text):
    # "(Stargate)", "(Force Majeure Notice)" are written glosses, not spoken a second time; also with letters outside
    # A-Z ("(Dan Jørgensen)") and one bracket inside ("(Deutsche Welle (DW))"), as the script tool writes them (19 Oct
    # 2026: those two stopped the approval of «ازمه اوروبا»; every other script on this Mac parses as before)
    return GLOSS.sub(" ", text)


def strip_glosses(text):
    """Latin glosses and pronunciation notes in parentheses ("(النطق: كَيْنْز)", written by the script tool) are read
    by the presenter, not spoken"""
    return strip_latin_glosses(re.sub(r"\(\s*النطق\s*:[^)]*\)", " ", text))


SLOT = re.compile(r"\[[^\]]*المذيع[^\]]*\]")   # «[حضّر مشروبك — بكلام المذيع]»: a place for the presenter's own words


def drink_channel():
    """the episode's channel ends its cold open with the presenter's «حضّر مشروبك» (its profile says so)"""
    from .common import PROJECT
    try:
        st = (PROJECT.profile_montage().get("structure") or {}) if PROJECT is not None and PROJECT.profile else {}
    except Exception:  # noqa: BLE001
        return False
    return "مشروب" in (st.get("cold_open_ends_with") or "")


def split_sentences(para):
    parts = re.split(r"(?<=[.!?؟:؛…])\s+|\.\.+\s*", para)
    return [p.strip() for p in parts if p and len(normalize_ar(p).split()) > 0]


def build():
    paras = docx_paragraphs(SCRIPT_DOCX)
    title, body = paras[0], paras[1:]
    sentences, stage, slots = [], [], []
    for para in body:
        if is_stage_direction(para):
            stage.append(para)
            continue
        marks = SLOT.findall(para)     # the presenter's own words go there: not script words (owner's fix 5 of 21 Oct 2026)
        for k, piece in enumerate(SLOT.split(para)):
            for s in split_sentences(strip_glosses(piece)):
                sentences.append(s)
            if k < len(marks):
                slots.append({"after": len(sentences) - 1, "text": marks[k]})
    flat, sent_of_word = [], []
    for i, s in enumerate(sentences):
        for w in normalize_ar(s).split():
            flat.append(w)
            sent_of_word.append(i)
    data = {"title": title, "sentences": sentences, "stage_directions": stage,
            "words": flat, "sent_of_word": sent_of_word}
    if slots:                          # only when the script has one (every other script's file stays as it was)
        data["slots"] = slots
    elif drink_channel():              # owner's 1a of 21 Oct 2026: no placeholder, but the channel's cold open ends with his
        data["drink_auto"] = True      # «حضّر مشروبك»: the cut finds his own lines by «مشروب» (align.drink_after)
    save_json(OUT_JSON, data)
    print(f"script: {len(sentences)} sentences, {len(flat)} spoken words, "
          f"{len(stage)} stage directions dropped")
    return data


if __name__ == "__main__":
    build()
