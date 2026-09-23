from app.agent.state import AgentState


def request_approval(
    state: AgentState,
    job_title: str,
    company: str
) -> AgentState:

    print("\n===== HUMAN APPROVAL =====")

    print(f"Job: {job_title}")
    print(f"Company: {company}")

    state.approval_status = "pending"
    state.next_action = "review"

    answer = input(
        "\nDo you want to continue with this job? (yes/no): "
    )

    if answer.strip().lower() == "yes":

        state.approval_status = "approved"
        state.next_action = "apply"

    else:

        state.approval_status = "rejected"
        state.next_action = "stop"

    return state