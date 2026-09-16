from types import SimpleNamespace
from typing import cast
from uuid import uuid7

from armi_runtime.application.creator_system import CreatorSystem
from armi_runtime.interfaces.browser_sessions import BrowserSessionStore
from armi_runtime.interfaces.creator_routes_usage import register_usage_routes
from fastapi import FastAPI
from fastapi.security import HTTPBearer
from fastapi.testclient import TestClient


def test_usage_routes_authorize_before_query_and_share_filters():
    requests = []

    async def query(request):
        requests.append(request)
        if request.mode == "read":
            raise ValueError("USAGE-CALL-NOT-FOUND")
        return {"total": 0, "items": []}

    sessions = BrowserSessionStore(
        environment_id=uuid7(), creator_party_id=uuid7(), session_ttl_seconds=60
    )
    token = sessions.establish().token
    app = FastAPI()
    register_usage_routes(
        app=app,
        bearer=HTTPBearer(auto_error=False),
        canonical_origin="http://testserver",
        browser_sessions=sessions,
        system=cast(CreatorSystem, SimpleNamespace(usage=SimpleNamespace(query=query))),
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://testserver",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with TestClient(app) as client:
        assert client.get("/v1/usage/calls").status_code in {401, 403}
        assert (
            client.get(
                "/v1/usage/calls", headers={**headers, "Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        assert requests == []
        filters = {
            "start": "2026-09-01T00:00:00+08:00",
            "end": "2026-10-01T00:00:00+08:00",
            "model": "model-a",
            "cost_status": "unpriced",
        }
        response = client.get(
            "/v1/usage/calls",
            headers=headers,
            params={**filters, "limit": 2, "offset": 3},
        )
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"total": 0, "items": []}
        assert (
            client.get("/v1/usage/summary", headers=headers, params=filters).status_code
            == 200
        )
        assert requests[0].filters == requests[1].filters
        assert (requests[0].limit, requests[0].offset) == (2, 3)
        assert (
            client.get(f"/v1/usage/calls/{uuid7()}", headers=headers).status_code == 404
        )
        previous = len(requests)
        assert (
            client.get(
                "/v1/usage/calls", headers=headers, params={"limit": 101}
            ).status_code
            == 422
        )
        assert (
            client.get(
                "/v1/usage/calls", headers=headers, params={"start": "invalid"}
            ).status_code
            == 422
        )
        assert len(requests) == previous
