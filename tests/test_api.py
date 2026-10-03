import asyncio

import httpx

from app.main import app


def post_debug(code: str) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post("/api/debug", json={"code": code})

    return asyncio.run(send())


def test_debug_api() -> None:
    response = post_debug("a = 1\nb = 2\nprint(a + b)")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"].startswith("a = 1")
    assert payload["algorithm"]["renderer"] == "execution"
    assert payload["steps"][-1]["stdout"] == "3\n"


def test_debug_api_accepts_stdin() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/debug",
                json={"code": "value = int(input())\nprint(value * 2)", "stdin": "21\n"},
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    assert response.json()["steps"][-1]["stdout"] == "42\n"


def test_debug_api_reports_validation_error() -> None:
    response = post_debug("import os")

    assert response.status_code == 422
    assert response.json()["detail"]["issues"][0]["line"] == 1


def test_debug_api_accepts_cpp() -> None:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.post(
                "/api/debug",
                json={
                    "language": "cpp",
                    "code": "#include <iostream>\nint main() { int n; std::cin >> n; int answer = n * 2; std::cout << answer << '\\n'; return 0; }",
                    "stdin": "21\n",
                },
            )

    response = asyncio.run(send())

    assert response.status_code == 200
    payload = response.json()
    assert payload["language"] == "cpp"
    assert payload["status"] == "completed"
    assert payload["steps"]
    assert payload["steps"][-1]["stdout"] == "42\n"


def test_page_versions_its_scripts_so_browsers_never_mix_old_and_new_files() -> None:
    async def fetch() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/")

    response = asyncio.run(fetch())

    assert response.headers["cache-control"] == "no-cache"
    assert "/static/app.js?v=" in response.text
    assert "/static/style.css?v=" in response.text
