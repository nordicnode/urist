"""Offline tests for the diary rebuild (scripts/rebuild_diary.py).

The rebuild rewrites diary.md from the recorded history. The
2026-11-27 quality pass found its feeds were wrong in three ways
the validator then blessed: run decisions were SUMMED across all
replays of a day (04-01 claimed 28 beds, 35 barrels), the
per-dwarf record was an older day's (04-05: six wounded from
04-01, the day's snapshots say two), and the June/July entries
carried 04-01's wounds and needs into a fort of ten. These tests
pin the fixes: one run per date, snapshot/lite group counts, and
the prompt notes that mark a stale record as stale.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "scripts"))

from dfagent_harness import diary  # noqa: E402
import rebuild_diary as rb  # noqa: E402
from test_diary_feed import FakeStore  # noqa: E402


def _write_log(log_dir, name, records):
    path = Path(log_dir) / name
    path.write_text("\n".join(json.dumps(r) for r in records)
                    + "\n")
    return path


class TestRunDecisionsByDate(unittest.TestCase):
    def test_one_run_per_date_diary_attempt_wins(self):
        # 04-01 was played by many runs; the feed must carry ONE
        # run's decisions — the latest that attempted a diary
        # write — not the sum of all of them.
        with tempfile.TemporaryDirectory() as tmp:
            _write_log(tmp, "m1-20261127-070000.jsonl", [
                {"kind": "run_start", "mock": False},
                {"kind": "start_tick", "date": "125-04-01"},
                {"kind": "action", "name": "queue_job",
                 "reason": "queued make_bed x1 on building #7",
                 "model_reason": "", "ok": True},
            ])
            _write_log(tmp, "m1-20261127-073557.jsonl", [
                {"kind": "run_start", "mock": False},
                {"kind": "start_tick", "date": "125-04-01"},
                {"kind": "action", "name": "queue_job",
                 "reason": "queued make_barrel x2 on building #7",
                 "model_reason": "", "ok": True},
                {"kind": "diary", "ok": True},
            ])
            got = rb._run_decisions_by_date(Path(tmp))
        self.assertEqual(list(got), ["125-04-01"])
        self.assertEqual(
            [d["decision"] for d in got["125-04-01"]],
            ["queue make_barrel x2 at building #7"])

    def test_garbage_start_tick_date_dropped(self):
        # Some run files carry a "Population: ..." string in the
        # start_tick date. Those runs cannot be attributed to a
        # day; their decisions are dropped, not filed under a
        # junk key.
        with tempfile.TemporaryDirectory() as tmp:
            _write_log(tmp, "m1-20261127-090000.jsonl", [
                {"kind": "run_start", "mock": False},
                {"kind": "start_tick",
                 "date": "Population: 7 citizens (2 idle, "
                         "1 wounded), 25 animals"},
                {"kind": "action", "name": "queue_job",
                 "reason": "queued make_bed x1 on building #7",
                 "model_reason": "", "ok": True},
            ])
            got = rb._run_decisions_by_date(Path(tmp))
        self.assertEqual(got, {})

    def test_mock_runs_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_log(tmp, "m1-20261127-070000.jsonl", [
                {"kind": "run_start", "mock": True},
                {"kind": "start_tick", "date": "125-04-01"},
                {"kind": "action", "name": "queue_job",
                 "reason": "queued make_bed x1 on building #7",
                 "model_reason": "", "ok": True},
            ])
            got = rb._run_decisions_by_date(Path(tmp))
        self.assertEqual(got, {})


class TestSnapshotGroupCounts(unittest.TestCase):
    def test_first_and_last_with_a_population_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_log(tmp, "m1-20261127-063000.jsonl", [
                {"kind": "run_start", "mock": False},
                {"kind": "snapshot", "text":
                 "Erushtathtat, 125-04-05\n"
                 "Population: 7 citizens (5 idle, 2 wounded)"},
                {"kind": "snapshot", "text":
                 "Erushtathtat, 125-04-05\n"
                 "Population: 7 citizens (4 idle, 2 wounded)"},
                {"kind": "snapshot", "text":
                 "Erushtathtat, 125-04-06\n"
                 "Population: 7 citizens (4 idle, 1 wounded)"},
                # No Population line: ignored, not a group count.
                {"kind": "snapshot", "text":
                 "Erushtathtat, 125-04-05\nNo citizens here."},
            ])
            got = rb._snapshot_group_counts(Path(tmp))
        self.assertEqual(got["125-04-05"], {
            "start": {"population": 7, "idle": 5, "wounded": 2},
            "end": {"population": 7, "idle": 4, "wounded": 2}})
        self.assertEqual(got["125-04-06"]["end"]["wounded"], 1)

    def test_mock_run_snapshots_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_log(tmp, "m1-20261127-063000.jsonl", [
                {"kind": "run_start", "mock": True},
                {"kind": "snapshot", "text":
                 "Erushtathtat, 125-04-05\n"
                 "Population: 7 citizens (5 idle, 2 wounded)"},
            ])
            got = rb._snapshot_group_counts(Path(tmp))
        self.assertEqual(got, {})


class TestLiteDwarfFeed(unittest.TestCase):
    def _store(self):
        # 125-06-12's day (181200-182399): full samples from
        # 04-01 only, lite samples at tick 171344 (125-06-03).
        # Lor wounded, Ral fishing and thirsty, one migrant
        # never named.
        store = FakeStore()
        store.add_unit(1, 101323, name="Lor Mebzuthkin",
                       profession="Miner", mood_name="none",
                       stress_category=-1, stress=0, needs=[],
                       wounds=[{"id": 4, "parts": 2}], job="Miner",
                       relations=[], thirst=2000, hunger=4000)
        store.add_unit(1, 171344, name="", profession="",
                       mood_name="none", stress_category=-1,
                       stress=0, needs=[], wounds=[{"id": 7}],
                       job="", relations=[], thirst=5000,
                       hunger=30000)
        store.add_unit(2, 101323, name="Ral Dalzatolin",
                       profession="Fisherdwarf", mood_name="none",
                       stress_category=-1, stress=0, needs=[],
                       wounds=[], job="Fish", relations=[],
                       thirst=2000, hunger=4000)
        store.add_unit(2, 171344, name="", profession="",
                       mood_name="none", stress_category=-1,
                       stress=0, needs=[], wounds=[], job="Fish",
                       relations=[], thirst=25000, hunger=30000)
        store.add_unit(3, 171344, name="", profession="",
                       mood_name="none", stress_category=-1,
                       stress=0, needs=[], wounds=[], job="",
                       relations=[], thirst=9000, hunger=30000)
        return store

    def test_counts_from_lite_samples(self):
        store = self._store()
        lite = rb._lite_dwarf_feed(store, 181200, 10, 125)
        recs = lite["records"]
        counts = lite["counts"]
        self.assertEqual(lite["record_tick"], 171344)
        self.assertEqual(
            diary.date_str(lite["record_tick"], 125), "125-06-03")
        self.assertEqual(lite["unnamed"], 1)
        self.assertEqual(lite["sampled"], 3)
        self.assertEqual(lite["span_ticks"], 0)
        self.assertEqual(lite["in_day_sampled"], 0)
        self.assertEqual(lite["in_day_wounded"], 0)
        by_key = {g["key"]: g for g in counts}
        # Lor is the only wounded one; Ral the only thirsty one
        # (thirst 25000, past the 20000 threshold — a derived
        # drink need, not a game-reported one).
        self.assertEqual(by_key["wounded"]["count"], 1)
        self.assertEqual(by_key["wounded"]["total"], 10)
        self.assertEqual(by_key["wounded"]["names"],
                         ["Lor Mebzuthkin"])
        self.assertEqual(by_key["thirsty"]["count"], 1)
        self.assertEqual(by_key["thirsty"]["names"],
                         ["Ral Dalzatolin"])
        # The migrant is in the records as an unnamed migrant,
        # so the complement is honest about who is not wounded.
        self.assertIn("an unnamed migrant",
                      by_key["wounded"]["not_names"])
        names = [r["name"] for r in recs]
        self.assertIn("an unnamed migrant", names)
        self.assertEqual(
            [r for r in recs
             if r["name"] == "Ral Dalzatolin"][0]["needs"],
            [{"need": "drink", "focus": -1, "level": 1}])

    def test_no_samples_returns_none(self):
        store = FakeStore()
        self.assertIsNone(rb._lite_dwarf_feed(store, 181200, 7, 125))

    def test_day_has_full_samples(self):
        store = self._store()
        # Full samples are 04-01 only: no full sample inside
        # 06-12 (181200-182399) or inside 04-05 (105600-106799).
        self.assertFalse(rb._day_has_full_samples(store, 181200))
        self.assertFalse(rb._day_has_full_samples(store, 105600))
        # But 04-01 (100800-101999) has one.
        self.assertTrue(rb._day_has_full_samples(store, 100800))

    def test_mixed_span_is_reported(self):
        # 06-02's shape: two dwarves sampled today, the rest
        # from an old sample round — the span is weeks, and the
        # in-day poll is 2 sampled, 1 wounded. The caller clears
        # the record on a span this wide; the helper must report
        # the numbers it needs.
        store = FakeStore()
        store.add_unit(1, 103996, name="Lor Mebzuthkin",
                       profession="Miner", mood_name="none",
                       stress_category=-1, stress=0, needs=[],
                       wounds=[{"id": 4}], job="", relations=[],
                       thirst=2000, hunger=4000)
        store.add_unit(1, 169650, name="", profession="",
                       mood_name="none", stress_category=-1,
                       stress=0, needs=[], wounds=[{"id": 7}],
                       job="", relations=[], thirst=3732,
                       hunger=28391)
        store.add_unit(2, 103996, name="Ral Dalzatolin",
                       profession="Fisherdwarf", mood_name="none",
                       stress_category=-1, stress=0, needs=[],
                       wounds=[], job="Fish", relations=[],
                       thirst=2000, hunger=4000)
        lite = rb._lite_dwarf_feed(store, 169200, 10, 125)
        self.assertEqual(lite["record_tick"], 169650)
        self.assertEqual(lite["span_ticks"], 169650 - 103996)
        self.assertGreater(lite["span_ticks"], rb._LITE_STALE_TICKS)
        self.assertEqual(lite["in_day_sampled"], 1)
        self.assertEqual(lite["in_day_wounded"], 1)
        self.assertEqual(lite["sampled"], 2)


class TestRebuildPromptNotes(unittest.TestCase):
    def _feed(self, **extra):
        summary = {
            "date": "125-06-12", "date_words": "12th of Galena",
            "season": "Summer", "stocks_start": {}, "stocks_end": {},
            "deaths": [], "arrivals": 0, "threats": [],
            "observations": [], "decisions": [],
        }
        feed = {"summary": summary, "dwarves": [],
                "group_counts": [], "threads": [],
                "recent_entries": []}
        feed.update(extra)
        return feed

    def test_lite_record_date_note(self):
        msgs = diary.diary_prompt(self._feed(
            lite_dwarf_record_date="125-06-04"))
        user = msgs[1]["content"]
        self.assertIn("125-06-04", user)
        self.assertIn("not today's measurement", user)
        self.assertIn("Attribute its facts to that day", user)

    def test_unnamed_citizens_note(self):
        msgs = diary.diary_prompt(self._feed(unnamed_citizens=3))
        user = msgs[1]["content"]
        self.assertIn("3 of the citizens are migrants", user)
        self.assertIn("Do not invent names for them", user)

    def test_no_record_note_names_last_record(self):
        msgs = diary.diary_prompt(self._feed(
            no_per_dwarf_samples=True,
            last_dwarf_record_date="125-04-02"))
        user = msgs[1]["content"]
        self.assertIn("No per-dwarf record exists for this day",
                      user)
        self.assertIn("The last per-dwarf record is from 125-04-02",
                      user)

    def test_partial_record_note(self):
        feed = self._feed(
            no_per_dwarf_samples=True,
            last_dwarf_record_date="125-04-03",
            partial_dwarf_record={"sampled": 2, "wounded": 1})
        feed["summary"]["stocks_end"] = {"population": 10}
        msgs = diary.diary_prompt(feed)
        user = msgs[1]["content"]
        self.assertIn("Only 2 of the 10 citizens were recorded today "
                      "(1 wounded, 1 unmarked)", user)
        self.assertIn("Do not claim anything about the unrecorded "
                      "dwarves", user)


if __name__ == "__main__":
    unittest.main()


class TestSplitEntries(unittest.TestCase):
    def test_heading_suffix_dropped(self):
        entries = rb._split_entries(
            "# Diary of Erushtathtat\n\n"
            "## 125-06-22 — 22nd of Galena, 125\n\n"
            "Nothing happened today.\n")
        self.assertEqual(entries, [
            ("125-06-22", "Nothing happened today.")])

    def test_gap_body_starts_with_gap(self):
        entries = rb._split_entries(
            "# Diary of Erushtathtat\n\n"
            "## 125-04-06 — 6th of Hematite, 125\n\n"
            "GAP — no entries exist.\n")
        self.assertTrue(entries[0][1].startswith("GAP —"))


class TestLedgerSourceFallback(unittest.TestCase):
    """A second run over AI-written entries has no ledger lines
    to read — the AI entries dropped them — and the Store's only
    trend sample is 04-01's (drink 39). Without the pre-rewrite
    ledger fallback, a June day's feed would read drink 39, food
    32, pop 7. The gap marker must also survive a second run: it
    is a note, not an entry to rewrite."""

    def test_ledger_recovered_from_pre_rewrite_copy(self):
        import io
        from contextlib import redirect_stdout
        from dfagent_harness.store import Store
        from dfagent_harness.planner import Journal

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            logs = Path(tmp) / "logs"
            logs.mkdir()
            # The Store's only trend sample: 04-01's numbers.
            store = Store(state / "world.db")
            store.sample_trend(100800, "drink", 39)
            store.sample_trend(100800, "food", 32)
            store.sample_trend(100800, "wood", 124)
            store.sample_trend(100800, "population", 7)
            store.close()
            Journal(state / "journal.db").close()
            # Current diary: an AI entry with no ledger line.
            (state / "diary.md").write_text(
                "# Diary of Erushtathtat\n\n"
                "## 125-06-22 — 22nd of Galena, 125\n\n"
                "Nothing happened today. No drink.\n")
            # Pre-rewrite diary: the template entry with its ledger.
            source = Path(tmp) / "pre.md"
            source.write_text(
                "# Diary of Erushtathtat\n\n"
                "## 125-06-22 — 22nd of Galena, 125\n\n"
                "Drink: 0 Food: 23 Wood: 211 Stone: 0 Citizens: 10.\n")
            out = io.StringIO()
            with redirect_stdout(out):
                rb.rebuild(state, logs, dry_run=True, ai=False,
                           ledger_source=source)
            self.assertIn("125-06-22: stocks from ledger",
                          out.getvalue())
            # The rendered entry carries the recovered ledger,
            # not the Store's 04-01 numbers.
            self.assertIn("Drink: 0", out.getvalue())
            self.assertNotIn("Drink: 39", out.getvalue())

    def test_gap_marker_skipped(self):
        import io
        from contextlib import redirect_stdout
        from dfagent_harness.store import Store
        from dfagent_harness.planner import Journal

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "state"
            state.mkdir()
            logs = Path(tmp) / "logs"
            logs.mkdir()
            Store(state / "world.db").close()
            Journal(state / "journal.db").close()
            (state / "diary.md").write_text(
                "# Diary of Erushtathtat\n\n"
                "## 125-04-06 — 6th of Hematite, 125\n\n"
                "GAP — no entries exist for 125-04-06 to 125-06-01.\n")
            out = io.StringIO()
            with redirect_stdout(out):
                rb.rebuild(state, logs, dry_run=True, ai=False)
            self.assertIn("125-04-06: gap marker, skipped",
                          out.getvalue())
            # The marker is still rewritten after the loop (the
            # dry run prints it), not consumed by the loop.
            self.assertIn("gap marker (dry run, not written)",
                          out.getvalue())
