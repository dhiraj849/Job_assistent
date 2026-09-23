from dataclasses import dataclass

from app.agent.state import AgentState


@dataclass
class AgentContext:
    state: AgentState