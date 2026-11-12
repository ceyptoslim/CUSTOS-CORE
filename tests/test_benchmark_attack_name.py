"""The attack's ``{model}`` substitution is a measured parameter, not plumbing.

AgentDojo's ``important_instructions`` builds its injected sentence around a model
name and resolves that name by searching its own MODEL_NAMES table for a key that
appears in the pipeline's name. Neither frozen model id is a key, so the attack
refuses to construct: the first live Arm A invocation died on "No valid model name
not found in pipeline name `gemini-3.6-flash`". The OpenAI arm would have died the
same way, and no offline guard saw either, because the tests stub ``load_attack``.

So the series declares the string it will be scored with, per provider, and these
guards hold three things: the declared strings, the table entry that produces them
inside AgentDojo, and the runner's own check that what came back is what was
declared.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

import pathlib
import sys
import types

import pytest

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
SCRIPTS = ROOT / "scripts" / "benchmarks"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run_agentdojo_ab as runner  # noqa: E402
from agentdojo_guard import ATTACK_MODEL_NAME, DECLARED_ATTACK_MODEL_NAME  # noqa: E402

DECLARED = {"openai": "GPT-4", "google": "AI model developed by Google"}


def test_every_declared_attack_pair_names_a_string_agentdojo_accepts():
    """A declared pair must be usable, and only declared pairs may be recorded.

    Both land in the same test as the provider table because they are the same claim
    at two resolutions: the series records a string, and the string depends on the
    attack as well as the provider.
    """
    assert DECLARED_ATTACK_MODEL_NAME[("google", "direct")] == "the AI language model"
    assert (
        DECLARED_ATTACK_MODEL_NAME[("google", "important_instructions")]
        == ATTACK_MODEL_NAME["google"]
    )
    assert set(DECLARED_ATTACK_MODEL_NAME) == {
        ("openai", "important_instructions"),
        ("google", "important_instructions"),
        ("google", "direct"),
        # The local series declares the same neutral string for both attacks. It
        # is a different model family, so the injected sentence must not claim to
        # be either of the hosted ones.
        ("local", "important_instructions"),
        ("local", "direct"),
    }


def test_the_declared_strings_are_the_ones_the_series_records():
    # Pinned literally. A reworded substitution changes the injected text, which
    # changes what every case in the series measured.
    assert ATTACK_MODEL_NAME == DECLARED


def test_every_provider_used_by_the_prereg_has_a_declared_name():
    assert set(ATTACK_MODEL_NAME) == {"openai", "google"}
    assert set(runner.ATTACK_NAME_KEY) == set(ATTACK_MODEL_NAME)


def test_each_name_key_resolves_to_its_declared_string_inside_agentdojo():
    pytest.importorskip(
        "agentdojo", reason="benchmark package absent; the literal guards above still hold"
    )
    from agentdojo.attacks.base_attacks import MODEL_NAMES

    for provider, key in runner.ATTACK_NAME_KEY.items():
        assert key in MODEL_NAMES, (provider, key)
        assert MODEL_NAMES[key] == ATTACK_MODEL_NAME[provider], provider


def _fake_attack_module(monkeypatch, resolved_name):
    seen = {}

    def load_attack(attack_name, suite, pipeline):
        seen["pipeline_name"] = pipeline.name
        return types.SimpleNamespace(name=attack_name, model_name=resolved_name)

    module = types.ModuleType("agentdojo.attacks.attack_registry")
    module.load_attack = load_attack
    monkeypatch.setitem(sys.modules, "agentdojo.attacks.attack_registry", module)
    monkeypatch.setitem(sys.modules, "agentdojo.attacks", types.ModuleType("agentdojo.attacks"))
    return seen


def test_build_attack_restores_the_honest_pipeline_name_for_every_provider(monkeypatch):
    for provider in ("openai", "google"):
        seen = _fake_attack_module(monkeypatch, ATTACK_MODEL_NAME[provider])
        pipeline = types.SimpleNamespace(name="gemini-3.6-flash")
        attack = runner.build_attack("important_instructions", object(), pipeline, provider)
        # The constructor saw a name carrying the table key; the record does not.
        assert runner.ATTACK_NAME_KEY[provider] in seen["pipeline_name"]
        assert pipeline.name == "gemini-3.6-flash"
        assert attack.model_name == ATTACK_MODEL_NAME[provider]


def test_build_attack_refuses_when_the_provider_resolved_something_else(monkeypatch):
    # The check that makes the declaration binding rather than decorative: if the
    # attack substitutes a different name, the series would be scored on text it
    # never recorded.
    _fake_attack_module(monkeypatch, "GPT-3.5")
    pipeline = types.SimpleNamespace(name="gemini-3.6-flash")
    with pytest.raises(SystemExit) as excinfo:
        runner.build_attack("important_instructions", object(), pipeline, "google")
    assert excinfo.value.code == runner.EXIT_REFUSED
    assert pipeline.name == "gemini-3.6-flash"


def _cache():
    """The signature cache, in the environments that have AgentDojo installed.

    The element module imports AgentDojo at module level, and CI installs without
    the benchmark package, so these tests skip there rather than pretend to run.
    """
    pytest.importorskip("agentdojo", reason="benchmark package absent")
    from agentdojo_element import _ThoughtSignatures

    return _ThoughtSignatures()


# --- the thought signature seam -------------------------------------------


def _part(name, args, signature=None):
    call = types.SimpleNamespace(name=name, args=args)
    return types.SimpleNamespace(function_call=call, thought_signature=signature)


def test_a_signature_is_replayed_with_the_call_it_arrived_on():
    cache = _cache()
    returned = types.SimpleNamespace(
        candidates=[
            types.SimpleNamespace(
                content=types.SimpleNamespace(parts=[_part("read_file", {"path": "a"}, b"sig-1")])
            )
        ]
    )
    cache.remember(returned)

    replayed = _part("read_file", {"path": "a"})
    contents = [types.SimpleNamespace(role="model", parts=[replayed])]
    cache.attach(contents)
    assert replayed.thought_signature == b"sig-1"


def test_the_same_call_with_different_arguments_does_not_borrow_a_signature():
    cache = _cache()
    cache.remember(
        types.SimpleNamespace(
            candidates=[
                types.SimpleNamespace(
                    content=types.SimpleNamespace(parts=[_part("read_file", {"path": "a"}, b"sig-1")])
                )
            ]
        )
    )
    other = _part("read_file", {"path": "b"})
    cache.attach([types.SimpleNamespace(parts=[other])])
    assert other.thought_signature is None


def test_a_response_without_signatures_leaves_history_untouched():
    cache = _cache()
    cache.remember(
        types.SimpleNamespace(
            candidates=[types.SimpleNamespace(content=types.SimpleNamespace(parts=[_part("x", {})]))]
        )
    )
    part = _part("x", {})
    cache.attach([types.SimpleNamespace(parts=[part])])
    assert part.thought_signature is None


def test_attach_tolerates_no_contents():
    cache = _cache()
    assert cache.attach(None) is None
    assert cache._by_call == {}
