"""Per-dwarf tracking (2026-11-27, diary per-dwarf feed).

The diary and the snapshot both need to know each dwarf as a
person — mood, stress, needs, wounds, job, relationships — and,
crucially, what CHANGED for them since the last record ("Olon was
stressed yesterday, today he is content"). This module is the one
place that knowledge lives: it diffs two unit_history samples into
plain-words changes, ranks them by significance, and builds the
structured per-dwarf record the diary feed and the snapshot's
citizen section both use. Pure functions over Store sample dicts
(or live citizen dicts, which carry the same fields); no game
reads, no model calls.

Grounding: a change is only reported when BOTH samples carry the
field. Old samples (recorded before the per-dwarf columns landed)
have mood -1, stress_category -1, no needs/relations — a field
that is unknown on either side is skipped, never compared, so the
feed never invents a change out of missing data.
"""

from __future__ import annotations

import re
from typing import Any

# A dwarf is "featured" (carried in the feed / the snapshot's
# citizen section with their personal life) when their most
# significant change reaches this level, or when an event or a
# decision involves them (the caller adds those). Stable dwarves
# with nothing new get a line or nothing — the feed is curated,
# not dumped.
FEATURE_THRESHOLD = 2

# Significance: 0 routine, 1 minor, 2 notable, 3 major.
SIG_ROUTINE = 0
SIG_MINOR = 1
SIG_NOTABLE = 2
SIG_MAJOR = 3

# Stress category (dfhack.units.getStressCategory: 0 = most
# stressed, 6 = least; baseline fort is category 3) in plain
# words. These are the HARNESS's words for the category, not game
# strings — the game exposes only the number. Consistent with
# attention.describe_unit ("highly stressed" <= 1, "stressed" 2).
STRESS_WORDS = {
    0: "at breaking point",
    1: "highly stressed",
    2: "stressed",
    3: "content",
    4: "relaxed",
    5: "very relaxed",
    6: "serene",
}


def stress_words(category: Any) -> str:
    """Plain words for a stress category int, "" when unknown."""
    if isinstance(category, int) and category in STRESS_WORDS:
        return STRESS_WORDS[category]
    return ""


# A need's focus is its satisfaction (the game's needs screen
# shows a need going unmet as its focus falls). Focus below zero
# reads as unmet; a move of this size reads as a real change
# rather than drift. Both are the harness's reading of the raw
# numbers, documented here, not game strings.
NEED_UNMET_FOCUS = 0
NEED_BIG_MOVE = 25

# A stress-level move of one cutoff step (the getStressCategory
# cutoffs are 50000/25000/10000/-10000/-25000/-50000/-100000)
# reads as a real change even when the category does not move.
STRESS_BIG_MOVE = 10000


def _need_words(name: Any) -> str:
    """df.need_type enum name in plain words: "BeWithFamily" ->
    "be with family". A mechanical rendering, not a paraphrase."""
    if not isinstance(name, str) or not name:
        return ""
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).strip().lower()
    return words


# Raw df job tokens in plain words. Moved here from attention.py
# (2026-11-27, diary feed audit R5): the diary feed rendered the
# raw token ("working as Fish") while instructing the model to use
# plain words, and the model mapped it to fish-cleaning — Ral
# "cleans fish" in three entries. Both the snapshot attention
# lines and the diary feed now share this one map, so a new job
# token gets plain words everywhere at once. Values are verb
# phrases ("fishing", "constructing a building"); the diary
# renders a mapped token bare and an unmapped one as
# "working as <words>".
JOB_VERBS = {
    "Dig": "digging", "FellTree": "cutting down a tree",
    "Eat": "eating", "Drink": "drinking", "Drink2": "drinking",
    "Sleep": "sleeping", "HaulStone": "hauling stone",
    "HaulWood": "hauling wood", "HaulItem": "hauling an item",
    "HaulBody": "hauling a body", "HaulFood": "hauling food",
    "HaulFurniture": "hauling furniture",
    "ConstructBuilding": "constructing a building",
    "CustomReaction": "working a reaction",
    "PrepareMeal": "cooking a meal", "MakeBarrel": "making a barrel",
    "MakeBucket": "making a bucket", "PlantSeeds": "planting seeds",
    "HarvestPlants": "harvesting plants",
    "GatherPlants": "gathering plants", "Fish": "fishing",
    "Hunt": "hunting", "TrainAnimal": "training an animal",
    "ButcherAnimal": "butchering an animal", "MilkCreature": "milking",
    "ShearCreature": "shearing", "Clean": "cleaning",
    "Rest": "resting", "SeekArtifact": "seeking an artifact",
    "StoreItemInStockpile": "storing an item",
    "RemoveConstruction": "removing a construction",
    "DestroyBuilding": "destroying a building",
}


