"""Isolated HTTP provider responses for the born Runtime integration test."""

import json

import httpx
from armi_runtime.runtime_entrypoint import main


def respond(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    if str(request.url) == "https://api.typesafe.ai/v1/systemone":
        answers = {}
        for name, question in body["questions"].items():
            choice = next(
                option
                for option in question["criteria"]
                if option not in {"unknown", "not_applicable"}
            )
            answers[name] = {
                "type": "choice",
                "choice": choice,
                "confidence": 1,
                "probabilities": {
                    option: int(option == choice) for option in question["criteria"]
                },
            }
        return httpx.Response(
            200,
            json={
                "model": body["model"],
                "answers": answers,
                "usage": {"input_tokens": 100, "output_tokens": 20},
            },
        )
    if (
        str(request.url)
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/responses"
    ):
        return httpx.Response(
            200,
            json={
                "id": "resp-isolated",
                "object": "response",
                "created_at": 1,
                "model": body["model"],
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "id": "msg-isolated",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "text": json.dumps(
                                    {
                                        "action": "reply",
                                        "content": ["隔离测试收到。"],
                                    },
                                    ensure_ascii=False,
                                ),
                            }
                        ],
                    }
                ],
                "usage": {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                },
            },
        )
    raise AssertionError(f"unexpected isolated provider URL: {request.url}")


class IsolatedClient(httpx.AsyncClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, transport=httpx.MockTransport(respond))


if __name__ == "__main__":
    httpx.AsyncClient = IsolatedClient
    raise SystemExit(main())
