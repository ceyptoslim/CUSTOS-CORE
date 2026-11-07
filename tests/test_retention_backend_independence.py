"""The retention modules do not know which audit backend wrote the record.

The claim this guards is structural and was, until now, prose: nothing in
`custos/retention.py` or `custos/content_retention.py` names an audit backend.
It is the reason retention is expected to behave the same on PostgreSQL as on
SQLite, and it was made in a summary a reader cannot check from the summary. A
claim whose subject is the code and whose statement is prose is the defect class
this series keeps producing, so it becomes a test.

What this does NOT establish: that the behaviour is identical on every backend.
Nothing branches is an argument about the code. It is not the measurement, which
is issue 149, and the two are kept apart on purpose.
"""

import pathlib

RETENTION = pathlib.Path("custos/retention.py")
CONTENT_RETENTION = pathlib.Path("custos/content_retention.py")

# Identifiers that would mean the retention path had learned about a backend.
# The content store's own `sqlite3` use is not one of them: that is the store it
# is, not a branch on where the records live.
BACKEND_MARKERS = (
    "PostgreSQL",
    "Postgres",
    "SQLiteBackend",
    "PostgreSQLBackend",
    "InMemoryBackend",
    "DATABASE_URL",
    "audit_backend",
    "backend_type",
)


def _sources():
    for path in (RETENTION, CONTENT_RETENTION):
        yield path, path.read_text(encoding="utf-8")


class TestTheRetentionPathDoesNotBranchOnBackend:
    def test_neither_module_mentions_a_backend(self):
        hits = []
        for path, source in _sources():
            for marker in BACKEND_MARKERS:
                if marker in source:
                    hits.append(f"{path.name}: {marker}")
        assert not hits, (
            "the retention path now knows about an audit backend, which means the "
            "structural argument for backend independence no longer holds: "
            + ", ".join(hits)
        )

    def test_the_two_modules_exist_where_the_claim_says_they_are(self):
        assert RETENTION.exists() and CONTENT_RETENTION.exists()

    def test_the_content_store_is_still_its_own_sqlite_file(self):
        """The one store this path owns, split across the two modules: the store
        implementation in retention.py, its configuration in content_retention.py.
        The first version of this test asserted both against the second file and
        failed for the right reason, which is the misaimed-guard class caught by
        running it rather than by reading it."""
        assert "sqlite3" in RETENTION.read_text(encoding="utf-8")
        assert "CUSTOS_CONTENT_STORE_DIR" in CONTENT_RETENTION.read_text(encoding="utf-8")
