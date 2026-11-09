"""The pipeline element that installs the guarded runtime.

Kept apart from ``agentdojo_guard`` so the guard itself imports nothing from the
benchmark package. This module is the only file in the pair that requires
AgentDojo to be installed, and it is imported solely by the runner and by the
integration smoke test.

Placement is ``ToolsExecutionLoop([GuardedRuntimeElement(...), ToolsExecutor()])``.
The element wraps the runtime on the way through, the executor then dispatches
against the wrapper, and every later loop iteration sees the same wrapper because
the wrapped runtime is returned in place of the original.
"""
# Copyright (C) 2024-2026 Tavares Heath Sr. (doing business as FroLife Productions)
# Licensed under the GNU Affero General Public License v3.0 (AGPL-3.0)
# See LICENSE file for details. Commercial license available upon request.

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from agentdojo.agent_pipeline import BasePipelineElement
from agentdojo.functions_runtime import FunctionsRuntime

from agentdojo_guard import (
    ARM_A,
    DecisionRecord,
    GuardedRuntime,
    RunRefused,
)


class GuardedRuntimeElement(BasePipelineElement):
    """Wraps the runtime in a gate proxy before the executor reaches it."""

    name = "custos_guard"

    def __init__(
        self,
        gate: Any,
        arm: str,
        case_id: str = "",
        sink: Optional[Callable[[DecisionRecord], None]] = None,
    ) -> None:
        if arm == ARM_A:
            raise RunRefused("arm A must not install the guard element")
        self._gate = gate
        self._arm = arm
        self._case_id = case_id
        self._sink = sink

    def set_case(self, case_id: str) -> None:
        """Label the decisions that follow with the case being run."""
        self._case_id = case_id

    def query(
        self,
        query: str,
        runtime: FunctionsRuntime,
        env: Any = None,
        messages: Sequence[Any] = (),
        extra_args: Optional[dict] = None,
    ) -> tuple[str, Any, Any, Sequence[Any], dict]:
        extra_args = extra_args or {}
        if isinstance(runtime, GuardedRuntime):
            # Second pass through the loop. Rewrapping would produce nested
            # proxies and one decision record per wrap, which is the defect this
            # check exists for.
            return query, runtime, env, messages, extra_args
        guarded = GuardedRuntime(
            runtime, self._gate, self._arm, case_id=self._case_id, sink=self._sink
        )
        return query, guarded, env, messages, extra_args


class ModelVersionRecorder:
    """Every model version the provider reported, counted per version.

    Prereg v2 pins the Gemini model by name rather than by snapshot, because no
    dated snapshot is callable. A name is an alias: on November 8, 2026 the same
    name served 3.5 and then 3.6 inside half an hour. The recorder is what makes
    that visible instead of silent, and ``mixed`` is what the runner stops on.
    """

    def __init__(self) -> None:
        self._counts: dict[str, int] = {}

    def record(self, version: Optional[str]) -> None:
        key = version or "unreported"
        self._counts[key] = self._counts.get(key, 0) + 1

    def versions(self) -> list[str]:
        return sorted(self._counts)

    def counts(self) -> dict[str, int]:
        return dict(self._counts)

    def mixed(self) -> bool:
        return len(self._counts) > 1


class _RecordingModels:
    """Delegates to the provider's models endpoint, adding the frozen knob.

    The thinking budget cannot be reached through ``GoogleLLM``'s constructor: it
    builds one ``GenerateContentConfig`` and exposes no hook. Sitting under the
    client instead of copying the element's ``query`` keeps this file to the seam
    and leaves message conversion where AgentDojo maintains it.
    """

    def __init__(self, models: Any, recorder: ModelVersionRecorder, thinking_budget: Optional[int]):
        self._models = models
        self._recorder = recorder
        self._thinking_budget = thinking_budget

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        if config is not None and self._thinking_budget is not None:
            from google.genai import types as genai_types

            config = config.model_copy(
                update={
                    "thinking_config": genai_types.ThinkingConfig(
                        thinking_budget=self._thinking_budget
                    )
                }
            )
        response = self._models.generate_content(model=model, contents=contents, config=config)
        self._recorder.record(getattr(response, "model_version", None))
        return response


class _RecordingClient:
    """Holds the provider client for the life of the run, not just its models endpoint.

    Keeping only ``client.models`` is not enough: the ``Client`` owns the HTTP
    transport, so dropping the reference lets it be collected and the next call
    fails with "the client has been closed". Measured here, not guessed: with only
    ``models`` held, a single-call smoke failed on its first send.
    """

    def __init__(self, client: Any, recorder: ModelVersionRecorder, thinking_budget: Optional[int]):
        self._client = client
        self.models = _RecordingModels(client.models, recorder, thinking_budget)


def _single_attempt_completion(model: str, client: Any, contents: Any, generation_config: Any) -> Any:
    return client.models.generate_content(
        model=model, contents=contents, config=generation_config
    )


def install_single_attempt_google_calls() -> None:
    """Remove AgentDojo's own retry from the Google path.

    Upstream wraps the request in three tenacity attempts with exponential waits
    up to forty seconds, which would hide provider failures inside a benchmark
    result and overlap the runner's own journaled retries. The pre-registration
    puts retries in one place, so this replaces the wrapped function with a single
    attempt and the runner's policy owns everything above it. Idempotent.
    """
    from agentdojo.agent_pipeline.llms import google_llm as module

    if module.chat_completion_request is not _single_attempt_completion:
        module.chat_completion_request = _single_attempt_completion


def build_google_llm(
    model: str,
    api_key: str,
    recorder: ModelVersionRecorder,
    thinking_budget: Optional[int] = 0,
) -> Any:
    """A GoogleLLM with the frozen sampling, the frozen thinking budget, and a recorder."""
    from google import genai

    from agentdojo.agent_pipeline import GoogleLLM

    install_single_attempt_google_calls()
    client = genai.Client(api_key=api_key)
    return GoogleLLM(
        model,
        _RecordingClient(client, recorder, thinking_budget),
        temperature=0.0,
    )
