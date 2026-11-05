#!/usr/bin/env bash
# SABOTAGE 011: Fabricate a policy citation for an engine that cannot be hashed
# (must turn the suite RED, or the run is recorded FAULTY-GREEN).
#
# One change: delete the honesty guard in engine_policy_digest(). With it gone,
# an unpinned OPA or hybrid engine gets a well-formed sha256 over the rules this
# process can see, and the audit record cites it as if it covered the decision.
# Nothing downstream can tell the difference: the value is 64 hex characters,
# carries the engine kind, and satisfies CUSTOS_AUDIT_REQUIRE_BOUND=1 — so the
# action that should have been refused for having no citable policy is allowed
# and recorded as fully cited.
#
# Pre-registered in docs/red-proof-records/sabotage-fabricated-citation/DESIGN.md
# (hash pinned in the workflow). Expected failing assertions, named in advance:
#   TestCitationCoversWhatItCites::test_opa_without_pin_cites_nothing
#   TestCitationCoversWhatItCites::test_hybrid_without_pin_cites_nothing
#   TestCitationCoversWhatItCites::test_malformed_pin_is_refused_not_hashed
#   TestCitationCoversWhatItCites::test_engine_digest_helper_refuses_unpinned_non_regex
#   TestRecordCarriesTheCitationItClaims::test_opa_record_emits_no_citation_when_unpinned
#   TestRequireBoundStillGovernsUncitableEngines::test_uncitable_allow_does_not_stand_under_require_bound
#
# NOT engineered to dodge tests; see DESIGN.md "Blindness" for the disclosed
# weaker-blindness position on this class.
set -euo pipefail

python3 - <<'INJECT'
import pathlib

path = pathlib.Path("custos/policy_citation.py")
source = path.read_text()

guard = (
    "    if engine_kind != REGEX_ENGINE and not opa_policy_digest:\n"
    "        return None\n"
)

if guard not in source:
    raise SystemExit(
        "[sabotage] FAILED TO APPLY - honesty guard not found in engine_policy_digest (code drift?)"
    )

path.write_text(source.replace(guard, "", 1))
INJECT

# Integrity guards: a silent no-op would fake a FAULTY-GREEN.
grep -q 'if engine_kind != REGEX_ENGINE and not opa_policy_digest:' custos/policy_citation.py && {
  echo "[sabotage] FAILED TO APPLY - honesty guard still present"; exit 1;
}
# The digest must still be computed and returned, or nothing is fabricated.
grep -q 'def engine_policy_digest' custos/policy_citation.py || {
  echo "[sabotage] FAILED TO APPLY - engine_policy_digest removed (wrong weakening applied)"; exit 1;
}
# And the value must still be a real digest over the consulted subset.
grep -q 'engine_citation_bytes' custos/policy_citation.py || {
  echo "[sabotage] FAILED TO APPLY - digest payload removed (wrong weakening applied)"; exit 1;
}
# A pin must still be honoured, so the class tests the unpinned case only.
grep -q 'opa_policy_digest' custos/policy_citation.py || {
  echo "[sabotage] FAILED TO APPLY - pin parameter removed (wrong weakening applied)"; exit 1;
}
echo "[sabotage] citation honesty weakened (unpinned engines cite a digest over the consulted subset)"
