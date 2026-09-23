import json
from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    ResultMessage,
)

from app.models.job_match import JobMatchResult


class ClaudeCodeProvider:

    async def generate(self, prompt: str) -> str:

        response = ""

        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                output_format={
                    "type": "json_schema",
                    "schema": JobMatchResult.model_json_schema()
                }
            )
        ):
            if isinstance(message, ResultMessage):
                response = message.result
        data = json.loads(response)
        return JobMatchResult.model_validate(data)