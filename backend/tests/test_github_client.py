import httpx

from app.github.client import GitHubClient


def test_github_client_sends_bearer_token(settings):
    observed_headers = {}

    def handle_request(request):
        observed_headers.update(request.headers)
        return httpx.Response(200, json={"login": "octo"})

    client = GitHubClient(
        "test-token",
        settings,
        transport=httpx.MockTransport(handle_request),
    )
    try:
        assert client.get_user() == {"login": "octo"}
    finally:
        client.close()

    assert observed_headers["authorization"] == "Bearer test-token"
