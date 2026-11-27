"""Point the harness wiki module at the repo-local fixture dfq.py.

The offline suite must run on a fresh checkout (CI has no DF wiki
export, so ~/workspace/df-wiki-export/dfq.py does not exist there).
The fixture (tests/fixtures/wiki/dfq.py) is a tiny dfq.py-compatible
tool over a small corpus of real DF pages, so the offline tests
exercise the real subprocess -> JSON -> prefetch -> briefing path
hermetically instead of shelling out to the external export. The
real export is still exercised by the live wiki route test and by
dfq.py's own accuracy eval.
"""

import sys
from pathlib import Path
from unittest import mock

from dfagent_harness import wiki

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "wiki"
FIXTURE_DFQ = FIXTURE_DIR / "dfq.py"


class WikiFixtureMixin:
    """TestCase mixin: run the wiki path against the fixture.

    Inherit it FIRST (class Foo(WikiFixtureMixin, unittest.TestCase))
    and call super().setUp() from any setUp the class defines, so
    the mixin's setUp runs.
    """

    def setUp(self):
        super().setUp()
        self._wiki_fixture_patches = [
            mock.patch.object(wiki, "DFQ", FIXTURE_DFQ),
            mock.patch.object(wiki, "WIKI_DIR", FIXTURE_DIR),
            mock.patch.object(wiki, "VENV_PYTHON", sys.executable),
        ]
        for patch in self._wiki_fixture_patches:
            patch.start()

    def tearDown(self):
        for patch in reversed(self._wiki_fixture_patches):
            patch.stop()
        super().tearDown()