def job_words(token: Any) -> str:
    """A raw df job token in plain words. Mapped tokens use
    JOB_VERBS; an unknown token is split on CamelCase and
    lowercased ("StoreItemInStockpile" -> "store item in
    stockpile") — the raw token never reaches prose. "" for a
    missing/empty token. Malformed input (non-string, digits
    only) returns "" or the lowercased digits, never raises."""
    if not isinstance(token, str) or not token:
        return ""
    if token in JOB_VERBS:
        return JOB_VERBS[token]
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", token).strip().lower()
    return words


def _wound_ids(sample: dict[str, Any] | None) -> set[Any]:
    if not sample:
        return set()
    out = set()
    for w in sample.get("wounds") or []:
        if isinstance(w, dict) and w.get("id") is not None:
            out.add(w["id"])
    return out


def _wound_parts(sample: dict[str, Any] | None
                 ) -> dict[Any, int]:
    """Wound id -> parts affected (0 when the record carries no
    parts count). A wound record's id is stable per wound, but the
    parts count moves as the wound worsens or heals."""
    if not sample:
        return {}
    out: dict[Any, int] = {}
    for w in sample.get("wounds") or []:
        if isinstance(w, dict) and w.get("id") is not None:
            parts = w.get("parts")
            out[w["id"]] = parts if isinstance(parts, int) else 0
    return out


def _needs_by_name(sample: dict[str, Any] | None
                   ) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not sample:
        return out
    for n in sample.get("needs") or []:
        if isinstance(n, dict) and n.get("need"):
            out[str(n["need"])] = n
    return out


def _relations_by_key(sample: dict[str, Any] | None
                      ) -> dict[tuple[str, Any], dict[str, Any]]:
    out: dict[tuple[str, Any], dict[str, Any]] = {}
    if not sample:
        return out
    for r in sample.get("relations") or []:
        if isinstance(r, dict) and r.get("type") is not None:
            out[(str(r["type"]), r.get("histfig_id"))] = r
    return out


def _social_label(love: Any, meet_count: Any) -> str:
    """Plain-words label for a social tie (hf_visual read), from the
    wiki's thresholds: love >= 50 friend, >= 75 close friend,
    >= 100 kindred spirit; <= -50 disliked, <= -75 hated, -100 pure
    hate; 30+ meetings without that love is a long-term
    acquaintance. Anything else is an acquaintance (they have met)
    or, on the negative side without reaching disliked, on poor
    terms. A missing love value falls back to the meeting count."""
    mc = meet_count if isinstance(meet_count, int) else 0
    if not isinstance(love, int):
        return "long-term acquaintance" if mc >= 30 else "acquaintance"
    if love >= 100:
        return "kindred spirit"
    if love >= 75:
        return "close friend"
    if love >= 50:
        return "friend"
    if love >= 0:
        return "long-term acquaintance" if mc >= 30 \
            else "acquaintance"
    if love <= -100:
        return "pure hate"
    if love <= -75:
        return "hated"
    if love <= -50:
        return "disliked"
    return "on poor terms"


