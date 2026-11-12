"""Wiring guards for the local (OpenAI-compatible) provider.

None of these tests measures a model. They answer three narrower questions, each
of which has to be true before any local arm may run:

1. the stub speaks the shape the client library expects, and the client parses a
   tool call out of it;
2. the runner refuses a local arm with no endpoint, and refuses an endpoint for a
   pinned provider, because the endpoint is part of what a record has to name;
3. the local series cannot validate while its pre-registration is unfrozen.

The third is the one that protects the record. A run may not cite a document that
has not been frozen by a merge, so the placeholder commit fails closed rather than
being accepted as a string.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
BENCH = REPO / "scripts" / "benchmarks"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(BENCH))

import agentdojo_guard as guard  # noqa: E402
from local_openai_stub import start_stub  # noqa: E402


@pytest.fixture()
def stub():
    """A stub server on a free port, torn down after the test."""
    server, _thread, base_url = start_stub(port=0, model="stub-model")
    try:
        yield server, base_url
    finally:
        server.shutdown()
        server.server_close()


def test_stub_answers_models_with_the_pinned_alias(stub):
    server, base_url = stub
    with urllib.request.urlopen(f"{base_url}/models", timeout=5) as response:
        payload = json.loads(response.read())
    assert payload["data"][0]["id"] == "stub-model"


def test_stub_answers_a_chat_completion_with_a_tool_call(stub):
    server, base_url = stub
    request = json.dumps(
        {
            "model": "stub-model",
            "temperature": 0.0,
            "messages": [{"role": "user", "content": "what is my balance"}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_balance",
                        "parameters": {"type": "object", "properties": {}},
                    },
                }
            ],
        }
    ).encode()
    http_request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=request,
        headers={"Content-Type": "application/json", "Authorization": "Bearer stub"},
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=5) as response:
        payload = json.loads(response.read())
    call = payload["choices"][0]["message"]["tool_calls"][0]["function"]
    assert call["name"] == "get_balance"
    assert json.loads(call["arguments"]) == {"user_id": "7"}
    assert payload["model"] == "stub-model"


def test_client_library_parses_the_stub_tool_call(stub):
    """The real client, the real request shape, a stubbed server."""
    openai = pytest.importorskip("openai")
    server, base_url = stub
    client = openai.OpenAI(base_url=base_url, api_key="stub", max_retries=0)
    completion = client.chat.completions.create(
        model="stub-model",
        temperature=0.0,
        messages=[{"role": "user", "content": "what is my balance"}],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "get_balance",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )
    message = completion.choices[0].message
    assert message.tool_calls[0].function.name == "get_balance"
    assert json.loads(message.tool_calls[0].function.arguments) == {"user_id": "7"}
    # The request the stub saw is what the runner would send: the pinned model at
    # temperature 0 with the tool schemas declared.
    seen = server.RequestHandlerClass.calls[-1]
    assert seen["model"] == "stub-model"
    assert seen["temperature"] == 0.0
    assert seen["tools"] == ["get_balance"]


def test_local_provider_refuses_without_an_endpoint(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(BENCH / "run_agentdojo_ab.py"),
            "--arm", "A",
            "--attack", "important_instructions",
            "--provider", "local",
            "--model", guard.PROVIDER_MODELS["local"],
            "--out", str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "CUSTOS_LOCAL_API_KEY": "stub"},
        cwd=str(REPO),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "--base-url" in (result.stdout + result.stderr)
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*"))


def test_endpoint_is_refused_for_a_pinned_provider(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(BENCH / "run_agentdojo_ab.py"),
            "--arm", "A",
            "--attack", "important_instructions",
            "--provider", "openai",
            "--model", guard.PROVIDER_MODELS["openai"],
            "--base-url", "http://127.0.0.1:9/v1",
            "--out", str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "OPENAI_API_KEY": "unused"},
        cwd=str(REPO),
    )
    assert result.returncode == 2, result.stdout + result.stderr
    assert "--base-url is only meaningful" in (result.stdout + result.stderr)


def test_local_series_cannot_validate_while_its_prereg_is_unfrozen(tmp_path):
    assert guard.PREREG_BY_PROVIDER["local"] == guard.FROZEN_PREREG_COMMIT_V4
    assert guard.FROZEN_PREREG_COMMIT_V4 == "PENDING_PREREG_V4_COMMIT"
    config = guard.ArmConfig(
        arm="A",
        model=guard.PROVIDER_MODELS["local"],
        attack="important_instructions",
        case_list="docs/benchmark/case-list-v1.txt",
        out_dir=str(tmp_path / "out"),
        provider="local",
    )
    problems = config.validate()
    assert any("no frozen pre-registration commit" in p for p in problems), problems


def test_frozen_series_still_validate(tmp_path):
    """The guard above must not become a blocker for the frozen series."""
    for provider in ("openai", "google"):
        config = guard.ArmConfig(
            arm="A",
            model=guard.PROVIDER_MODELS[provider],
            attack="important_instructions",
            case_list="docs/benchmark/case-list-v1.txt",
            out_dir=str(tmp_path / provider),
            provider=provider,
        )
        assert config.validate() == [], (provider, config.validate())


def test_local_series_declares_its_attack_model_name():
    """The injected sentence carries this string, so it is part of the experiment."""
    declared = guard.DECLARED_ATTACK_MODEL_NAME[("local", "important_instructions")]
    assert declared == "the AI language model"
    assert guard.PROVIDER_THINKING_BUDGET["local"] is None
