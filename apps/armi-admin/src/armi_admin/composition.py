"""The sole composition root for the Admin MCP process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .application.installation import SetupApplication, SetupPaths

from armi_artifact_store.bootstrap import bootstrap_artifact_admin
from armi_attention.bootstrap import bootstrap_opportunity_admin
from armi_codex.bootstrap import bootstrap_codex_admin
from armi_cognition.bootstrap import bootstrap_cognition_admin
from armi_effect.bootstrap import bootstrap_effect_admin
from armi_evidence.bootstrap import bootstrap_evidence_admin
from armi_expression.bootstrap import bootstrap_expression_admin
from armi_interaction.bootstrap import bootstrap_interaction_admin
from armi_kernel.application import CredentialPurpose
from armi_live_vision.bootstrap import bootstrap_live_vision_admin
from armi_material.bootstrap import bootstrap_material_admin_read
from armi_mood.bootstrap import (
    bootstrap_mood_admin_correction,
    bootstrap_mood_admin_read,
)
from armi_perception.bootstrap import bootstrap_perception_admin
from armi_prompt.bootstrap import bootstrap_prompt_admin_reference
from armi_subject_state.bootstrap import (
    bootstrap_subject_state_admin_correction,
    bootstrap_subject_state_admin_read,
)
from armi_web_observation.bootstrap import bootstrap_web_observation_admin

from armi_admin.application import (
    AdminConfig,
    AdminControlPlane,
    AdminCorrectionCoordinator,
    AdminCredentialPort,
)
from armi_admin.application.service import AdminToolService
from armi_admin.persistence import AdminCorrectionGateway, AdminObservationGateway
from armi_admin.persistence.role_session import AdminRoleBoundPool
from armi_admin.persistence.runtime_foundation import RuntimeFoundationAdminAdapter


@dataclass(slots=True)
class AdminComposition:
    service: AdminToolService
    pool: AdminRoleBoundPool

    def close(self) -> None:
        self.pool.close()


def bootstrap_admin(
    config: AdminConfig, credentials: AdminCredentialPort
) -> AdminComposition:
    def conninfo() -> str:
        with credentials.resolve(
            config.locator, CredentialPurpose("database.admin")
        ) as handle:
            return handle.consume(lambda value: bytes(value).decode("utf-8"))

    pool = AdminRoleBoundPool(conninfo, expected_role=config.expected_role)
    pool.open()
    try:
        runtime = RuntimeFoundationAdminAdapter(
            environment_id=config.environment_id,
            incarnation=config.environment_incarnation,
        )
        artifact_root = config.environment_root / "data" / "artifacts"
        artifacts = bootstrap_artifact_admin(artifact_root=artifact_root)
        cognition = bootstrap_cognition_admin()
        codex = bootstrap_codex_admin()
        effects = bootstrap_effect_admin()
        evidence = bootstrap_evidence_admin()
        expression = bootstrap_expression_admin()
        interaction = bootstrap_interaction_admin()
        materials = bootstrap_material_admin_read(artifacts=artifacts)
        mood = bootstrap_mood_admin_correction()
        opportunity = bootstrap_opportunity_admin()
        subject_state = bootstrap_subject_state_admin_correction()
        web = bootstrap_web_observation_admin()
        observation = AdminObservationGateway(
            factory=pool,
            runtime=runtime,
            artifacts=artifacts,
            cognition=cognition,
            effects=effects,
            evidence=evidence,
            opportunity=opportunity,
            expression=expression,
            interaction=interaction,
            materials=materials,
            mood=bootstrap_mood_admin_read(),
            subject_state=bootstrap_subject_state_admin_read(),
        )
        correction_gateway = AdminCorrectionGateway(
            factory=pool,
            runtime=runtime,
            artifacts=artifacts,
            cognition=cognition,
            codex=codex,
            effects=effects,
            evidence=evidence,
            expression=expression,
            interaction=interaction,
            live_vision=bootstrap_live_vision_admin(),
            material=materials,
            opportunity=opportunity,
            perception=bootstrap_perception_admin(),
            web=web,
            environment_id=config.environment_id,
            incarnation=config.environment_incarnation,
            mood=mood,
            prompts=bootstrap_prompt_admin_reference(),
            subject_state=subject_state,
        )
        control = AdminControlPlane(config, credentials, observation)
        corrections = AdminCorrectionCoordinator(
            config, credentials, control, correction_gateway
        )
        service = AdminToolService(
            config=config,
            credentials=credentials,
            control=control,
            corrections=corrections,
            observation=observation,
            pool=pool,
        )
        return AdminComposition(service, pool)
    except BaseException:
        pool.close()
        raise


def bootstrap_setup(paths: SetupPaths) -> SetupApplication:
    """Compose installer transports over the existing Admin application."""
    import json
    from typing import Any

    from .application.configuration import load_admin_config
    from .application.credentials import AdminCredentialPort
    from .application.installation import SetupApplication, SetupError
    from .application.package_identity import verify_admin_package_set

    def invoke(operation_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from .application.catalog import ADMIN_OPERATIONS

        config, path = load_admin_config(
            {"ARMI_ADMIN_CONFIG": str(paths.environment_root / "admin.yaml")}
        )
        verify_admin_package_set(config.expected.package_set_digest)
        operation = next(
            (item for item in ADMIN_OPERATIONS if item.name == operation_name), None
        )
        if operation is None:
            raise SetupError("SETUP-OPERATION-UNAVAILABLE")
        payload = dict(arguments)
        fields = operation.request.model_fields
        for name, value in {
            "environment_id": config.environment_id,
            "environment_incarnation": config.environment_incarnation,
            "purpose": "admin." + operation_name,
        }.items():
            if name in fields:
                if name in payload and payload[name] != value:
                    raise SetupError("SETUP-BINDING-MISMATCH")
                payload[name] = value
        request = operation.request.model_validate_json(json.dumps(payload))
        credentials = AdminCredentialPort(
            locator=config.locator,
            migrator_locator=config.migrator_locator,
            preview_locator=config.preview_locator,
            config_root=path.parent,
        )
        composition = bootstrap_admin(config, credentials)
        try:
            return operation.invoke(composition.service, request).model_dump(
                mode="json"
            )
        finally:
            composition.close()

    from .windows_startup import login_startup

    def startup(enabled: bool | None) -> dict[str, object]:
        launcher = paths.installation_root / "armi-desktop.exe"
        return login_startup(launcher, paths.environment_root, enabled)

    return SetupApplication(paths, invoke, startup)


__all__ = ("AdminComposition", "bootstrap_admin", "bootstrap_setup")
