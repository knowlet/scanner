import pytest
import yaml

from scanner.prober import APIProber


@pytest.fixture
def spec_file(tmp_path):
    spec_content = {
        "paths": {"/users/{id}": {"get": {"summary": "Get User"}}, "/login": {"post": {"summary": "Login"}}}
    }
    p = tmp_path / "spec.yaml"
    with open(p, "w") as f:
        yaml.dump(spec_content, f)
    return str(p)


def test_load_spec(spec_file):
    prober = APIProber(spec_file=spec_file, api_prefix="http://test.com")
    prober.load_spec()

    assert len(prober.endpoints) == 2
    paths = sorted([e["path"] for e in prober.endpoints])
    assert paths == ["/login", "/users/{id}"]


def test_fill_params(spec_file):
    prober = APIProber(spec_file=spec_file, api_prefix="http://test.com")

    path = "/users/{id}"
    filled = prober._fill_params(path)
    assert filled == "/users/1"

    path2 = "/items/{itemId}/details"
    filled2 = prober._fill_params(path2)
    assert filled2 == "/items/1/details"


@pytest.mark.asyncio
async def test_run_prober_logic(spec_file, httpx_mock):
    # We expect 2 endpoints * 2 samples = 4 requests
    # Register 4 responses to be consumed
    for _ in range(4):
        httpx_mock.add_response(status_code=200)

    prober = APIProber(spec_file=spec_file, api_prefix="http://api.test.com/v1", samples=2)

    await prober.probe()

    requests = httpx_mock.get_requests()
    assert len(requests) == 4

    # Verify URLs
    urls = sorted([str(r.url) for r in requests])
    # http://api.test.com/v1/login
    # http://api.test.com/v1/users/1
    # appearing twice each

    assert "http://api.test.com/v1/login" in urls[0]
    assert "http://api.test.com/v1/users/1" in urls[-1]
