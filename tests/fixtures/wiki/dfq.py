#!/usr/bin/env python3
"""Repo-local dfq.py-compatible fixture for the offline test suite.

The harness wiki module shells out to the DF wiki export's dfq.py
(~/workspace/df-wiki-export/dfq.py, a 4,485-page export with FTS +
vector indexes). That export lives outside the repo, so a fresh
checkout (CI, a clean machine) has no dfq.py and every offline test
that touches the wiki fails. This fixture is a tiny standalone
dfq.py-compatible tool over a small corpus of real DF pages, so the
offline suite can exercise the real subprocess -> JSON -> prefetch ->
briefing path hermetically. It implements the same CLI surface the
harness uses (search/semantic/hybrid/title/page/stats, --limit,
--json) and the same JSON shape ({query, fallback_or, ms, results
with slug/title/words/rank/snippet}); semantic/hybrid/title are
keyword search here, since the fixture has no vector index. Stdlib
only (sqlite3 FTS5, porter stemming, title weighted 10x like the
real tool).

The real export is still exercised by the live wiki route test and
by dfq.py's own accuracy eval; this fixture is only the offline
suite's stand-in.
"""

import argparse
import json
import sqlite3
import sys
import time

# (slug, title, text). Condensed from the real DF wiki pages; the
# texts carry the terms the offline tests' queries rank on.
PAGES = [
    ("alcohol", "Alcohol",
     "Alcohol is the primary drink of dwarves, and the only drink "
     "that satisfies a dwarf's thirst without the unhappy thoughts "
     "that come from drinking water. This page explains how to brew "
     "alcohol from plants at a still. Each brewing job produces five "
     "units of alcohol per brewable plant, and deposits the alcohol "
     "in an empty barrel or large pot, recovering any plant seeds in "
     "the process. The size of a stack does not affect how long it "
     "takes to brew it. To brew alcohol you need a still, a brewable "
     "plant such as a plump helmet, and an empty barrel. The brewer "
     "carries the plant to the still and works the brewing job. "
     "Alcohol is stored in barrels in a food stockpile, and dwarves "
     "drink it whenever they are thirsty. A fort with no alcohol "
     "will see its dwarves drink water instead, which they dislike, "
     "and a fort with no drink at all will see dwarves die of "
     "thirst. Brewing is therefore one of the first jobs a new fort "
     "should set up, and a still is one of the first workshops to "
     "build. Different plants brew into different kinds of alcohol, "
     "but any alcohol satisfies thirst the same way."),
    ("still", "Still",
     "A still is a workshop used for brewing alcohol from plants. "
     "Each brewing job at a still consumes one brewable plant and "
     "one empty barrel or large pot, and produces five units of "
     "alcohol and one seed. The still is built from wood or stone "
     "and needs a brewer to work it. Brewing is the way a fort "
     "turns its farm produce into drink, and a fort that brews "
     "steadily never runs out of alcohol."),
    ("brewer", "Brewer",
     "The brewer is the dwarf who brews alcohol at the still. A "
     "brewer with the brewing labor enabled takes a brewable plant "
     "to the still and works the brewing job, turning the plant "
     "into drink. Brewing skill makes the job faster. A good "
     "brewer keeps the fort's barrels full of alcohol."),
    ("strange-mood", "Strange mood",
     "A strange mood is a state that strikes a dwarf without "
     "warning. The dwarf claims a workshop and demands specific "
     "materials, then works in a fever until the mood is satisfied "
     "and an artifact is created. If the materials cannot be "
     "found, the dwarf goes mad. Strange moods are how artifacts "
     "are made."),
    ("kitchen", "Kitchen",
     "A kitchen is a workshop for cooking food into meals. A cook "
     "working at a kitchen turns raw ingredients into prepared "
     "meals, which feed dwarves better than raw food and keep the "
     "fort's food stocks varied. Cooking takes place at the "
     "kitchen, and a good kitchen keeps the fort fed."),
    ("cook", "Cook",
     "The cook skill governs cooking food at the kitchen. A dwarf "
     "with the cooking labor prepares meals from ingredients, and "
     "a skilled cook makes fine meals that dwarves enjoy. Cooking "
     "is done at the kitchen, and every fort needs a cook."),
    ("tallow", "Tallow",
     "Tallow is rendered fat, used in cooking and for making soap. "
     "A kitchen renders tallow from fat, and cooking with tallow "
     "makes meals from food that would otherwise go to waste."),
    ("combat", "Combat",
     "Combat is how dwarves fight hostile creatures that attack "
     "the fort. A dwarf in combat defends the fort against "
     "invaders, and a trained military defends the entrance. "
     "Combat against a hostile creature is dangerous, and defense "
     "of the fort depends on armor, weapons, and training."),
    ("ambush", "Ambush",
     "An ambush is a surprise attack by hostile creatures. "
     "Ambushers hide near the fort and strike when a dwarf is "
     "outside. Combat against an ambush needs a fast response, "
     "and a fort that watches its entrances survives."),
    ("military", "Military",
     "The military is the fort's defense against hostile creatures "
     "and invaders. Squads train in barracks and station at "
     "choke points. Military dwarves need armor and weapons, and "
     "combat training keeps them ready for a siege."),
    ("siege", "Siege",
     "A siege is a sustained invasion by goblins or other hostile "
     "forces. A siege force camps outside the fort and attacks in "
     "waves. Defense against a siege needs walls, traps, and a "
     "trained military."),
    ("migrant", "Migrant",
     "A migrant is a dwarf who arrives at the fort in a migrant "
     "wave. Each wave brings new dwarves who need beds, food, and "
     "drink. A visitor may also arrive and ask to stay."),
    ("death", "Death",
     "A dwarf dies when its wounds, thirst, or hunger become too "
     "much. The cause of a dwarf's death is recorded, and a dead "
     "dwarf is buried or memorialized. Death from thirst is the "
     "most common preventable cause."),
    ("cavern", "Cavern",
     "A cavern is a vast underground layer inhabited by cavern "
     "creatures such as demons and trolls. A cavern creature that "
     "wanders into the fort is a threat, and demons and trolls are "
     "among the most dangerous cavern creatures."),
]


