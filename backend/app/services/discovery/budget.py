from __future__ import annotations

import asyncio
import json

import tiktoken

from app.services.finding_runtime.bridge import RuntimeLLMModelClient


class BudgetExhausted(RuntimeError):
    pass


class PhaseBudget:
    def __init__(self, tokens, turns):
        self.tokens, self.turns = max(0, int(tokens)), max(0, int(turns))
        self.used_tokens = self.used_turns = self.reserved = 0
        self.exhausted = False
        self.lock = asyncio.Lock()

    @property
    def available(self):
        return (
            not self.exhausted
            and self.used_turns < self.turns
            and self.tokens - self.used_tokens - self.reserved > 512
        )

    async def reserve(self, input_tokens):
        async with self.lock:
            output = min(4096, self.tokens - self.used_tokens - self.reserved - input_tokens)
            if self.used_turns >= self.turns or output < 512:
                self.exhausted = True
                raise BudgetExhausted("Phase model budget exhausted; unfinished work is deferred")
            self.reserved += input_tokens + output
            self.used_turns += 1
            return output

    async def settle(self, reservation, actual):
        async with self.lock:
            self.reserved -= reservation
            self.used_tokens += actual or reservation


class BudgetedModelClient(RuntimeLLMModelClient):
    def __init__(self, *, llm_service, budget):
        super().__init__(llm_service=llm_service, agent_type="finding")
        self.budget = budget

    async def stream_complete(self, **kwargs):
        messages = self._build_messages(
            system_prompt=kwargs.get("system_prompt"),
            recon_payload=kwargs.get("recon_payload", {}),
            transcript=kwargs.get("transcript", []),
            tool_definitions=kwargs.get("tool_definitions", []),
            tool_message_format=self._resolve_tool_message_format(),
        )
        # Include schemas and protocol overhead, not just the last user message.
        encoded = json.dumps(
            [messages, kwargs.get("tool_definitions", [])], ensure_ascii=False, default=str
        )
        estimate = (
            int(
                len(tiktoken.get_encoding("cl100k_base").encode(encoded, disallowed_special=()))
                * 1.15
            )
            + 256
        )
        output = await self.budget.reserve(estimate)
        actual = 0
        kwargs["max_output_tokens_override"] = output
        try:
            async for event in super().stream_complete(**kwargs):
                if event.get("type") == "done":
                    usage = event.get("usage", {})
                    actual = int(
                        usage.get("total_tokens")
                        or (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0))
                    )
                yield event
        finally:
            await self.budget.settle(estimate + output, actual)
