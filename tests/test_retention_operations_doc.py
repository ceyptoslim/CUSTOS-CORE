"""The runbook stays bound to the refusals it tells an operator to expect.

An operations document that quotes messages the code no longer emits is worse
than no document: it is a guide to a refusal that will not happen, matched by an
operator during a rollback. These guards hold the quotes to the source and fail
when a new refusal is added without a runbook row that names it.
"""

import pathlib
import re

DOC = pathlib.Path("docs/RETENTION-OPERATIONS.md")
SOURCE = pathlib.Path("custos/content_retention.py")

# One entry per `raise RetentionConfigRefused(` in the module, keyed by a fragment
# of the message the code builds and the phrase the runbook uses for it. Both
# halves are asserted, so deleting either side of the pair goes red.
REFUSALS = [
    ("is not a retention mode", "is not a retention mode"),
    ("with nowhere to store", "with nowhere to store"),
    ("Refusing to ", "create it yourself"),
    ("is not a directory", "is not a directory"),
    ("nothing can erase it", "nothing can erase it"),
    ("configured store the process does not use", "configured store the process does not use"),
    ("admin credential with no surface", "admin credential with no surface"),
]


def _norm(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


class TestTheRunbookMatchesTheCode:
    def test_every_refusal_site_has_a_runbook_row(self):
        source = SOURCE.read_text(encoding="utf-8")
        sites = len(re.findall(r"raise RetentionConfigRefused\(", source))
        assert sites == len(REFUSALS), (
            f"the module raises {sites} refusals and the runbook table lists "
            f"{len(REFUSALS)}; a new refusal needs a row that names what to unset"
        )

    def test_each_quoted_message_is_still_in_the_code(self):
        source = SOURCE.read_text(encoding="utf-8")
        for fragment, _ in REFUSALS:
            assert fragment in source, f"the code no longer builds {fragment!r}"

    def test_each_runbook_row_describes_a_message_that_exists(self):
        doc = _norm(DOC)
        for fragment, guidance in REFUSALS:
            assert guidance in doc, f"the runbook lost the advice for {fragment!r}"

    def test_every_variable_the_module_reads_is_documented(self):
        source = SOURCE.read_text(encoding="utf-8")
        doc = _norm(DOC)
        for name in ("CUSTOS_CONTENT_RETENTION", "CUSTOS_CONTENT_STORE_DIR",
                     "CUSTOS_RETENTION_ADMIN_TOKEN"):
            assert name in source and name in doc, f"{name} is undocumented"


class TestTheRollbackKeepsItsOrder:
    def test_the_rollback_says_erase_before_switching_off(self):
        doc = _norm(DOC)
        assert "Erase what you are obliged to erase first" in doc
        assert "Once the mode is off, that endpoint refuses" in doc

    def test_it_states_that_off_alone_will_not_start(self):
        doc = _norm(DOC)
        assert "will not start" in doc
        assert "unset" in doc.lower()

    def test_it_names_the_consequence_for_files_left_on_disk(self):
        """The trap the refusal does not catch: unsetting the variable and leaving
        the files behind. Nothing reads them and nothing erases them."""
        doc = _norm(DOC)
        assert "still on disk" in doc
        assert "body-missing" in doc

    def test_it_says_what_the_erasure_does_not_reach(self):
        doc = _norm(DOC)
        assert "does not reach a copy of the store taken before it" in doc
        assert "another tenant" in doc
