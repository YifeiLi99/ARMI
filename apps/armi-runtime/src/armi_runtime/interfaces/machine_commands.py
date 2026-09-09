"""Machine argument/result adaptation for the shared Creator application."""

from __future__ import annotations

from typing import Any, cast

from armi_codex.api import CodexDelegationViolation, CodexModel, CodexReasoningEffort
from armi_effect.api import EffectArtifactKind, EffectViolation
from armi_interaction.api import CreatorInputViolation, SceneQueryViolation, SceneStatus
from armi_kernel.contracts import ContractViolation

from armi_runtime.application.artifact_transfer import ArtifactReadWindow
from armi_runtime.application.creator_commands import CreatorCommands
from armi_runtime.application.creator_contract import CreatorCodexTaskRequest
from armi_runtime.application.interaction import (
    InteractionInvocation,
    InteractionResult,
)
from armi_runtime.application.media_uploads import UploadViolation

from .creator_effect_wire import effect_wire
from .creator_http import (
    _accepted_wire,
    _input_failure,
    _rejected,
    _scene_wire,
    _unavailable,
    operation_wire,
)

COMMAND_NAMES = frozenset(
    {
        "message_send",
        "scene_list",
        "scene_create",
        "scene_close",
        "scene_reopen",
        "codex_submit",
        "operation_get",
        "effect_get",
        "artifact_read",
    }
)


