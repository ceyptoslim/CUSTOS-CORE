"""The second provider is held to the same rules as the first.

Prereg v2 asks whether the gate behaves the same when a different provider's model
drives the pipeline. Four defects would have made that question unanswerable while
every test stayed green, so each one is guarded here.

A daily quota spent in the same shape as a per-minute throttle would have been
retried until the retry budget died, turning a wall into an interruption at the
end of a sitting instead of a resumption at the start of the next one. A per-minute
wall treated as a daily one would have thrown away progress that hours of patience
would have kept. A model name is an alias, so a series that never read the version
back could describe two models while claiming one. And an arm count borrowed from
the first prereg would have run the omitted third arm and called it the plan.

The provider tables are asserted rather than described: the value that changes is
the value the runner reads.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.


import pathlib
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts" / "benchmarks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import agentdojo_guard as guard  # noqa: E402
import agentdojo_resilience as resilience  # noqa: E402
import run_agentdojo_ab as runner  # noqa: E402

# A presence check is not enough: the CI import shape installs a module that raises
# on import rather than omitting the package, so this attempts the import the tests
# will actually need.
try:  # noqa: SIM105 - the except is the point
    import agentdojo.agent_pipeline  # noqa: F401

    HAS_AGENTDOJO = True
except Exception:  # noqa: BLE001
    HAS_AGENTDOJO = False


class QuotaClientError(Exception):
    """The shape google-genai raises: a code plus the provider's own payload."""

    def __init__(self, code, payload=None, message="quota"):
        super().__init__(message)
        self.code = code
        self.status = "RESOURCE_EXHAUSTED" if code == 429 else "ERROR"
        self.response_json = payload


def _quota_payload(quota_id):
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaMetric": "generativelanguage.googleapis.com/generate_content_free_tier_requests",
                            "quotaId": quota_id,
                        }
                    ],
                }
            ],
        }
    }


class Recorder:
    def __init__(self):
        self.delays = []

    def sleep(self, seconds):
        self.delays.append(round(seconds, 3))


class TestTheProviderTables:
    def test_each_provider_pins_one_model(self):
        assert guard.PROVIDER_MODELS["openai"] == "gpt-4.1-mini-2025-04-14"
        assert guard.PROVIDER_MODELS["google"] == "gemini-3.6-flash"
        assert guard.FROZEN_MODEL_ID == guard.PROVIDER_MODELS["openai"]
        assert guard.FROZEN_GOOGLE_MODEL_ID == guard.PROVIDER_MODELS["google"]

    def test_each_provider_names_the_key_it_needs(self):
        assert guard.PROVIDER_KEY_ENV == {
            "openai": "OPENAI_API_KEY",
            "google": "GEMINI_API_KEY",
        }

    def test_the_thinking_budget_is_frozen_only_where_it_exists(self):
        assert guard.PROVIDER_THINKING_BUDGET["google"] == 0
        assert guard.PROVIDER_THINKING_BUDGET["openai"] is None

    def test_each_provider_is_bound_to_its_own_prereg(self):
        assert guard.PREREG_BY_PROVIDER["openai"] == guard.FROZEN_PREREG_COMMIT
        assert guard.PREREG_BY_PROVIDER["google"] == guard.FROZEN_PREREG_COMMIT_V2
        assert guard.FROZEN_PREREG_COMMIT != guard.FROZEN_PREREG_COMMIT_V2


