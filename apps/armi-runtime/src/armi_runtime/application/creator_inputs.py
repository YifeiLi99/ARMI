from __future__ import annotations

from .creator_calls import CreatorCall
from .creator_contract import (
    CapabilityRequestDecisionRequest,
    CreatorExportRequest,
    CreatorPromptDeactivateRequest,
    CreatorPromptRevisionRequest,
    CreatorRelationshipBoundaryRequest,
    DataRightsOrderRequest,
)
from .creator_projection import (
    CapabilityViolation,
    ContractViolation,
    CreatorExportViolation,
    CreatorInputViolation,
    CreatorPromptViolation,
    DataRightsViolation,
    LifeRecordKind,
    OpaqueCursor,
)


async def _creator_boundary_request(
    call: CreatorCall,
) -> CreatorRelationshipBoundaryRequest:
    try:
        return CreatorRelationshipBoundaryRequest.model_validate(dict(call.input))
    except ValueError:
        raise CreatorInputViolation("INPUT-BODY") from None


async def _capability_decision_request(
    call: CreatorCall,
) -> CapabilityRequestDecisionRequest:
    try:
        return CapabilityRequestDecisionRequest.model_validate(dict(call.input))
    except ValueError:
        raise CapabilityViolation("CON-CAPABILITY-BODY") from None


async def _creator_prompt_revision_request(
    call: CreatorCall,
) -> CreatorPromptRevisionRequest:
    try:
        return CreatorPromptRevisionRequest.model_validate(dict(call.input))
    except ValueError:
        raise CreatorPromptViolation("CON-PROMPT-BODY") from None


async def _creator_prompt_deactivate_request(
    call: CreatorCall,
) -> CreatorPromptDeactivateRequest:
    try:
        return CreatorPromptDeactivateRequest.model_validate(dict(call.input))
    except ValueError:
        raise CreatorPromptViolation("CON-PROMPT-BODY") from None


async def _creator_export_request(call: CreatorCall) -> CreatorExportRequest:
    try:
        return CreatorExportRequest.model_validate(dict(call.input))
    except ValueError:
        raise CreatorExportViolation("CREATOR-EXPORT-COMMAND") from None


async def _data_rights_request(call: CreatorCall) -> DataRightsOrderRequest:
    try:
        return DataRightsOrderRequest.model_validate(dict(call.input))
    except ValueError:
        raise DataRightsViolation("DATA-RIGHTS-COMMAND") from None


def _life_query_parameters(
    call: CreatorCall, *, allow_kind: bool, allow_text: bool
) -> tuple[int, str | None, LifeRecordKind | None, OpaqueCursor | None]:
    supported_record_kinds = {
        "activity",
        "conversation",
        "experience",
        "material",
        "memory",
        "relationship",
        "self_change",
    }
    allowed = {"limit", "cursor"}
    if allow_kind:
        allowed.add("kind")
    if allow_text:
        allowed.add("q")
    pairs = list(call.parameters)
    names = [name for name, _value in pairs]
    if set(names) - allowed or any(names.count(name) > 1 for name in allowed):
        raise ContractViolation("CON-PAGE", "query parameters are invalid")
    values = dict(pairs)
    limit_text = values.get("limit", "50")
    if not limit_text.isascii() or not limit_text.isdecimal():
        raise ContractViolation("CON-PAGE", "page limit is invalid")
    limit = int(limit_text)
    if not 1 <= limit <= 100:
        raise ContractViolation("CON-PAGE", "page limit is invalid")
    query_text = values.get("q")
    if query_text is not None:
        try:
            encoded = query_text.encode("utf-8", errors="strict")
        except UnicodeEncodeError:
            raise ContractViolation("CON-PAGE", "query text is invalid") from None
        if not query_text.strip() or b"\x00" in encoded or len(encoded) > 1024:
            raise ContractViolation("CON-PAGE", "query text is invalid")
    try:
        record_kind = None
        if allow_kind and "kind" in values:
            if values["kind"] not in supported_record_kinds:
                raise ValueError("unsupported life-record kind")
            record_kind = LifeRecordKind(values["kind"])
        cursor = (
            OpaqueCursor.from_wire(values["cursor"]) if "cursor" in values else None
        )
    except ValueError, ContractViolation:
        raise ContractViolation("CON-PAGE", "query scope is invalid") from None
    return (limit, query_text, record_kind, cursor)


__all__ = (
    "_capability_decision_request",
    "_creator_boundary_request",
    "_creator_export_request",
    "_creator_prompt_deactivate_request",
    "_creator_prompt_revision_request",
    "_data_rights_request",
    "_life_query_parameters",
)
