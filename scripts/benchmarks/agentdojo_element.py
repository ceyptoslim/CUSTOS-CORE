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
