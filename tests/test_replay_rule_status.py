"""The replay rule is a decision, and the code has not caught up with it.

Issue 113 is closed as not planned, so the document is the whole artifact. Two
things can go wrong quietly and both are guarded here.

The document can stop saying what its own status is, which would leave a reader to
discover from a closed issue that nothing was built. And the code can implement part
of the rule without the document being updated, at which point the sentence "no
implementation yet" becomes false while every test stays green.

The second guard is the interesting one: it fails when the feature lands, which is
the intended signal rather than an accident, because the document has to change in
that same commit.
"""

import pathlib

DOC = pathlib.Path("docs/design/idempotent-decision-replay.md")
PY_FILES = [pathlib.Path("main.py")] + sorted(pathlib.Path("custos").glob("*.py"))


def _flat(path: pathlib.Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _code() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in PY_FILES)


class TestTheDocumentStatesItsOwnStatus:
    def test_it_says_the_issue_closed_without_the_work_being_done(self):
        doc = _flat(DOC)
        assert "closed as not planned rather than completed" in doc
        assert "artifact that closure rests on" in doc

    def test_it_names_the_reopen_condition(self):
        doc = _flat(DOC)
        assert "more than one tenant" in doc
        assert "decide twice" in doc


class TestTheCodeStillHasNoneOfIt:
    def test_no_caller_supplied_identifier_exists_yet(self):
        """If this fails, the field was implemented and the document is now wrong:
        update the status before deleting the guard."""
        assert "caller_request_id" not in _code(), (
            "a caller-supplied identifier is in the code, so the rule document's "
            "'no implementation yet' is false and binding-version work is owed"
        )

    def test_nothing_claims_idempotency_in_the_served_path(self):
        source = pathlib.Path("main.py").read_text(encoding="utf-8")
        assert "idempot" not in source.lower()
        assert "X-Request-ID" not in source, (
            "the served path reads a request id, which the rule says it may not do "
            "without a binding-version bump"
        )

    def test_the_binding_version_is_still_the_one_the_rule_assumes(self):
        from custos.audit import RECORD_BINDING_CURRENT

        assert RECORD_BINDING_CURRENT == 2, (
            f"binding version {RECORD_BINDING_CURRENT} means the rule document's "
            "field and version section needs rewriting"
        )
