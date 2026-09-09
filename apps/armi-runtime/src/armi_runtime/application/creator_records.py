from __future__ import annotations

from .creator_calls import CreatorCall, CreatorUseCase, creator_result
from .creator_inputs import _life_query_parameters
from .creator_projection import (
    UUID,
    Any,
    ContractViolation,
    Instant,
    Literal,
    OpaqueCursor,
    OtherHumanPartyRecordPageResponse,
    OtherHumanPartyRecordResponse,
    OtherHumanRecordQueryPort,
    OtherHumanRecordViolation,
    OtherHumanSceneRecordPageResponse,
    OtherHumanSceneRecordResponse,
    OtherHumanTimelineRecordPageResponse,
    OtherHumanTimelineRecordResponse,
    SceneKey,
    SceneQueryViolation,
    SceneTimelineItemResponse,
    SceneTimelinePageResponse,
    SceneTimelineQuery,
    SceneTimelineQueryPort,
    _rejected,
    _unavailable,
    cast,
)
from .interaction import InteractionResult


def create_record_use_cases(
    *,
    scene_timeline_query: SceneTimelineQueryPort | None,
    other_human_record_query: OtherHumanRecordQueryPort | None,
) -> dict[str, CreatorUseCase]:

    async def get_scene_timeline(
        scene_key: str, call: CreatorCall
    ) -> InteractionResult:
        if scene_timeline_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        pairs = list(call.parameters)
        names = [name for name, _value in pairs]
        if (
            set(names) - {"limit", "cursor"}
            or names.count("limit") != 1
            or names.count("cursor") > 1
        ):
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_LIMIT")
            )
        values = dict(pairs)
        limit_text = values["limit"]
        if not limit_text.isascii() or not limit_text.isdecimal():
            return creator_result(
                status_code=400, content=_rejected("INPUT_PAGE_LIMIT")
            )
        try:
            parsed_scene_key = SceneKey(scene_key)
        except SceneQueryViolation:
            return creator_result(
                status_code=404, content=_rejected("SCOPE_SCENE_NOT_VISIBLE")
            )
        try:
            query = SceneTimelineQuery(
                scene_key=parsed_scene_key,
                limit=int(limit_text),
                cursor=OpaqueCursor.from_wire(values["cursor"])
                if "cursor" in values
                else None,
            )
        except ContractViolation, SceneQueryViolation:
            code = "INPUT_CURSOR_INVALID" if "cursor" in values else "INPUT_PAGE_LIMIT"
            return creator_result(status_code=400, content=_rejected(code))
        try:
            page = await scene_timeline_query.query(query)
        except SceneQueryViolation as error:
            if error.code == "SCENE-NOT-VISIBLE":
                return creator_result(
                    status_code=404, content=_rejected("SCOPE_SCENE_NOT_VISIBLE")
                )
            if error.code == "SCENE-CURSOR-STALE":
                return creator_result(
                    status_code=409, content=_rejected("CONFLICT_CURSOR_STALE")
                )
            if error.code == "SCENE-CURSOR-INVALID":
                return creator_result(
                    status_code=400, content=_rejected("INPUT_CURSOR_INVALID")
                )
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_SCENE_QUERY_UNAVAILABLE"),
            )
        response = SceneTimelinePageResponse(
            contract_version="1.0",
            projection_version="scene-timeline.v6",
            scene_key=page.scene_key.value,
            items=[
                SceneTimelineItemResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_kind=item.source_kind,
                    source_ref=str(item.source_ref),
                    status=item.status.value,
                    occurred_at=item.occurred_at.to_wire(),
                    operation_ref=str(item.operation_ref)
                    if item.operation_ref is not None
                    else None,
                    effect_ref=str(item.effect_ref)
                    if item.effect_ref is not None
                    else None,
                    message=item.message,
                    modality=cast(
                        Literal["text", "media_file", "live_voice"], item.modality
                    ),
                )
                for item in page.items
            ],
            next_cursor=page.next_cursor.to_wire()
            if page.next_cursor is not None
            else None,
        )
        return creator_result(
            content=response.model_dump(mode="json", exclude_none=True)
        )

    def _other_human_party_wire(item: Any) -> OtherHumanPartyRecordResponse:
        return OtherHumanPartyRecordResponse(
            party_id=str(item.party_id),
            party_key=item.party_key,
            display_label=item.display_label,
            scene_count=item.scene_count,
            record_count=item.record_count,
            last_record_at=None
            if item.last_record_at is None
            else Instant(item.last_record_at).to_wire(),
        )

    async def _other_human_record_scope(
        call: CreatorCall,
    ) -> tuple[int, OpaqueCursor | None] | InteractionResult:
        if other_human_record_query is None:
            return creator_result(
                status_code=503,
                content=_unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE"),
            )
        try:
            limit, _query, _kind, cursor = _life_query_parameters(
                call, allow_kind=False, allow_text=False
            )
            return (limit, cursor)
        except ContractViolation:
            return creator_result(status_code=400, content=_rejected("INPUT_PAGE"))

    async def list_other_human_record_parties(call: CreatorCall) -> InteractionResult:
        scope = await _other_human_record_scope(call)
        if isinstance(scope, InteractionResult):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_parties(limit=scope[0], cursor=scope[1])
        except OtherHumanRecordViolation as error:
            status = 400 if error.code.endswith(("CURSOR", "LIMIT")) else 503
            return creator_result(
                status_code=status,
                content=_rejected("INPUT_PAGE")
                if status == 400
                else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE"),
            )
        response = OtherHumanPartyRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            items=[_other_human_party_wire(item) for item in page.items],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return creator_result(
            content=response.model_dump(mode="json", exclude_none=True)
        )

    async def list_other_human_record_scenes(
        party_id: str, call: CreatorCall
    ) -> InteractionResult:
        scope = await _other_human_record_scope(call)
        if isinstance(scope, InteractionResult):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.list_scenes(
                UUID(party_id), limit=scope[0], cursor=scope[1]
            )
        except ValueError:
            return creator_result(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_PARTY")
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return creator_result(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return creator_result(
                status_code=status,
                content=_rejected("INPUT_PAGE")
                if status == 400
                else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE"),
            )
        response = OtherHumanSceneRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party=_other_human_party_wire(page.party),
            items=[
                OtherHumanSceneRecordResponse(
                    scene_id=str(item.scene_id),
                    scene_key=item.scene_key,
                    status=cast(Literal["open", "closed"], item.status),
                    record_count=item.record_count,
                    last_record_at=None
                    if item.last_record_at is None
                    else Instant(item.last_record_at).to_wire(),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return creator_result(
            content=response.model_dump(mode="json", exclude_none=True)
        )

    async def get_other_human_record_timeline(
        party_id: str, scene_id: str, call: CreatorCall
    ) -> InteractionResult:
        scope = await _other_human_record_scope(call)
        if isinstance(scope, InteractionResult):
            return scope
        try:
            query = cast(OtherHumanRecordQueryPort, other_human_record_query)
            page = await query.timeline(
                UUID(party_id), UUID(scene_id), limit=scope[0], cursor=scope[1]
            )
        except ValueError:
            return creator_result(
                status_code=400, content=_rejected("INPUT_OTHER_HUMAN_RECORD_SCOPE")
            )
        except OtherHumanRecordViolation as error:
            if error.code.endswith("NOT-VISIBLE"):
                return creator_result(
                    status_code=404,
                    content=_rejected("SCOPE_OTHER_HUMAN_RECORD_NOT_VISIBLE"),
                )
            status = 400 if error.code.endswith(("CURSOR", "LIMIT", "SCOPE")) else 503
            return creator_result(
                status_code=status,
                content=_rejected("INPUT_PAGE")
                if status == 400
                else _unavailable("DEPENDENCY_OTHER_HUMAN_RECORD_UNAVAILABLE"),
            )
        response = OtherHumanTimelineRecordPageResponse(
            contract_version="1.0",
            projection_version="other-human-record.v1",
            party_id=str(page.party_id),
            scene_id=str(page.scene_id),
            items=[
                OtherHumanTimelineRecordResponse(
                    timeline_item_id=str(item.timeline_item_id),
                    source_ref=str(item.source_ref),
                    direction=item.direction.value,
                    status=cast(
                        Literal["accepted", "completed", "failed", "unknown"],
                        item.result_status,
                    ),
                    text=item.text,
                    occurred_at=Instant(item.occurred_at).to_wire(),
                )
                for item in page.items
            ],
            next_cursor=None if page.next_cursor is None else page.next_cursor.value,
        )
        return creator_result(
            content=response.model_dump(mode="json", exclude_none=True)
        )

    return {
        "scene_timeline": get_scene_timeline,
        "other_human_list": list_other_human_record_parties,
        "other_human_scenes": list_other_human_record_scenes,
        "other_human_timeline": get_other_human_record_timeline,
    }


__all__ = ("create_record_use_cases",)
