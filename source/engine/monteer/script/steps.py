"""The script stage's steps, in their fixed order (run by the same runner as the video: core/runner.py, stage "script").

    bin/monteer script "<project>" [--brain claude-code|api|local] [--from STEP]

check -> queries* -> gather -> select* -> read -> facts* -> outline* -> outline_ok (you) -> draft* -> import -> verify (+revise*)
-> review                                                                                      (* = the brain decides)
The run stops where a decision or your review is needed and continues from there when started again. After review, edit
the review copy in Word and run again (import -> verify -> review make v<N+1>), or approve:
    bin/monteer script approve "<project>" --name "<who>" [--accept-local]
"""
from ..steps import Step
from .common import S, latest_version

BOTH = ("talking_head", "voice_only")


def _f(*parts):
    return lambda p: [S(p, *parts)]


def _channel(p, *names):
    c = p.channel
    return [c.joinpath(*names)] if c else []


def _review_input(p):
    v = latest_version(p)
    return [S(p, f"review_v{v}.docx")] if v else []


def _pending_raw(p):
    from .write import pending_version
    return [S(p, "drafts", f"v{pending_version(p)}.raw.json")]


def _pending_out(p):
    from .write import pending_version
    return [S(p, "drafts", f"v{pending_version(p)}.json")]


def _latest(p, fmt):
    v = latest_version(p)
    return [S(p, fmt.format(v=v))] if v else [S(p, "drafts", "none")]


STEPS = [
    Step("check", "topic, channel profile, source list, style guide and brain are in place", BOTH, "monteer.script.check:step_check",
         always=True),
    Step("queries", "the search plan (brain): news terms, Wikipedia leads, data series, legal searches", BOTH,
         "monteer.script.research:step_queries", inputs=lambda p: _f("topic.json")(p) + _channel(p, "sources.json"),
         outputs=_f("research", "queries.json")),
    Step("gather", "search the source list (feeds, GDELT, Wikipedia references, Wikidata, data APIs, Federal Register)", BOTH,
         "monteer.script.research:step_gather", inputs=_f("research", "queries.json"), outputs=_f("research", "items.json")),
    Step("select", "which items to read (brain); one more search round if it asks", BOTH, "monteer.script.research:step_select",
         inputs=_f("research", "items.json"), outputs=_f("research", "selected.json")),
    Step("read", "read the chosen pages (robots incl. Claude-User, no paywall), keep their text internally", BOTH,
         "monteer.script.research:step_read", inputs=_f("research", "selected.json"), outputs=_f("research", "read.json")),
    Step("facts", "fact cards from every text (brain), each passage and number checked in code", BOTH,
         "monteer.script.research:step_facts", version=2, inputs=lambda p: _f("research", "read.json")(p) + _f("research", "texts")(p),
         outputs=_f("facts.json")),
    Step("outline", "the outline (brain): angle, cold open, parts, cards, word budget, material types", BOTH,
         "monteer.script.write:step_outline", inputs=lambda p: _f("facts.json")(p) + _f("outline_notes.json")(p) + _f("topic.json")(p)
         + _channel(p, "style", "style_guide.md") + _channel(p, "style", "style_profile.json"), outputs=_f("outline.json")),
    Step("outline_ok", "your yes or your notes on the outline (decision 10a)", BOTH, "monteer.script.write:step_outline_ok",
         inputs=lambda p: _f("outline.json")(p) + _f("outline_ok.json")(p)),
    Step("draft", "the full draft, part by part (brain), each line with its type and cards", BOTH, "monteer.script.write:step_draft",
         inputs=lambda p: _f("outline.json")(p) + _f("outline_ok.json")(p) + _f("facts.json")(p), outputs=_f("drafts", "v1.raw.json")),
    Step("import", "your edits in the latest review copy come back (and cancel an approval)", BOTH, "monteer.script.approve:step_import",
         always=True),
    Step("verify", "the code checks (sources, numbers, copying, quotes, types, length); up to 2 revise rounds (brain)", BOTH,
         "monteer.script.write:step_verify", version=2, inputs=lambda p: _pending_raw(p) + _f("facts.json")(p), outputs=_pending_out),
    Step("review", "the review copy (Word, sources and types in the margin) and the internal sources file", BOTH,
         "monteer.script.steps:step_review", inputs=lambda p: _latest(p, "drafts/v{v}.json"), outputs=lambda p: _latest(p, "review_v{v}.docx")),
]

by_name = {s.name: s for s in STEPS}


def step_review(p):
    from .review import write_review
    write_review(p)