def social_ties(sample: dict[str, Any],
                prev_social: list[dict[str, Any]] | None = None,
                related_states: dict[int, dict[str, Any]] | None = None
                ) -> tuple[list[dict[str, Any]], int]:
    """The dwarf's in-fort social ties (friendships, grudges) from
    the sample's hf_visual read, strongest first, each with its
    plain-words label, love value, meeting count, and whether it is
    new today (``prev_social`` is the previous sample's social list;
    None means first sighting, so nothing is new today — same rule
    as relations). Returns (ties, outside_count): ``outside_count``
    is the number of social entries whose target is NOT in the fort
    — carried as a count only, never as a story, so the feed can
    say a dwarf has people elsewhere without inventing who they
    are (the 04-01 "Mestthos has a family somewhere he is not"
    invention). Ties with no name are dropped (unresolvable)."""
    related_states = related_states or {}
    prev_keys = set()
    if prev_social is not None:
        prev_keys = {r.get("histfig_id") for r in prev_social
                     if isinstance(r, dict)}
    ties: list[dict[str, Any]] = []
    outside = 0
    for r in sample.get("social") or []:
        if not isinstance(r, dict):
            continue
        if not r.get("in_fort"):
            outside += 1
            continue
        name = r.get("name") or ""
        if not name:
            continue
        tie: dict[str, Any] = {
            "name": name,
            "label": _social_label(r.get("love"),
                                   r.get("meet_count")),
            "love": r.get("love"),
            "meet_count": r.get("meet_count"),
        }
        if prev_social is not None:
            tie["new_today"] = r.get("histfig_id") not in prev_keys
        else:
            tie["new_today"] = False
        uid = r.get("unit_id")
        if isinstance(uid, int) and uid in related_states:
            st = related_states[uid]
            tie["mood"] = st.get("mood_name") or "none"
            tie["stress"] = stress_words(st.get("stress_category"))
            if st.get("changed"):
                tie["changed"] = True
        ties.append(tie)
    ties.sort(key=lambda t: (-abs(t.get("love") or 0),
                             -(t.get("meet_count") or 0)))
    return ties, outside


def salient_traits(sample: dict[str, Any], limit: int = 6
                   ) -> list[dict[str, Any]]:
    """Personality facets far from neutral (50): |value - 50| >= 25,
    most deviant first, capped. The feed carries the facet name in
    plain words plus the value and an intensity word; the diary
    model phrases it. Facets near neutral are not character — they
    are noise — so they never reach the feed."""
    out: list[dict[str, Any]] = []
    for t in sample.get("traits") or []:
        if not isinstance(t, dict):
            continue
        v = t.get("value")
        if not isinstance(v, int):
            continue
        dev = abs(v - 50)
        if dev < 25:
            continue
        raw_facet = t.get("facet")
        # Unresolved enum fallback ("facet_41"): the Lua name
        # lookup failed for this sample (the 125-04-12 sample
        # recorded before the daemon reloaded the fixed Lua). A
        # bare index is not character — it would reach the prompt
        # as garbage — so it never reaches the feed. Resolved
        # facets ("LOVE_PROPENSITY") pass through.
        if isinstance(raw_facet, str) and re.fullmatch(
                r"facet_\d+", raw_facet):
            continue
        facet = str(raw_facet or "").lower().replace("_", " ")
        if v > 50:
            words = "very high" if dev >= 40 else "high"
        else:
            words = "very low" if dev >= 40 else "low"
        out.append({"facet": facet, "value": v, "words": words})
    out.sort(key=lambda x: -abs(x["value"] - 50))
    return out[:limit]


def _is_unresolved_enum(value: Any) -> bool:
    """Is this an unresolved enum fallback, not a name? The Lua
    name lookup yields a bare number ("14"), or the fallback
    strings "emotion_14" / "thought_57" / "facet_41". A resolved
    name ("ANNOYANCE", "Rain", "LOVE_PROPENSITY") is not one of
    these. An int value is unresolved too (the JSON carries
    strings, but a live dict may carry the raw number)."""
    if isinstance(value, int):
        return True
    if not isinstance(value, str):
        return True
    if value.isdigit():
        return True
    return re.fullmatch(
        r"(emotion|thought|facet)_\d+", value) is not None


