"""The sole composition root for the Admin MCP process."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from armi_sleep.bootstrap import bootstrap_sleep_admin_read

if TYPE_CHECKING:
    from .application.installation import SetupApplication, SetupPaths
    from .machine import AdminSession

from armi_activity.bootstrap import bootstrap_activity_admin_content
from armi_artifact_store.bootstrap import (
    bootstrap_artifact_admin,
    bootstrap_artifact_admin_content,
)
from armi_attention.bootstrap import bootstrap_opportunity_admin
from armi_codex.bootstrap import bootstrap_codex_admin
from armi_cognition.bootstrap import (
    bootstrap_appraisal_read,
    bootstrap_cognition_admin,
    bootstrap_focus_admin_content,
    bootstrap_focus_admin_correction,
    bootstrap_focus_admin_read,
)
from armi_data_rights.bootstrap import bootstrap_data_rights_admin_content_guard
from armi_effect.bootstrap import bootstrap_effect_admin, bootstrap_expression_admin
from armi_evidence.bootstrap import bootstrap_evidence_admin
from armi_interaction.bootstrap import bootstrap_interaction_admin
from armi_kernel.application import CredentialPurpose
from armi_live_vision.bootstrap import bootstrap_live_vision_admin
from armi_material.bootstrap import (
    bootstrap_material_admin_content,
    bootstrap_material_admin_read,
)
from armi_memory.bootstrap import bootstrap_memory_admin_content
from armi_mind.bootstrap import (
    bootstrap_mind_admin_content,
    bootstrap_mind_admin_correction,
    bootstrap_mind_admin_read,
)
from armi_mood.bootstrap import (
    bootstrap_mood_admin_content,
    bootstrap_mood_admin_correction,
    bootstrap_mood_admin_read,
)
from armi_prompt.bootstrap import (
    bootstrap_prompt_admin_content,
    bootstrap_prompt_admin_reference,
)
from armi_relationship.bootstrap import bootstrap_relationship_admin_content
from armi_subject_state.bootstrap import (
    bootstrap_subject_state_admin_content,
    bootstrap_subject_state_admin_correction,
    bootstrap_subject_state_admin_read,
)

from armi_admin.application import (
    AdminConfig,
    AdminControlPlane,
    AdminCorrectionCoordinator,
    AdminCredentialPort,
)
from armi_admin.application.content_management import ContentManagement
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
    config: AdminConfig, credentials: AdminCredentialPort, *, local_owner: bool = False
) -> AdminComposition:
    if local_owner:
        from .application.catalog import ADMIN_OPERATIONS

        scopes = {item.name for item in ADMIN_OPERATIONS}
        scopes.update(
            variant["required_scope"]
            for item in ADMIN_OPERATIONS
            for variant in item.suboperations()
        )
        scopes.add("subject_snapshot.private")
        config = config.model_copy(
            update={"authorized_operations": tuple(sorted(scopes))}
        )

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
        codex = bootstrap_codex_admin(artifacts=artifacts)
        effects = bootstrap_effect_admin()
        evidence = bootstrap_evidence_admin()
        expression = bootstrap_expression_admin()
        interaction = bootstrap_interaction_admin()
        materials = bootstrap_material_admin_read(artifacts=artifacts)
        mood = bootstrap_mood_admin_correction()
        opportunity = bootstrap_opportunity_admin()
        subject_state = bootstrap_subject_state_admin_correction()
        observation = AdminObservationGateway(
            sleep=bootstrap_sleep_admin_read(),
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
            mood=bootstrap_mood_admin_read(bootstrap_appraisal_read()),
            subject_state=bootstrap_subject_state_admin_read(),
            mind=bootstrap_mind_admin_read(),
            focus=bootstrap_focus_admin_read(),
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
            environment_id=config.environment_id,
            incarnation=config.environment_incarnation,
            mood=mood,
            prompts=bootstrap_prompt_admin_reference(),
            subject_state=subject_state,
            mind=bootstrap_mind_admin_correction(),
            focus=bootstrap_focus_admin_correction(),
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
            local_owner=local_owner,
            content=ContentManagement(
                config,
                pool,
                owners={
                    "memory": bootstrap_memory_admin_content(),
                    "relationship": bootstrap_relationship_admin_content(),
                    "activity": bootstrap_activity_admin_content(),
                    "material": bootstrap_material_admin_content(),
                    "prompt": bootstrap_prompt_admin_content(),
                    "subject_state": bootstrap_subject_state_admin_content(),
                    "mind": bootstrap_mind_admin_content(),
                    "focus": bootstrap_focus_admin_content(),
                    "mood": bootstrap_mood_admin_content(),
                },
                guards=(
                    cognition,
                    effects,
                    bootstrap_data_rights_admin_content_guard(),
                ),
                parties=interaction,
                artifacts=bootstrap_artifact_admin_content(
                    artifact_root=artifact_root, factory=pool
                ),
            ),
        )
        return AdminComposition(service, pool)
    except BaseException:
        pool.close()
        raise


def bootstrap_setup(
    paths: SetupPaths, *, admin_session: AdminSession | None = None
) -> SetupApplication:
    """Compose installer transports over the existing Admin application."""
    import json
    from typing import Any

    from .application.installation import SetupApplication, SetupError, SetupPaths
    from .machine import AdminSession

    session = admin_session or AdminSession(
        paths.environment_root / "admin.yaml", local_owner=True
    )
    invoke = session.invoke

    from .windows_startup import login_startup

    def startup(enabled: bool | None) -> dict[str, object]:
        launcher = paths.installation_root / "ARMI.exe"
        return login_startup(launcher, paths.environment_root, enabled)

    from uuid import uuid7

    from .application.deployment import installed_root, registered_environments
    from .application.updates import UpdateApplication

    def stop_environments(operation: str = "UPDATE") -> None:
        root = installed_root(paths.installation_root)
        if root is None:
            raise SetupError(operation + "-MSIX-REQUIRED")
        for environment in registered_environments(root):
            service = bootstrap_setup(
                SetupPaths(
                    environment_root=environment,
                    installation_root=paths.installation_root,
                )
            )
            try:
                result = service.invoke(
                    "environment_stop", {"idempotency_key": str(uuid7())}
                )
            finally:
                service.close()
            if result.get("status") != "succeeded":
                raise SetupError(operation + "-ENVIRONMENT-STOP-UNCONFIRMED")

    def uninstall(delete_data: bool) -> dict[str, Any]:
        from armi_local_control.windows_package import uninstall as remove_package

        stop_environments("UNINSTALL")
        return remove_package(delete_data=delete_data)

    def verify_credential(name: str, secret: bytes) -> dict[str, Any]:
        import os
        import subprocess
        import sys
        from typing import cast

        from armi_local_control import ProviderCheckReceipts

        verification_id = str(uuid7())
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "armi_runtime.credential_probe"],
                input=json.dumps(
                    {
                        "name": name,
                        "key": secret.decode("utf-8"),
                        "root": str(paths.environment_root),
                        "verification_id": verification_id,
                    }
                ).encode("utf-8"),
                capture_output=True,
                timeout=90,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if completed.returncode or len(completed.stdout) > 32768:
                raise ValueError
            decoded: object = json.loads(completed.stdout)
            if not isinstance(decoded, dict):
                raise ValueError
            result = cast(dict[str, Any], decoded)
            if result.get("status") not in {
                "passed",
                "failed",
            }:
                raise ValueError
            return result
        except OSError, ValueError, subprocess.TimeoutExpired:
            return {
                "status": "failed",
                "error_code": "SETUP-CREDENTIAL-VERIFY-FAILED",
                "message": "验证进程失败或超时。凭据已保存。尚未验证通过。",
                "verification_id": verification_id,
            }
        finally:
            ProviderCheckReceipts(paths.environment_root).settle_interrupted(
                verification_id
            )

    return SetupApplication(
        paths,
        invoke,
        startup,
        UpdateApplication(stop_environments).execute,
        uninstall,
        verify_credential,
        close=session.close,
    )


__all__ = ("AdminComposition", "bootstrap_admin", "bootstrap_setup")
