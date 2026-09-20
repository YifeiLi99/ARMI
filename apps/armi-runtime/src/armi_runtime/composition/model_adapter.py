"""Select documented provider transports at the composition boundary."""

import json

from armi_cognition.api import CognitionSchemaDocument
from armi_kernel.application import (
    CredentialLocator,
    CredentialPort,
    ModelBinding,
    ModelViolation,
)

from armi_runtime.adapters.model.compatible import CompatibleStructuredTransport
from armi_runtime.adapters.model.model_clients import ModelClients
from armi_runtime.adapters.model.structured import (
    OfficialArkTransport,
    StructuredModelAdapter,
    StructuredTransport,
)


def create_model_adapter(
    *,
    binding: ModelBinding,
    credential_port: CredentialPort,
    locator: CredentialLocator | None,
    candidate_schema: CognitionSchemaDocument,
    instructions: str,
    schema_name: str,
    transport: StructuredTransport | None = None,
    clients: ModelClients | None = None,
) -> StructuredModelAdapter:
    transport_type: type[CompatibleStructuredTransport] | type[OfficialArkTransport]
    if binding.provider in {"qwen", "deepseek"}:
        transport_type = CompatibleStructuredTransport
    elif (
        binding.provider == "volcengine_ark" and binding.profile == "creator_voice_act"
    ):
        transport_type = OfficialArkTransport
    else:
        raise ModelViolation("MODEL-BINDING")
    renderer = transport_type(
        json.loads(candidate_schema.canonical_bytes),
        instructions=instructions,
        schema_name=schema_name,
        clients=clients,
    )
    return StructuredModelAdapter(
        binding=binding,
        credential_port=credential_port,
        locator=locator,
        transport=transport,
        renderer=renderer,
    )