def recent_emotions(sample: dict[str, Any], limit: int = 5
                    ) -> list[dict[str, Any]]:
    """The dwarf's most recent emotions (soul.personality.emotions),
    most recent first, capped. Each carries the emotion type and the
    thought that caused it, in plain words, plus strength, severity,
    and the game date it was felt. Old samples (no emotions column)
    yield []."""
    out: list[dict[str, Any]] = []
    for e in sample.get("emotions") or []:
        if not isinstance(e, dict):
            continue
        # Unresolved enum fallbacks (a bare number "14", or
        # "emotion_14" / "thought_57"): the Lua name lookup
        # failed for this sample. A bare index is not a feeling
        # — it would reach the prompt as garbage — so the entry
        # never reaches the feed. Resolved names ("ANNOYANCE",
        # "Rain") pass through.
        raw_type = e.get("type")
        raw_thought = e.get("thought")
        if _is_unresolved_enum(raw_type):
            continue
        # A missing thought is incomplete, not unresolved — keep
        # the entry and render it without the thought suffix (the
        # old behaviour). A present-but-unresolved thought drops
        # the entry, like an unresolved type.
        if raw_thought is not None \
                and _is_unresolved_enum(raw_thought):
            continue
        out.append({
            "type": str(raw_type or "").lower().replace(
                "_", " "),
            "strength": e.get("strength"),
            "thought": str(raw_thought or "").lower().replace(
                "_", " "),
            "severity": e.get("severity"),
            "year": e.get("year"),
            "year_tick": e.get("year_tick"),
        })
    out.sort(key=lambda e: (e.get("year") or 0,
                            e.get("year_tick") or 0), reverse=True)
    return out[:limit]