async def invoke_command(
    commands: CreatorCommands, call: InteractionInvocation
) -> InteractionResult:
    args = cast(dict[str, Any], call.arguments)
    try:
        match call.operation:
            case "operation_get":
                if commands.media is not None:
                    media = await commands.media.operation(
                        args["result_ref"], commands.operation
                    )
                    if media is not None:
                        return InteractionResult("returned", media)
                operation = await commands.operation(args["result_ref"])
                return InteractionResult("returned", operation_wire(operation))
            case "effect_get":
                effect = await commands.effect(
                    args["effect_id"], call.caller.creator_party_id
                )
                return InteractionResult("returned", effect_wire(effect))
            case "artifact_read":
                kind = EffectArtifactKind(args["artifact_kind"])
                metadata, content, media_type = await commands.artifact_chunk(
                    args["effect_id"],
                    call.caller.creator_party_id,
                    kind,
                    ArtifactReadWindow(
                        offset=args.get("offset", 0), length=args.get("length", 65536)
                    ),
                )
                return InteractionResult(
                    "returned",
                    metadata.model_dump(mode="json"),
                    content=content,
                    media_type=media_type,
                )
            case "message_send":
                if args.get("attachments"):
                    if commands.media is None:
                        raise CreatorInputViolation("INPUT-DEPENDENCY")
                    reference = await commands.media.send(
                        args, call.caller.creator_party_id, call.caller.delegate_id
                    )
                    media = await commands.media.operation(
                        str(reference), commands.operation
                    )
                    assert media is not None
                    return InteractionResult("returned", media, 202)
                accepted = await commands.message(
                    scene_key=args["scene_key"],
                    message=args.get("message", ""),
                    idempotency_key=args["idempotency_key"],
                    delegate_id=call.caller.delegate_id,
                )
                return InteractionResult("returned", _accepted_wire(accepted), 202)
            case "scene_list":
                collection = await commands.list_scenes()
                return InteractionResult(
                    "returned",
                    {
                        "contract_version": "1.0",
                        "projection_version": "creator-scenes.v1",
                        "scenes": [
                            _scene_wire(scene).model_dump(
                                mode="json", exclude_none=True
                            )
                            for scene in collection.scenes
                        ],
                    },
                )
            case "scene_create":
                scene = await commands.create_scene(
                    args["scene_key"], delegate_id=call.caller.delegate_id
                )
                return InteractionResult(
                    "returned",
                    _scene_wire(scene).model_dump(mode="json", exclude_none=True),
                    201,
                )
            case "scene_close" | "scene_reopen":
                scene = await commands.transition_scene(
                    args["scene_key"],
                    SceneStatus.CLOSED
                    if call.operation == "scene_close"
                    else SceneStatus.OPEN,
                    delegate_id=call.caller.delegate_id,
                )
                return InteractionResult(
                    "returned",
                    _scene_wire(scene).model_dump(mode="json", exclude_none=True),
                )
            case "codex_submit":
                body = CreatorCodexTaskRequest.model_validate(
                    {
                        "contract_version": "1.0",
                        **{
                            key: value
                            for key, value in args.items()
                            if key not in {"scene_key", "idempotency_key"}
                        },
                    }
                )
                accepted = await commands.submit_codex(
                    scene_key=args["scene_key"],
                    objective=body.objective,
                    idempotency_key=args["idempotency_key"],
                    model=CodexModel(body.model_id),
                    reasoning=CodexReasoningEffort(body.reasoning_effort),
                    web_search=body.web_search,
                    delegate_id=call.caller.delegate_id,
                )
                return InteractionResult("returned", _accepted_wire(accepted), 202)
            case _:
                raise ValueError("INTERACTION-COMMAND-UNKNOWN")
    except EffectViolation as error:
        if error.code in {"SCOPE-EFFECT-NOT-VISIBLE", "EFFECT-ARTIFACT-KIND"}:
            status, content = 404, _rejected("SCOPE_EFFECT_NOT_VISIBLE")
        else:
            status, content = 503, _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
    except UnicodeDecodeError:
        status, content = 503, _unavailable("DEPENDENCY_EFFECT_QUERY_UNAVAILABLE")
    except UploadViolation as error:
        status, content = 409, _rejected(str(error))
    except CreatorInputViolation as error:
        status, content = _input_failure(error)
    except ContractViolation:
        status, content = 400, _rejected("INPUT_IDEMPOTENCY_KEY")
    except SceneQueryViolation as error:
        if error.code == "SCENE-KEY-CONFLICT":
            status, content = 409, _rejected("CONFLICT_SCENE_KEY")
        elif error.code == "SCENE-NOT-VISIBLE":
            status, content = 404, _rejected("SCOPE_SCENE_NOT_VISIBLE")
        elif error.code.startswith("CON-SCENE"):
            status, content = 400, _rejected("INPUT_SCENE_KEY")
        else:
            status, content = 503, _unavailable("DEPENDENCY_SCENE_COMMAND_UNAVAILABLE")
    except CodexDelegationViolation as error:
        failures = {
            "CODEX-TASK-IDEMPOTENCY": (409, "IDEMPOTENCY_MISMATCH"),
            "CODEX-TASK-REQUEST-SIZE": (413, "INPUT_MESSAGE_TOO_LARGE"),
            "CODEX-TASK-REQUEST": (400, "INPUT_MESSAGE_INVALID"),
            "CODEX-TASK-SUBJECT": (404, "SCOPE_SCENE_NOT_VISIBLE"),
            "CODEX-DISABLED": (503, "DEPENDENCY_CODEX_DISABLED"),
            "CODEX-CREDENTIAL-MISSING": (503, "DEPENDENCY_CODEX_CREDENTIAL_MISSING"),
            "CODEX-CREDENTIAL-UNAVAILABLE": (
                503,
                "DEPENDENCY_CODEX_CREDENTIAL_UNAVAILABLE",
            ),
            "CODEX-UNAVAILABLE": (503, "DEPENDENCY_CODEX_EXECUTOR_UNAVAILABLE"),
        }
        status, code = failures.get(
            error.code, (503, "DEPENDENCY_CODEX_TASK_UNAVAILABLE")
        )
        content = _unavailable(code) if status == 503 else _rejected(code)
    except ValueError:
        if call.operation in {"effect_get", "artifact_read"}:
            status, content = 404, _rejected("SCOPE_EFFECT_NOT_VISIBLE")
        elif call.operation == "operation_get":
            status, content = 404, _rejected("SCOPE_OPERATION_NOT_VISIBLE")
        else:
            status, content = 400, _rejected("INPUT_INTERACTION_ARGUMENTS")
    return InteractionResult(
        "rejected" if status < 500 else "unavailable", content, status
    )


__all__ = ("COMMAND_NAMES", "invoke_command")
