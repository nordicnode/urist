"""Situation briefings (GOAL.md step 5, guidance layer 5).

When a strange mood, siege, caravan, or migrant wave starts, the
event carries a short briefing: what this is, what usually matters,
the options, and the cost of ignoring it — just in time, in a few
hundred tokens. The agent knows nothing about DF; the briefing is
the harness teaching it, in the moment, not in a prompt.

The briefing text is static (curated from the DF wiki, not
generated), so it costs nothing per tick. The wiki references are
the top pages for the event kind, fetched once and cached by kind
(the wiki is static data). The agent can pull the full page with
GET /v1/wiki/<slug> when it needs more than the briefing.

Briefings attach to attention items (see attention.build_attention):
an item whose kind has a briefing carries a ``briefing`` field.
"""

from __future__ import annotations

from typing import Any

# The briefing for each event kind. Keep each field to one or two
# sentences — the whole briefing is a few hundred tokens at most.
BRIEFINGS: dict[str, dict[str, str]] = {
    "new_arrival": {
        "what": ("A new creature has entered the map — a visitor, a "
                 "wild animal, or livestock. Visitors may petition "
                 "to stay, trade, or just pass through."),
        "matters": ("Whether it is hostile, and how close it is to "
                    "your dwarves. A wild animal near the fort is a "
                    "threat; a visitor at the edge is usually not."),
        "options": ("Watch it (query the unit for details), or "
                    "leave it alone. If it is hostile and close, "
                    "muster the military or seal the entrance."),
        "cost": ("Ignoring a hostile creature near your dwarves "
                 "risks a dwarf being attacked. Ignoring a harmless "
                 "visitor costs nothing."),
    },
    "citizen_new": {
        "what": ("New dwarves have arrived (a migrant wave). They "
                 "are citizens now and need food, drink, and a bed."),
        "matters": ("More mouths to feed and more hands to work. "
                    "Check drink and food stocks — a wave can halve "
                    "your runway. New dwarves need beds or they "
                    "sleep on the floor and grow unhappy."),
        "options": ("Assign labours (especially mining and "
                    "hauling), build beds, and make sure brewing "
                    "keeps up with the extra drinkers."),
        "cost": ("Ignoring a migrant wave means hungry, thirsty, "
                 "bedless dwarves — stress climbs and someone may "
                 "snap."),
    },
    "hostile": {
        "what": ("A hostile creature is on the map and close enough "
                 "to matter. It wants to kill your dwarves."),
        "matters": ("How many there are, how close they are, and "
                    "whether your military can handle them. A single "
                    "wild animal is a nuisance; a group is a fight."),
        "options": ("Muster the military, seal the entrance "
                    "(raise the drawbridge / lock the door), or let "
                    "the military intercept them away from civilians."),
        "cost": ("Ignoring a hostile near the fort risks dwarf "
                 "deaths. Dwarves will keep working outside unless "
                 "you stop them."),
    },
    "invasion": {
        "what": ("An invading force (goblins, or worse) is besieging "
                 "the fort. They will try to break in and kill "
                 "everyone."),
        "matters": ("Their numbers and whether they have siege "
                    "engines or trolls. Your military strength and "
                    "whether the entrance can be sealed."),
        "options": ("Seal the entrance immediately, muster the "
                    "military behind cover, and wait them out — "
                    "sieges end when the attackers give up or die. "
                    "Do not send civilians outside."),
        "cost": ("A siege left unanswered can destroy the fort. "
                 "Even a survived siege costs lives and months."),
    },
    "strange_mood": {
        "what": ("A dwarf has been taken by a strange mood. They "
                 "will claim a workshop and demand specific "
                 "materials to build an artifact."),
        "matters": ("Which materials they demand — the game tells "
                    "you when they claim the workshop. If the "
                    "materials are not available, the dwarf goes "
                    "insane (berserk, melancholy, or catatonic) and "
                    "usually dies."),
        "options": ("Provide the demanded materials (check the "
                    "workshop claim), or accept the loss. Do not "
                    "forbid the workshop they claimed."),
        "cost": ("An unfulfilled mood almost always kills the "
                 "dwarf, and a berserk dwarf can kill others."),
    },
    "caravan": {
        "what": ("A trade caravan has arrived at the depot. They "
                 "brought goods to trade and will leave after a "
                 "season."),
        "matters": ("What you need (food, drink, metal, cloth) "
                    "versus what you can spare (crafts, stone "
                    "goods). The broker does the trading."),
        "options": ("Trade at the depot (the broker handles it), "
                    "or ignore them and let them leave. Do not let "
                    "the depot be inaccessible or the caravan "
                    "leaves unhappy."),
        "cost": ("Ignoring a caravan costs nothing but the trade — "
                 "no penalty, just a missed opportunity."),
    },
    "unit_death": {
        "what": ("A dwarf has died. The cause is in the death "
                 "record (see /v1/memory/why/<unit_id>)."),
        "matters": ("WHY they died — thirst, hunger, a fight, a "
                 "fall. One death from thirst means the drink "
                 "supply is failing; fix the cause or more will "
                 "follow."),
        "options": ("Read the death diagnosis, fix the cause "
                    "(brew more drink, cook more food, deal with "
                    "the threat), and check the other dwarves' "
                    "counters."),
        "cost": ("An unaddressed cause kills again. Deaths also "
                 "hurt the mood of every dwarf who knew them."),
    },
    "low_drink": {
        "what": ("Drink is running out. Dwarves drink alcohol, not "
                 "water — without drink they dehydrate and die in "
                 "days. Drink is brewed at a Still from a brewable "
                 "plant (one plant + one empty barrel makes 5 "
                 "drink)."),
        "matters": ("How many days of drink are left (the snapshot "
                    "says), and whether a Still exists. No Still "
                    "means no brewing at all, however many plants "
                    "are in stock."),
        "options": ("Build a Still first if there is none, then "
                    "queue brew jobs at it. If plants or empty "
                    "barrels are short, gather plants or make "
                    "barrels at the Carpenter's workshop first — "
                    "the Materials section names the shortage."),
        "cost": ("Ignoring low drink kills dwarves of thirst. "
                 "The fort's most common killer is running out "
                 "of drink, not monsters."),
    },
    "low_food": {
        "what": ("Food is running out. Food is cooked at a Kitchen "
                 "from raw ingredients — an easy meal needs 2 "
                 "distinct food stacks — or gathered and fished "
                 "raw."),
        "matters": ("How many days of food are left, and whether "
                    "a Kitchen exists. Raw plants can be eaten "
                    "uncooked, but cooking stretches them further."),
        "options": ("Cook meals at the Kitchen (queue the cook "
                    "job), gather plants, or fish. If the kitchen "
                    "is missing, build one — it needs stone."),
        "cost": ("Ignoring low food starves dwarves. Hungry "
                 "dwarves work slowly, grow unhappy, and "
                 "eventually die."),
    },
}

# Cache of wiki references per event kind (the wiki is static).
_wiki_cache: dict[str, list[dict[str, str]]] = {}


def brief_for(kind: str) -> dict[str, Any] | None:
    """The briefing for an event kind, plus the top wiki pages for
    it (cached). Returns None when the kind has no briefing (the
    caller then attaches nothing — no guess)."""
    base = BRIEFINGS.get(kind)
    if base is None:
        return None
    briefing = dict(base)
    briefing["kind"] = kind
    if kind not in _wiki_cache:
        from . import wiki as wiki_mod
        results = wiki_mod.prefetch_for_event(kind)
        _wiki_cache[kind] = [
            {"slug": r.get("slug"), "title": r.get("title")}
            for r in results[:3]]
    briefing["wiki"] = _wiki_cache[kind]
    return briefing


def clear_wiki_cache() -> None:
    """Drop the cached wiki references (tests)."""
    _wiki_cache.clear()