def diff_unit_samples(prev: dict[str, Any] | None,
                      curr: dict[str, Any] | None
                      ) -> list[dict[str, Any]]:
    """What changed for one dwarf between two samples, in plain
    words, most significant first. Each change: {"kind", "text",
    "significance"}. prev None (first sighting) yields no changes
    — the dwarf is simply new to the record; arrivals are covered
    by the Journal's citizen_new events, not guessed here. A field
    unknown on either side is skipped, never compared."""
    if curr is None:
        return []
    if prev is None:
        return []
    changes: list[dict[str, Any]] = []

    def add(kind: str, text: str, sig: int) -> None:
        if text:
            changes.append({"kind": kind, "text": text,
                            "significance": sig})

    # Mood (raw df.mood_type; -1 = none).
    pm, cm = prev.get("mood"), curr.get("mood")
    if (isinstance(pm, int) and isinstance(cm, int)
            and pm != -1 and cm != -1 and pm != cm):
        pn = prev.get("mood_name") or "a strange mood"
        cn = curr.get("mood_name") or "a strange mood"
        add("mood_changed",
            f"mood shifted from {pn} to {cn}", SIG_MAJOR)
    elif (isinstance(pm, int) and isinstance(cm, int)
          and pm == -1 and cm != -1):
        cn = curr.get("mood_name") or "a strange mood"
        add("mood_changed",
            f"fell into a {cn} mood", SIG_MAJOR)
    elif (isinstance(pm, int) and isinstance(cm, int)
          and pm != -1 and cm == -1):
        pn = prev.get("mood_name") or "a strange mood"
        add("mood_changed",
            f"came out of their {pn} mood", SIG_MAJOR)

    # Stress: the category move is the story; a big level move
    # inside one category is worth a line too.
    pc, cc = prev.get("stress_category"), curr.get("stress_category")
    if (isinstance(pc, int) and isinstance(cc, int)
            and pc != -1 and cc != -1 and pc != cc):
        pw, cw = stress_words(pc), stress_words(cc)
        direction = "rose" if cc < pc else "eased"
        if cc < pc:
            sig = SIG_MAJOR if cc <= 1 else SIG_NOTABLE
        else:
            sig = SIG_MINOR
        add("stress_changed",
            f"stress {direction} from {pw} to {cw}", sig)
    else:
        pl, cl = prev.get("stress"), curr.get("stress")
        if (isinstance(pl, int) and isinstance(cl, int)
                and abs(cl - pl) >= STRESS_BIG_MOVE):
            direction = "climbing" if cl > pl else "easing"
            add("stress_changed",
                f"stress is {direction}", SIG_MINOR)

    # Wounds: wound ids are stable per wound, so a new id is a new
    # wound and a missing id is a healed one.
    prev_w, curr_w = _wound_ids(prev), _wound_ids(curr)
    new_w = curr_w - prev_w
    healed_w = prev_w - curr_w
    if new_w:
        n = len(new_w)
        add("wound_new",
            f"was wounded ({n} new wound{'s' if n > 1 else ''})",
            SIG_MAJOR)
    if healed_w:
        n = len(healed_w)
        add("wound_healed",
            f"{n} wound{'s' if n > 1 else ''} healed", SIG_MINOR)
    # A wound id that persists on both sides with MORE parts
    # affected got worse. The old diff compared ids only, so the
    # 04-01 äs case (wound id 4, parts 0 -> 2) produced NO change
    # and the entry never reported it.
    prev_parts, curr_parts = _wound_parts(prev), _wound_parts(curr)
    worsened = [wid for wid in prev_w & curr_w
                if curr_parts.get(wid, 0) > prev_parts.get(wid, 0)]
    if worsened:
        n = len(worsened)
        add("wound_worsened",
            "a wound got worse" if n == 1
            else f"{n} wounds got worse", SIG_NOTABLE)

    # Needs: focus below zero reads as unmet. A need newly unmet
    # (crossed below zero, or fell hard) is notable; a need newly
    # met is a minor recovery beat. Needs with level 0 are not
    # real needs for this dwarf and are skipped.
    prev_n, curr_n = _needs_by_name(prev), _needs_by_name(curr)
    for name, cn in curr_n.items():
        level = cn.get("level")
        if isinstance(level, int) and level <= 0:
            continue
        cf = cn.get("focus")
        if not isinstance(cf, int):
            continue
        pn = prev_n.get(name)
        pf = pn.get("focus") if pn else None
        words = _need_words(name)
        if not words:
            continue
        if cf < NEED_UNMET_FOCUS and (
                pf is None or pf >= NEED_UNMET_FOCUS
                or pf - cf >= NEED_BIG_MOVE):
            add("need_unmet",
                f"went without {words}", SIG_NOTABLE)
        elif cf >= NEED_UNMET_FOCUS and isinstance(pf, int) and (
                pf < NEED_UNMET_FOCUS
                or cf - pf >= NEED_BIG_MOVE):
            add("need_met",
                f"finally got {words}", SIG_MINOR)

    # Job: the job type string ("Drink2", "Sleep", ...) is a raw
    # enum name; the record keeps it raw and the renderer puts it
    # in plain words (job_words, below). A job change alone is
    # routine — it only matters as part of a featured dwarf's day.
    pj, cj = prev.get("job") or "", curr.get("job") or ""
    if pj != cj:
        if not cj:
            add("job_changed", "went idle", SIG_ROUTINE)
        elif not pj:
            add("job_changed", f"started {job_words(cj)}",
                SIG_ROUTINE)
        else:
            add("job_changed",
                f"switched from {job_words(pj)} to {job_words(cj)}",
                SIG_ROUTINE)

    # Relations: a new relation (by type + histfig) or a lost one.
    # A lost spouse/family relation is major; a new friend is
    # notable. (A relation lost because the other dwarf died is
    # also carried by the day's death event — the feed shows both,
    # they are two views of one fact.)
    prev_r, curr_r = _relations_by_key(prev), _relations_by_key(curr)
    for key, cr in curr_r.items():
        if key not in prev_r:
            rname = cr.get("name") or "someone"
            rtype = key[0]
            sig = SIG_MAJOR if rtype in ("spouse", "lover") \
                else SIG_NOTABLE
            add("relation_new",
                f"gained a {rtype}: {rname}", sig)
    for key, pr in prev_r.items():
        if key not in curr_r:
            rname = pr.get("name") or "someone"
            rtype = key[0]
            add("relation_lost",
                f"lost {rtype} {rname}", SIG_MAJOR)

    changes.sort(key=lambda c: -c["significance"])
    return changes


