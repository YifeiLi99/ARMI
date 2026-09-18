"""Read the official SDK completion without auditing intermediate tool events."""

from dataclasses import dataclass

from openai_codex import TurnResult

from ._runner_contract import CodexRunnerViolation, CodexUsage


@dataclass(frozen=True, slots=True)
class SdkTurnEvidence:
    final_response: str
    usage: CodexUsage | None


def normalize_sdk_turn(result: TurnResult) -> SdkTurnEvidence:
    if result.status.value != "completed" or result.error is not None:
        raise CodexRunnerViolation("CODEX-SDK-TURN")
    if type(result.final_response) is not str or not result.final_response.strip():
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT")
    try:
        if len(result.final_response.encode("utf-8")) > 1024 * 1024:
            raise CodexRunnerViolation("CODEX-OUTPUT-LIMIT")
    except UnicodeEncodeError:
        raise CodexRunnerViolation("CODEX-FINAL-OUTPUT") from None
    usage = result.usage
    # Missing usage is not a failed task; the final SDK status owns completion.
    normalized_usage = (
        None
        if usage is None
        else CodexUsage(
            usage.total.input_tokens,
            usage.total.cached_input_tokens,
            usage.total.output_tokens,
        )
    )
    return SdkTurnEvidence(result.final_response, normalized_usage)
