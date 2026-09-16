from types import SimpleNamespace
from typing import cast
from uuid import uuid7

from armi_runtime.application.creator_system import CreatorSystem
from armi_runtime.interfaces.browser_sessions import BrowserSessionStore
from armi_runtime.interfaces.creator_routes_autonomy import register_autonomy_routes
from fastapi import FastAPI
from fastapi.security import HTTPBearer
from fastapi.testclient import TestClient


def test_autonomy_authorization_pagination_and_unavailable():
    requests = []

    async def query(mode, limit, offset):
        requests.append((mode, limit, offset))
        return (
            {"state": "not_initialized"}
            if mode == "status"
            else {
                "items": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
            }
        )

    sessions = BrowserSessionStore(
        environment_id=uuid7(),
        creator_party_id=uuid7(),
        session_ttl_seconds=60,
    )
    token = sessions.establish().token
    system = SimpleNamespace(autonomy=SimpleNamespace(query=query))
    app = FastAPI()
    register_autonomy_routes(
        app=app,
        bearer=HTTPBearer(auto_error=False),
        canonical_origin="http://testserver",
        browser_sessions=sessions,
        system=cast(CreatorSystem, system),
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Origin": "http://testserver",
        "Sec-Fetch-Site": "same-origin",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Dest": "empty",
    }
    with TestClient(app) as client:
        assert client.get("/v1/autonomy/status").status_code in {401, 403}
        assert (
            client.get(
                "/v1/autonomy/history",
                headers={**headers, "Sec-Fetch-Site": "cross-site"},
            ).status_code
            == 403
        )
        assert requests == []
        response = client.get("/v1/autonomy/status", headers=headers)
        assert response.status_code == 200
        assert response.json()["state"] == "not_initialized"
        assert response.headers["cache-control"] == "no-store"
        response = client.get(
            "/v1/autonomy/history", headers=headers, params={"limit": 3, "offset": 4}
        )
        assert response.status_code == 200
        assert response.json() == {"items": [], "total": 0, "limit": 3, "offset": 4}
        assert requests == [("status", 25, 0), ("history", 3, 4)]
        assert (
            client.get(
                "/v1/autonomy/history", headers=headers, params={"limit": 101}
            ).status_code
            == 422
        )
        system.autonomy = None
        assert client.get("/v1/autonomy/status", headers=headers).status_code == 503
        assert len(requests) == 2