def most_unmet_needs(sample: dict[str, Any] | None,
                     limit: int = 3) -> list[dict[str, Any]]:
    """The dwarf's most unmet needs (focus below zero, lowest
    first), up to ``limit``. [] when every need is met — nothing
    to say about needs then."""
    if not sample:
        return []
    needs = []
    for n in sample.get("needs") or []:
        if not isinstance(n, dict):
            continue
        focus = n.get("focus")
        level = n.get("level")
        if not isinstance(focus, int) or focus >= NEED_UNMET_FOCUS:
            continue
        if isinstance(level, int) and level <= 0:
            continue
        words = _need_words(n.get("need"))
        if words:
            needs.append({"need": words, "focus": focus})
    needs.sort(key=lambda n: n["focus"])
    return needs[:limit]


def dwarf_record(sample: dict[str, Any],
                 changes: list[dict[str, Any]] | None = None,
                 related_states: dict[int, dict[str, Any]] | None = None,
                 prev_relations: list[dict[str, Any]] | None = None,
                 prev_social: list[dict[str, Any]] | None = None
                 ) -> dict[str, Any]:
    """The structured per-dwarf record the diary feed and the
    snapshot's citizen section both use. ``sample`` is the latest
    unit_history sample (or a live citizen dict — same fields).
    ``related_states`` maps a relation's unit_id to that relation's
    current state {mood_name, stress_category, stress_level,
    changed} (from the Store's latest sample for that unit, or
    from the live citizens list), so the feed carries how each
    featured dwarf's relations are doing — the diary needs it to
    write the human consequence, and the snapshot's model needs it
    to decide. Relations not in the fort carry no state (their
    mood is not observable). ``prev_relations`` is the dwarf's
    relations at the previous sample: a relation in ``sample``
    but not in ``prev_relations`` is marked ``new_today``; one in
    both is pre-existing background. When ``prev_relations`` is
    None (first sighting) every relation is background — the
    dwarf is new to the record, the relations are not new today.
    Without this the diary cannot tell a devotion from before
    today (a god worshipped since embark) from a bond formed
    today, and it presents background as today's event.
    ``prev_social`` is the same rule for the social ties
    (friendships/grudges from hf_visual): a tie in ``sample`` but
    not in ``prev_social`` is new today. The record also carries
    the dwarf's salient personality facets and most recent
    emotions, so the feed has character to write from, not just a
    stat line."""
    changes = changes or []
    related_states = related_states or {}
    cat = sample.get("stress_category")
    prev_keys = set()
    if prev_relations is not None:
        prev_keys = set(_relations_by_key(
            {"relations": prev_relations}))
    rels = []
    for r in sample.get("relations") or []:
        if not isinstance(r, dict):
            continue
        entry: dict[str, Any] = {
            "type": r.get("type") or "",
            "name": r.get("name") or "",
            "in_fort": bool(r.get("in_fort")),
        }
        if prev_relations is not None:
            key = (str(r.get("type")),
                   r.get("histfig_id"))
            entry["new_today"] = key not in prev_keys
        else:
            entry["new_today"] = False
        if r.get("strength") is not None:
            entry["strength"] = r.get("strength")
        uid = r.get("unit_id")
        if isinstance(uid, int) and uid in related_states:
            st = related_states[uid]
            entry["mood"] = st.get("mood_name") or "none"
            entry["stress"] = stress_words(
                st.get("stress_category"))
            if st.get("changed"):
                entry["changed"] = True
        rels.append(entry)
    ties, outside = social_ties(sample, prev_social, related_states)
    sig = max((c.get("significance", 0) for c in changes),
              default=0)
    return {
        "unit_id": sample.get("unit_id", sample.get("id")),
        "name": sample.get("name") or "",
        "profession": sample.get("profession") or "",
        "mood": sample.get("mood_name") or "none",
        "stress": {
            "level": sample.get("stress"),
            "category": cat,
            "words": stress_words(cat),
        },
        "needs": most_unmet_needs(sample),
        "wounds": len(_wound_ids(sample)),
        "job": sample.get("job") or "",
        "relations": rels,
        "social": ties,
        "social_outside": outside,
        "traits": salient_traits(sample),
        "emotions": recent_emotions(sample),
        "goal": ((sample.get("goal") or {}).get("name") or "")
        if isinstance(sample.get("goal"), dict) else "",
        "skills": [{"skill": s.get("skill"),
                    "rating": s.get("rating") or ""}
                   for s in (sample.get("skills") or [])
                   if isinstance(s, dict) and s.get("skill")],
        "changes": [{"kind": c.get("kind"), "text": c.get("text"),
                     "significance": c.get("significance", 0)}
                    for c in changes],
        "significance": sig,
    }