def _build_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE VIRTUAL TABLE pages USING fts5"
        "(slug UNINDEXED, title, body, tokenize='porter')")
    for slug, title, text in PAGES:
        conn.execute("INSERT INTO pages VALUES (?, ?, ?)",
                     (slug, title, text))
    return conn


def _terms(query: str) -> list[str]:
    return [t for t in "".join(
        c if c.isalnum() else " " for c in query.lower()).split() if t]


def _search(conn: sqlite3.Connection, query: str,
            limit: int) -> tuple[list[dict], bool]:
    terms = _terms(query)
    if not terms:
        return [], False
    quoted = " ".join(f'"{t}"' for t in terms)
    rows = list(conn.execute(
        "SELECT slug, title, body, bm25(pages, 10.0, 1.0) AS r"
        " FROM pages WHERE pages MATCH ? ORDER BY r LIMIT ?",
        (" AND ".join(quoted.split()), limit)))
    fallback = False
    if not rows:
        fallback = True
        rows = list(conn.execute(
            "SELECT slug, title, body, bm25(pages, 10.0, 1.0) AS r"
            " FROM pages WHERE pages MATCH ? ORDER BY r LIMIT ?",
            (" OR ".join(quoted.split()), limit)))
    out = []
    for slug, title, body, rank in rows:
        out.append({"slug": slug, "title": title,
                    "words": len(body.split()), "rank": -rank,
                    "snippet": _snippet(body, terms)})
    return out, fallback


def _snippet(body: str, terms: list[str]) -> str:
    """Excerpt around the first query term, matched terms bracketed
    (like the real tool's FTS snippet). A fixed token window around
    the first match can miss the term the caller cares about, so the
    window starts at the first match and runs long enough to cover
    the next sentence."""
    import re
    low = body.lower()
    hits = [low.find(t) for t in terms]
    hits = [h for h in hits if h >= 0]
    idx = min(hits) if hits else 0
    start = max(0, idx - 60)
    end = min(len(body), idx + 260)
    text = body[start:end]
    if terms:
        # Bracket the matched word (a term is a stem: "brew"
        # brackets "brewing", like the real tool).
        pat = re.compile("(" + "|".join(re.escape(t) for t in terms)
                         + r")\w*", re.IGNORECASE)
        text = pat.sub(lambda m: "[" + m.group(0) + "]", text)
    if start > 0:
        text = " ... " + text
    if end < len(body):
        text = text + " ... "
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("search", "semantic", "hybrid", "title"):
        sp = sub.add_parser(name)
        sp.add_argument("query", nargs="+")
        sp.add_argument("--limit", type=int, default=5)
        sp.add_argument("--json", action="store_true")
    pg = sub.add_parser("page")
    pg.add_argument("slug")
    pg.add_argument("--lines", type=int, default=0)
    sub.add_parser("stats")
    args = ap.parse_args(argv)
    conn = _build_db()
    if args.mode == "page":
        for slug, title, text in PAGES:
            if slug == args.slug:
                out = f"# {title} [{slug}]\n\n{text}\n"
                if args.lines:
                    out = "\n".join(out.splitlines()[:args.lines]) + "\n"
                sys.stdout.write(out)
                return 0
        sys.stderr.write(f"no such page: {args.slug}\n")
        return 1
    if args.mode == "stats":
        print(json.dumps({"pages": len(PAGES), "words": sum(
            len(t.split()) for _, _, t in PAGES)}))
        return 0
    query = " ".join(args.query)
    t0 = time.monotonic()
    results, fallback = _search(conn, query, args.limit)
    ms = (time.monotonic() - t0) * 1000.0
    print(json.dumps({"query": query, "fallback_or": fallback,
                      "ms": round(ms, 1), "results": results}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
