#!/usr/bin/env python3
"""Validate the file:line citations in design documents against the source tree.

A design document that cites `custos/action_gate.py:281` is making a claim about a
specific line of code. Evidence for that claim is text an unfriendly reader can find at
exactly that line, so the rule enforced here is:

    every citation must sit next to a verbatim fragment, and the cited
    line range must contain one of the fragments bound to that citation.

Two failure modes are worth separating, because only the second is dangerous:

  * a citation with no quoted fragment is not checkable, so it fails rather than
    passing by default;
  * a fragment that no longer sits on the cited range means the citation points at
    real code that no longer says what the sentence says it says.

Anchors bind positionally: the fragment that follows a citation belongs to it, so
`file.py:310` "policy_digest=cited_digest" and `:342` "policy_digest=cited_digest" are
checked separately rather than either fragment satisfying both. When a citation ends a
line or a table cell, the fragment before it is used instead, which is how a table row
naming its evidence last still works.

Documents opt in with the marker `<!-- citation-check: on -->`. Opt-in keeps the guard
from retroactively failing documents written before the rule existed; those get
converted one at a time, with the conversion reviewed.

Usage:
    python scripts/check_doc_citations.py                # every opted-in doc
    python scripts/check_doc_citations.py --selftest     # mutation self-check
    python scripts/check_doc_citations.py docs/design/x.md
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "<!-- citation-check: on -->"
DOC_GLOB = "docs/design/*.md"

# A full citation names a path; the shorthand form relies on the last path on the line.
CITATION = re.compile(r"(?P<path>[A-Za-z0-9_./-]+\.py):(?P<start>\d+)(?:-(?P<end>\d+))?")
SHORTHAND = re.compile(r"(?<![\w./:-]):(?P<start>\d+)(?:-(?P<end>\d+))?")
TICKED = re.compile(r"`([^`]+)`")
QUOTED = re.compile(r'"([^"]{8,})"')

MIN_ANCHOR_CHARS = 8


def squash(text: str) -> str:
    """Collapse whitespace so a fragment that wraps across source lines still matches."""
    return re.sub(r"\s+", " ", text).strip()


def anchor_variants(anchor: str) -> list[str]:
    """Trailing punctuation in prose is not part of the code, so try with and without it."""
    base = squash(anchor)
    out = {base, base.rstrip(".,:;"), base.rstrip(".,:;)\"'")}
    return [v for v in out if len(v) >= MIN_ANCHOR_CHARS]


@dataclass(frozen=True)
class Citation:
    path: str
    start: int
    end: int
    doc_line: int
    anchors: tuple[str, ...]


@dataclass(frozen=True)
class Problem:
    doc_line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.doc_line}: {self.message}"


def _looks_like_citation(text: str) -> bool:
    stripped = text.strip()
    return bool(CITATION.fullmatch(stripped) or SHORTHAND.fullmatch(stripped))


def anchors_in(text: str) -> list[str]:
    found = [m.group(1).strip() for m in TICKED.finditer(text)]
    found += [m.group(1).strip() for m in QUOTED.finditer(text)]
    return [a for a in found if not _looks_like_citation(a) and len(a) >= MIN_ANCHOR_CHARS]


def _spans(line: str) -> list[tuple[int, int, str, int, int]]:
    """Citation spans on one line as (char_start, char_end, path, start, end)."""
    spans: list[tuple[int, int, str, int, int]] = []
    file_at = ""
    for m in CITATION.finditer(line):
        file_at = m.group("path")
        spans.append((m.start(), m.end(), file_at, int(m.group("start")), int(m.group("end") or m.group("start"))))
    for m in SHORTHAND.finditer(line):
        if any(s <= m.start() < e for s, e, *_ in spans):
            continue
        if not file_at:
            continue
        spans.append(
            (m.start(), m.end(), file_at, int(m.group("start")), int(m.group("end") or m.group("start")))
        )
    # Extend each span over its wrapping backticks so the segment boundaries used for
    # anchor binding land between code spans, not inside one. Without this a citation
    # ending mid-span leaves an orphan backtick at the start of the next segment and
    # every later ticked fragment on the line is mis-paired.
    widened: list[tuple[int, int, str, int, int]] = []
    for start_at, end_at, path, start, end in spans:
        if start_at > 0 and end_at < len(line) and line[start_at - 1] == "`" and line[end_at] == "`":
            start_at -= 1
            end_at += 1
        widened.append((start_at, end_at, path, start, end))
    return sorted(widened)


def citations_in(markdown: str) -> list[Citation]:
    out: list[Citation] = []
    for lineno, line in enumerate(markdown.splitlines(), start=1):
        spans = _spans(line)
        for index, (start_at, end_at, path, start, end) in enumerate(spans):
            next_at = spans[index + 1][0] if index + 1 < len(spans) else len(line)
            anchors = anchors_in(line[end_at:next_at])
            if not anchors and index == len(spans) - 1:
                prev_at = spans[index - 1][1] if index else 0
                anchors = anchors_in(line[prev_at:start_at])
            out.append(Citation(path, start, end, lineno, tuple(anchors)))
    return out


def _resolve(path: str, root: Path) -> tuple[Path | None, str | None]:
    direct = root / path
    if direct.is_file():
        return direct, None
    nested = root / "custos" / path
    if nested.is_file():
        return nested, None
    matches = [p for p in root.glob(f"**/{Path(path).name}") if ".git" not in p.parts]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        return None, f"{path} does not exist"
    return None, f"{path} is ambiguous: {', '.join(str(m.relative_to(root)) for m in matches[:4])}"


def check_document(doc_path: Path, root: Path = ROOT) -> list[Problem]:
    markdown = doc_path.read_text(encoding="utf-8")
    problems: list[Problem] = []
    cache: dict[Path, list[str]] = {}

    def source_for(target: Path) -> list[str]:
        if target not in cache:
            cache[target] = target.read_text(encoding="utf-8").splitlines()
        return cache[target]

    for cite in citations_in(markdown):
        target, error = _resolve(cite.path, root)
        if error or target is None:
            problems.append(Problem(cite.doc_line, error or f"{cite.path} does not exist"))
            continue
        source = source_for(target)
        if cite.start < 1 or cite.end > len(source) or cite.end < cite.start:
            problems.append(
                Problem(cite.doc_line, f"{cite.path}:{cite.start}-{cite.end} is outside the file ({len(source)} lines)")
            )
            continue
        if not cite.anchors:
            problems.append(
                Problem(cite.doc_line, f"{cite.path}:{cite.start} has no quoted fragment, so the claim is not checkable")
            )
            continue
        cited = squash("\n".join(source[cite.start - 1 : cite.end]))
        if not any(variant in cited for anchor in cite.anchors for variant in anchor_variants(anchor)):
            problems.append(
                Problem(
                    cite.doc_line,
                    f"{cite.path}:{cite.start}-{cite.end} does not contain its fragment "
                    f"({', '.join(repr(a) for a in cite.anchors[:2])})",
                )
            )
    return problems


def opted_in(root: Path = ROOT) -> list[Path]:
    return [p for p in sorted(root.glob(DOC_GLOB)) if MARKER in p.read_text(encoding="utf-8")]


def run(paths: list[Path], root: Path = ROOT) -> int:
    total = 0
    for path in paths:
        cites = citations_in(path.read_text(encoding="utf-8"))
        problems = check_document(path, root)
        rel = path.relative_to(root) if path.is_relative_to(root) else path
        if problems:
            total += len(problems)
            print(f"FAIL {rel} ({len(problems)} of {len(cites)} citations)")
            for problem in problems:
                print(f"  {problem}")
        else:
            print(f"OK   {rel} ({len(cites)} citations)")
    return total


def _first_citation_span(markdown: str) -> tuple[int, int, str, int, int] | None:
    for line in markdown.splitlines():
        spans = _spans(line)
        if spans:
            return spans[0]
    return None


def _mutations(markdown: str) -> dict[str, str]:
    """Derive one rot case per failure mode from the document itself.

    Nothing here names a line number: a self-test that pins the numbers it exists to keep
    honest fails every time the document is re-mapped, and the natural fix becomes
    editing the test. Mutations are found by shape instead.
    """
    out: dict[str, str] = {}
    first = _first_citation_span(markdown)
    if first is not None:
        _, end_at, path, start, _ = first
        head = markdown[: markdown.index(f"{path}:{start}", 0)]
        tail = markdown[markdown.index(f"{path}:{start}", 0) + len(f"{path}:{start}") :]
        out["line number past the end of the file"] = f"{head}{path}:99999{tail}"
        out["file that does not exist"] = f"{head}custos/nonexistent.py:{start}{tail}"
        out["line number on a line that does not hold the fragment"] = f"{head}{path}:1{tail}"

    # A citation whose fragment is deleted is not checkable, so it must fail.
    anchored = re.search(r"(`[A-Za-z0-9_./-]+\.py:\d+(?:-\d+)?`)\s+(`[^`]{8,}`|\"[^\"]{8,}\")", markdown)
    if anchored:
        out["citation with no quoted fragment"] = (
            markdown[: anchored.start()] + anchored.group(1) + markdown[anchored.end() :]
        )

    # Positional binding: a duplicate fragment elsewhere in the file must not validate a
    # citation that points at the wrong line. The mutation keeps the fragment and moves
    # only the line number to a neighbouring line, which is a stale citation: the text is
    # findable somewhere in the file, so a search-based checker would pass it, while the
    # cited line does not hold it.
    for cite in citations_in(markdown):
        if not cite.anchors or cite.start != cite.end:
            continue
        wrong = cite.start + 1
        if wrong > 4000:
            continue
        needle = f"{cite.path}:{cite.start}"
        if needle not in markdown:
            continue
        out["wrong line whose fragment exists elsewhere"] = markdown.replace(
            needle, f"{cite.path}:{wrong}", 1
        )
        break
    return out


def selftest(root: Path = ROOT) -> int:
    """Prove the checker fails on each way a citation can rot, and passes when it should."""
    doc = root / "docs/design/pre-execution-boundary-accurate.md"
    original = doc.read_text(encoding="utf-8")
    failures = 0
    if check_document(doc, root):
        print("SELFTEST FAIL: the unmodified document should pass")
        failures += 1

    mutations = _mutations(original)
    if len(mutations) < 4:
        print(f"SELFTEST FAIL: only {len(mutations)} rot cases derivable from the document")
        return failures + 1

    tmp = root / "docs/design/.selftest-citation.md"
    for name, mutated in mutations.items():
        if mutated == original:
            print(f"SELFTEST FAIL: mutation '{name}' did not change the document")
            failures += 1
            continue
        tmp.write_text(mutated, encoding="utf-8")
        problems = check_document(tmp, root)
        print(f"SELFTEST {'OK  ' if problems else 'FAIL'} caught: {name}")
        failures += 0 if problems else 1
        if name == "citation with no quoted fragment":
            # Caught for the stated reason, not by collateral damage elsewhere in the doc.
            right = any("no quoted fragment" in p.message for p in problems)
            print(f"SELFTEST {'OK  ' if right else 'FAIL'} no-fragment case reports its own reason")
            failures += 0 if right else 1
    tmp.unlink(missing_ok=True)

    print("SELFTEST PASS" if not failures else f"SELFTEST FAIL ({failures})")
    return failures


def main(argv: list[str]) -> int:
    if "--selftest" in argv:
        return 1 if selftest() else 0
    targets = [Path(a) for a in argv if not a.startswith("-")]
    if not targets:
        targets = opted_in()
    if not targets:
        print(f"no documents carry {MARKER}")
        return 0
    return 1 if run(targets) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