class TestWhatTheProviderRefusesBeforeItSpendsACall:
    def _config(self, tmp_path, **values):
        base = {
            "arm": guard.ARM_B1,
            "provider": "google",
            "model": guard.FROZEN_GOOGLE_MODEL_ID,
            "attack": "important_instructions",
            "case_list": tmp_path / "case-list-v1.txt",
            "out_dir": tmp_path / "out",
        }
        base.update(values)
        return guard.ArmConfig(**base)

    def test_an_unknown_provider_is_refused(self, tmp_path):
        problems = self._config(tmp_path, provider="anthropic").validate()
        assert problems and "unknown provider" in problems[0]

    def test_a_model_from_the_other_provider_is_refused(self, tmp_path):
        problems = self._config(tmp_path, model=guard.FROZEN_MODEL_ID).validate()
        assert problems and "not the frozen snapshot" in problems[0]
        assert guard.FROZEN_MODEL_ID in problems[0]

    def test_the_gemini_series_runs_all_three_arms(self, tmp_path):
        """B2 was refused while quota was the constraint; the addendum lifts it.

        The refusal was a guard against an arm nobody had declared, not against the
        arm itself. Once docs/benchmark/agentdojo-prereg-v2-b2-addendum.md declares
        it as a post-hoc control, the arm set has to move with the declaration, and
        an arm that is neither declared nor in the set must still be refused.
        """
        for arm in (guard.ARM_A, guard.ARM_B1, guard.ARM_B2):
            assert self._config(tmp_path, arm=arm).validate() == []

        problems = self._config(tmp_path, arm="B3").validate()
        assert problems and "unknown arm" in problems[0]

    def test_the_openai_series_still_runs_all_three_arms(self, tmp_path):
        for arm in (guard.ARM_A, guard.ARM_B1, guard.ARM_B2):
            assert self._config(
                tmp_path, provider="openai", model=guard.FROZEN_MODEL_ID, arm=arm
            ).validate() == []

    def _dir_with_manifest(self, tmp_path, provider, arm="A", payload=None):
        out = tmp_path / "out"
        out.mkdir(exist_ok=True)
        path = out / guard.MANIFEST_PATTERN.format(arm=arm)
        if payload is None:
            payload = {"provider": provider, "arm": arm}
        path.write_text(payload if isinstance(payload, str) else __import__("json").dumps(payload))
        return out, path

    def test_an_output_directory_holding_the_other_series_is_refused(self, tmp_path):
        out, _path = self._dir_with_manifest(tmp_path, "openai")
        problems = self._config(tmp_path, out_dir=out).validate()
        assert problems, "a google run accepted a directory holding an openai record"
        assert any("already holds a openai series record" in p for p in problems)
        assert any("own output directory" in p for p in problems)

    def test_the_refusal_names_the_collision_and_not_a_style_preference(self, tmp_path):
        # the two series share the arm letter, so the file that collides is the point
        out, _path = self._dir_with_manifest(tmp_path, "openai", arm=guard.ARM_A)
        problems = self._config(tmp_path, out_dir=out, arm=guard.ARM_A).validate()
        assert any("arm letters are shared" in p for p in problems)

    def test_its_own_series_may_reuse_the_directory(self, tmp_path):
        out, _path = self._dir_with_manifest(tmp_path, "google", arm=guard.ARM_A)
        assert self._config(tmp_path, out_dir=out, arm=guard.ARM_B1).validate() == []

    def test_an_unreadable_manifest_is_refused_rather_than_ignored(self, tmp_path):
        out, _path = self._dir_with_manifest(tmp_path, None, payload="{not json")
        problems = self._config(tmp_path, out_dir=out).validate()
        assert any("cannot be read" in p for p in problems)

    def test_a_manifest_without_a_provider_is_not_read_as_the_other_series(self, tmp_path):
        out, _path = self._dir_with_manifest(tmp_path, None, payload={"arm": "A"})
        assert self._config(tmp_path, out_dir=out).validate() == []

    def test_each_arm_names_its_own_manifest(self):
        # one manifest.json per directory would be overwritten by the next arm
        a = guard.MANIFEST_PATTERN.format(arm=guard.ARM_A)
        b = guard.MANIFEST_PATTERN.format(arm=guard.ARM_B1)
        assert a != b
        source = pathlib.Path(runner.__file__).read_text()
        assert "MANIFEST_PATTERN.format(arm=args.arm)" in source
        assert '"manifest.json"' not in source

    def test_the_openai_alias_is_still_refused_by_name(self, tmp_path):
        problems = self._config(
            tmp_path, provider="openai", model=guard.FORBIDDEN_MODEL_ALIAS
        ).validate()
        assert problems and "alias refused" in problems[0]


