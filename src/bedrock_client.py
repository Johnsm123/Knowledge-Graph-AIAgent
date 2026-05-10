"""
AWS Bedrock ChatCompletionClient adapter for AutoGen.

Wraps boto3 bedrock-runtime Converse API to implement the AutoGen
ChatCompletionClient protocol so the 6-agent HEDIS pipeline can use
Amazon Nova Pro (or any Bedrock model) instead of Azure OpenAI.
"""

import json
import logging
import time
import random
from typing import Any, AsyncGenerator, Mapping, Optional, Sequence, Union

import boto3
from autogen_core.models import (
    ChatCompletionClient,
    CreateResult,
    LLMMessage,
    RequestUsage,
)
from autogen_core.tools import Tool, ToolSchema
from autogen_core.models import ModelInfo
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class BedrockChatCompletionClient(ChatCompletionClient):
    """AutoGen-compatible model client backed by AWS Bedrock Converse API."""
    
    component_type = "model"
    component_config_schema = BaseModel
    component_provider_override = "bedrock_client.BedrockChatCompletionClient"
 
    def __init__(
        self,
        model_id: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-1",
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ):
        self._model_id = model_id
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._total_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)
        self._actual_usage = RequestUsage(prompt_tokens=0, completion_tokens=0)

        self._client = boto3.client(
            "bedrock-runtime",
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

        self._model_info = ModelInfo(
            vision=False,
            function_calling=True,
            json_output=True,
            family="nova",
            structured_output=False,
            multiple_system_messages=False,
        )

    @property
    def model_info(self) -> ModelInfo:
        return self._model_info

    @property
    def capabilities(self) -> ModelInfo:
        return self._model_info

    # ── Convert AutoGen LLMMessage objects to Bedrock Converse format ────────

    def _convert_messages(self, messages: Sequence[LLMMessage]):
        """Convert AutoGen messages to Bedrock Converse API format.

        Returns (system_prompts, conversation_messages).
        """
        system_prompts = []
        conversation = []

        for msg in messages:
            # Handle different AutoGen message types
            role = getattr(msg, "role", None) or getattr(msg, "type", "user")
            if hasattr(msg, "source"):
                role = "assistant" if msg.source != "user" else "user"

            # Extract text content
            content = ""
            if hasattr(msg, "content"):
                if isinstance(msg.content, str):
                    content = msg.content
                elif isinstance(msg.content, list):
                    content = " ".join(
                        part.get("text", str(part)) if isinstance(part, dict) else str(part)
                        for part in msg.content
                    )
                else:
                    content = str(msg.content)

            if not content.strip():
                continue

            # Route system messages separately (Bedrock Converse uses a dedicated system field)
            msg_type = type(msg).__name__
            if msg_type == "SystemMessage" or role == "system":
                system_prompts.append({"text": content})
            elif msg_type == "AssistantMessage" or role == "assistant":
                conversation.append({
                    "role": "assistant",
                    "content": [{"text": content}],
                })
            else:
                # UserMessage, FunctionExecutionResultMessage, etc. → user
                conversation.append({
                    "role": "user",
                    "content": [{"text": content}],
                })

        # Bedrock requires alternating user/assistant roles — merge consecutive same-role
        merged = []
        for msg in conversation:
            if merged and merged[-1]["role"] == msg["role"]:
                merged[-1]["content"].extend(msg["content"])
            else:
                merged.append(msg)

        # Bedrock requires conversation to start with "user" role
        if merged and merged[0]["role"] != "user":
            merged.insert(0, {"role": "user", "content": [{"text": "Begin analysis."}]})

        return system_prompts, merged

    # ── Core create method (async required by AutoGen) ───────────────────────

    async def create(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Union[Tool, ToolSchema]] = [],
        json_output: Optional[Union[bool, type[BaseModel]]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token=None,
    ) -> CreateResult:
        system_prompts, conversation = self._convert_messages(messages)

        if not conversation:
            conversation = [{"role": "user", "content": [{"text": "Analyze and respond."}]}]

        kwargs = {
            "modelId": self._model_id,
            "messages": conversation,
            "inferenceConfig": {
                "maxTokens": extra_create_args.get("max_tokens", self._max_tokens),
                "temperature": extra_create_args.get("temperature", self._temperature),
            },
        }
        if system_prompts:
            kwargs["system"] = system_prompts

        max_retries = 6
        base_delay = 2.0
        for attempt in range(max_retries):
            try:
                response = self._client.converse(**kwargs)
                break
            except self._client.exceptions.ThrottlingException as exc:
                if attempt == max_retries - 1:
                    logger.error(f"Bedrock Converse throttled after {max_retries} retries: {exc}")
                    raise
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Bedrock throttled (attempt {attempt + 1}/{max_retries}), retrying in {delay:.1f}s")
                time.sleep(delay)
            except Exception as exc:
                logger.error(f"Bedrock Converse error: {exc}")
                raise

        # Extract response text
        output = response.get("output", {})
        message = output.get("message", {})
        content_blocks = message.get("content", [])
        text = " ".join(b.get("text", "") for b in content_blocks if "text" in b)

        # Extract usage
        usage_data = response.get("usage", {})
        prompt_tokens = usage_data.get("inputTokens", 0)
        completion_tokens = usage_data.get("outputTokens", 0)

        usage = RequestUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )
        self._total_usage = RequestUsage(
            prompt_tokens=self._total_usage.prompt_tokens + prompt_tokens,
            completion_tokens=self._total_usage.completion_tokens + completion_tokens,
        )
        self._actual_usage = usage

        stop_reason = response.get("stopReason", "end_turn")
        # Map Bedrock stopReason → AutoGen CreateResult finish_reason
        # Valid values: 'stop', 'length', 'function_calls', 'content_filter', 'unknown'
        _FINISH_MAP = {
            "end_turn": "stop",
            "stop_sequence": "stop",
            "max_tokens": "length",
            "tool_use": "function_calls",
            "content_filtered": "content_filter",
            "guardrail_intervened": "content_filter",
        }
        finish = _FINISH_MAP.get(stop_reason, "unknown")

        return CreateResult(
            finish_reason=finish,
            content=text,
            usage=usage,
            cached=False,
        )

    async def create_stream(
        self,
        messages: Sequence[LLMMessage],
        *,
        tools: Sequence[Union[Tool, ToolSchema]] = [],
        json_output: Optional[Union[bool, type[BaseModel]]] = None,
        extra_create_args: Mapping[str, Any] = {},
        cancellation_token=None,
    ) -> AsyncGenerator[Union[str, CreateResult], None]:
        # Fallback: just call create and yield the result
        result = await self.create(
            messages,
            tools=tools,
            json_output=json_output,
            extra_create_args=extra_create_args,
            cancellation_token=cancellation_token,
        )
        yield result

    def count_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Union[Tool, ToolSchema]] = []
    ) -> int:
        # Rough estimation: ~4 chars per token
        total = 0
        for msg in messages:
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                total += len(content)
            elif isinstance(content, list):
                total += sum(len(str(p)) for p in content)
        return total // 4

    def remaining_tokens(
        self, messages: Sequence[LLMMessage], *, tools: Sequence[Union[Tool, ToolSchema]] = []
    ) -> int:
        return max(0, 300000 - self.count_tokens(messages, tools=tools))

    def actual_usage(self) -> RequestUsage:
        return self._actual_usage

    def total_usage(self) -> RequestUsage:
        return self._total_usage

    async def close(self) -> None:
        pass