def _notable_skills(skills: Any, limit: int = 6
                    ) -> list[dict[str, Any]]:
    """The dwarf's notable skills: Adequate or better (rating_num
    >= 2), best first, capped. Novice/Dabbling skills are not
    character — every dwarf has a long tail of them — so they never
    reach the store. A skill dict without a resolved name (None)
    is skipped, never stored as a blank."""
    out: list[dict[str, Any]] = []
    if not isinstance(skills, list):
        return out
    for s in skills:
        if not isinstance(s, dict):
            continue
        name = s.get("skill")
        num = s.get("rating_num")
        if not isinstance(name, str) or not name:
            continue
        if not isinstance(num, int) or num < 2:
            continue
        out.append({"skill": name,
                    "rating": s.get("rating") or "",
                    "rating_num": num})
    out.sort(key=lambda x: -x["rating_num"])
    return out[:limit]


def record_citizens(store: Any, tick: int,
                    citizens: list[dict[str, Any]] | None) -> None:
    """Record one sample per live citizen dict (the observation's
    citizen record) at ``tick``. The single mapping from a live
    citizen to a Store sample — used by the daemon's daily sampling
    and by the diary write (which captures the run-end state before
    building the feed, since no samples are taken while the loop is
    paused)."""
    for c in citizens or []:
        counters = c.get("counters") or {}
        stress = c.get("stress") or {}
        job = c.get("job")
        if isinstance(job, dict):
            job = job.get("type") or ""
        elif not isinstance(job, str):
            job = ""
        cat = stress.get("category")
        store.record_unit_history(
            tick, c.get("id", 0), pos=c.get("pos"), job=job,
            hunger=counters.get("hunger", 0) or 0,
            thirst=counters.get("thirst", 0) or 0,
            sleepiness=counters.get("sleepiness", 0) or 0,
            stress=stress.get("level", 0) or 0,
            wounds=c.get("wounds") or [],
            name=c.get("name") or "",
            profession=c.get("profession") or "",
            mood=c.get("mood") if isinstance(c.get("mood"), int)
            else -1,
            mood_name=c.get("mood_name") or "none",
            stress_category=cat if isinstance(cat, int) else -1,
            needs=c.get("needs") or [],
            relations=c.get("relations") or [],
            social=c.get("social") or [],
            traits=c.get("traits") or [],
            emotions=c.get("emotions") or [],
            goal=c.get("goal") if isinstance(c.get("goal"), dict)
            else {},
            skills=_notable_skills(c.get("skills")))