class TestWhichQuotaWasSpent:
    def test_a_daily_quota_is_read_from_the_providers_own_identifier(self):
        exc = QuotaClientError(429, _quota_payload("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))
        assert resilience.quota_exhaustion(exc) == "per_day"

    def test_a_per_minute_quota_is_read_the_same_way(self):
        exc = QuotaClientError(429, _quota_payload("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"))
        assert resilience.quota_exhaustion(exc) == "per_minute"

    def test_an_unlabelled_429_is_not_read_as_a_daily_wall(self):
        assert resilience.quota_exhaustion(QuotaClientError(429, None)) is None

    def test_a_non_429_is_never_a_quota_answer(self):
        assert resilience.quota_exhaustion(QuotaClientError(500, _quota_payload("PerDay"))) is None

    def test_the_answer_does_not_depend_on_the_payload_shape(self):
        nested = {"error": {"details": [{"violations": [{"quotaId": "x-PerDay-y"}]}]}}
        assert resilience.quota_exhaustion(QuotaClientError(429, nested)) == "per_day"


class TestTheRetryPolicyRespectsTheAnswer:
    def test_a_daily_quota_stops_the_sitting_without_sleeping(self):
        recorder = Recorder()
        policy = resilience.RetryPolicy(max_attempts=5, sleep=recorder.sleep)
        exc = QuotaClientError(429, _quota_payload("GenerateRequestsPerDayPerProjectPerModel-FreeTier"))

        with pytest.raises(resilience.QuotaExhausted) as caught:
            policy.run(lambda: (_ for _ in ()).throw(exc))

        assert caught.value.quota == "per_day"
        assert caught.value.attempts == 1
        assert recorder.delays == []

    def test_a_daily_quota_is_not_retried_even_once(self):
        calls = []

        def operation():
            calls.append(1)
            raise QuotaClientError(429, _quota_payload("PerDay"))

        policy = resilience.RetryPolicy(max_attempts=5, sleep=lambda _s: None)
        with pytest.raises(resilience.QuotaExhausted):
            policy.run(operation)
        assert len(calls) == 1

    def test_a_per_minute_wall_is_waited_out_and_succeeds(self):
        recorder = Recorder()
        policy = resilience.RetryPolicy(max_attempts=4, base_delay=1.0, sleep=recorder.sleep)
        attempts = {"n": 0}

        def operation():
            attempts["n"] += 1
            if attempts["n"] < 3:
                raise QuotaClientError(429, _quota_payload("GenerateRequestsPerMinutePerProjectPerModel-FreeTier"))
            return "served"

        assert policy.run(operation) == "served"
        assert len(recorder.delays) == 2

    def test_quota_exhausted_is_an_interruption_not_a_case_failure(self):
        # The runner's generic handler catches RunInterrupted; QuotaExhausted must
        # be caught before it so the journal says which wall it was.
        assert issubclass(resilience.QuotaExhausted, resilience.RunInterrupted)
        source = (SCRIPTS / "run_agentdojo_ab.py").read_text()
        assert source.index("except QuotaExhausted") < source.index("except RunInterrupted")


class TestTheJournalBindsTheProvider:
    def _binding(self, **overrides):
        values = {
            "arm": guard.ARM_A,
            "provider": "openai",
            "model": guard.FROZEN_MODEL_ID,
            "attack": "important_instructions",
            "case_list_sha256": "0" * 64,
            "case_count": 144,
            "allowlist": guard.ARM_ALLOWLISTS[guard.ARM_A],
            "prereg_commit": guard.FROZEN_PREREG_COMMIT,
            "suite_pin": guard.BANKING_SUITE_PIN,
        }
        values.update(overrides)
        return resilience.Journal.binding(**values)

    def test_the_same_plan_under_two_providers_is_two_identities(self):
        openai = resilience.Journal.digest(self._binding())
        google = resilience.Journal.digest(
            self._binding(
                provider="google",
                model=guard.FROZEN_GOOGLE_MODEL_ID,
                prereg_commit=guard.FROZEN_PREREG_COMMIT_V2,
            )
        )
        assert openai != google

    def test_a_journal_from_one_provider_refuses_to_resume_as_another(self, tmp_path):
        journal = resilience.Journal(tmp_path / "journal.jsonl")
        openai = self._binding()
        journal.start(openai)
        journal.append_case("UserTask0:InjectionTask0", {"case": "x", "utility": True}, [])
        with pytest.raises(resilience.JournalConflict):
            journal.open_resume(self._binding(provider="google", model=guard.FROZEN_GOOGLE_MODEL_ID))


class TestTheSeriesStopsWhenTheModelChangesUnderIt:
    def test_the_void_exit_code_is_its_own_code(self):
        assert runner.EXIT_VOID == 4
        assert runner.EXIT_VOID not in (0, runner.EXIT_REFUSED, runner.EXIT_INTERRUPTED)

    def test_one_version_is_not_mixed(self):
        recorder = types.SimpleNamespace(counts=lambda: {"gemini-3.6-flash": 12}, mixed=lambda: False)
        written = []
        journal = types.SimpleNamespace(append_abort=lambda *a, **k: written.append((a, k)))
        assert runner._void_on_mixed_versions(recorder, journal) is False
        assert written == []

    def test_a_second_version_voids_the_series_and_names_both(self):
        counts = {"gemini-3.6-flash": 9, "gemini-3.7-flash": 3}
        recorder = types.SimpleNamespace(
            counts=lambda: dict(counts), mixed=lambda: True, versions=lambda: sorted(counts)
        )
        written = []
        journal = types.SimpleNamespace(append_abort=lambda *a, **k: written.append((a, k)))

        assert runner._void_on_mixed_versions(recorder, journal) is True
        assert len(written) == 1
        args, kwargs = written[0]
        assert args == ("model_version_changed",)
        assert kwargs["versions"] == ["gemini-3.6-flash", "gemini-3.7-flash"]
        assert kwargs["counts"] == counts


@pytest.mark.skipif(not HAS_AGENTDOJO, reason="benchmark extra not installed")
class TestTheGoogleSeamInTheRealPackage:
    def test_the_upstream_retry_is_replaced_by_one_attempt(self):
        import agentdojo_element
        from agentdojo.agent_pipeline.llms import google_llm

        original = google_llm.chat_completion_request
        try:
            agentdojo_element.install_single_attempt_google_calls()
            assert google_llm.chat_completion_request is agentdojo_element._single_attempt_completion
            # Idempotent: a second install must not wrap the wrapper.
            agentdojo_element.install_single_attempt_google_calls()
            assert google_llm.chat_completion_request is agentdojo_element._single_attempt_completion
        finally:
            google_llm.chat_completion_request = original

    def test_one_attempt_means_one_call_to_the_provider(self):
        import agentdojo_element

        calls = []

        class Models:
            def generate_content(self, *, model, contents, config):
                calls.append(model)
                return "response"

        client = types.SimpleNamespace(models=Models())
        assert agentdojo_element._single_attempt_completion("m", client, [], None) == "response"
        assert calls == ["m"]

    def test_the_thinking_budget_and_the_version_are_carried_into_the_call(self):
        import agentdojo_element
        from google.genai import types as genai_types

        seen = {}

        class Models:
            def generate_content(self, *, model, contents, config):
                seen["config"] = config
                return types.SimpleNamespace(model_version="gemini-3.6-flash")

        recorder = agentdojo_element.ModelVersionRecorder()
        shim = agentdojo_element._RecordingClient(
            types.SimpleNamespace(models=Models()), recorder, 0
        )
        config = genai_types.GenerateContentConfig(temperature=0.0, max_output_tokens=16)
        shim.models.generate_content(model="gemini-3.6-flash", contents=[], config=config)

        assert seen["config"].thinking_config.thinking_budget == 0
        assert seen["config"].temperature == 0.0
        assert seen["config"].max_output_tokens == 16
        assert recorder.counts() == {"gemini-3.6-flash": 1}
        assert recorder.mixed() is False

    def test_the_wrapper_keeps_the_client_alive(self):
        # Measured defect: holding only ``client.models`` let the Client be
        # collected, and the next send raised "the client has been closed".
        import agentdojo_element

        client = types.SimpleNamespace(
            models=types.SimpleNamespace(generate_content=lambda **_: None)
        )
        shim = agentdojo_element._RecordingClient(client, agentdojo_element.ModelVersionRecorder(), 0)
        assert shim._client is client

    def test_an_unreported_version_is_recorded_rather_than_assumed(self):
        import agentdojo_element

        class Models:
            def generate_content(self, *, model, contents, config):
                return types.SimpleNamespace()

        recorder = agentdojo_element.ModelVersionRecorder()
        shim = agentdojo_element._RecordingClient(
            types.SimpleNamespace(models=Models()), recorder, None
        )
        shim.models.generate_content(model="m", contents=[], config=None)
        assert recorder.counts() == {"unreported": 1}
