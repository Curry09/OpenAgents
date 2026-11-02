"""Spec-0092/T2: inspect actual urllib requests, bounds, and redirect authentication."""

import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from openagents.utils import gitea

UID = "12345678-1234-1234-1234-123456789012"
R2 = "https://" + "a" * 32 + ".r2.cloudflarestorage.com/evidence?signature=private"


class Response(io.BytesIO):
    status = 200

    def read1(self, size):
        return self.read(size)


def redirect(url=R2, code=303):
    return urllib.error.HTTPError("hidden", code, "redirect", {"Location": url}, io.BytesIO())


def install(monkeypatch, replies, base="https://gitea.com"):
    gitea.configure(settings={"base_url": base, "owner": "o", "repo": "r"})
    monkeypatch.setenv("GITEA_TOKEN", "secret-token")
    requests = []
    replies = iter(replies)

    def opener(handler):
        assert handler.redirect_request(None, None, 302, "", {}, R2) is None

        def read(req, timeout):
            requests.append(req)
            assert 0 < timeout <= 5
            result = next(replies)
            if isinstance(result, Exception):
                raise result
            return Response(result)

        return SimpleNamespace(open=read)

    monkeypatch.setattr(gitea.urllib.request, "build_opener", opener)
    return requests


def metadata():
    return json.dumps([{"id": 1, "uuid": UID, "browser_download_url": "https://evil"}]).encode()


def test_hosted_download_strips_credentials_and_does_not_read_netrc(monkeypatch, tmp_path):
    (tmp_path / ".netrc").write_text("default login unintended password unintended")
    monkeypatch.setenv("HOME", str(tmp_path))
    reqs = install(monkeypatch, [metadata(), redirect(), b"content"])
    assert gitea.download_observation_asset(number=7, asset_id=1, limit=7) == b"content"
    assert [r.full_url for r in reqs] == [
        "https://gitea.com/api/v1/repos/o/r/issues/7/assets",
        f"https://gitea.com/attachments/{UID}",
        R2,
    ]
    assert reqs[0].get_header("Authorization") == "token secret-token"
    assert reqs[1].get_header("Authorization") == "token secret-token"
    assert dict(reqs[2].header_items()) == {"Accept-encoding": "identity"}


@pytest.mark.parametrize(
    "target",
    [
        "http://" + "a" * 32 + ".r2.cloudflarestorage.com/x",
        "https://127.0.0.1/x",
        R2.replace(".com/", ".com.evil/"),
        R2.replace("https://", "https://user:pass@"),
        R2.replace(".com/", ".com:444/"),
        R2 + "#fragment",
        "//evil/x",
        "https://evil/x",
        R2.replace("a" * 32, "not-an-account"),
    ],
)
def test_redirect_targets_refused(monkeypatch, target):
    reqs = install(monkeypatch, [metadata(), redirect(target)])
    with pytest.raises(ValueError, match="refused"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=10)
    assert len(reqs) == 2


@pytest.mark.parametrize(
    "base",
    ["http://gitea.com", "https://gitea.com.evil", "http://internal", "https://gitea.com/path"],
)
def test_other_sites_cannot_redirect(monkeypatch, base):
    reqs = install(monkeypatch, [metadata(), redirect()], base)
    with pytest.raises(ValueError):
        gitea.download_observation_asset(number=7, asset_id=1, limit=10)
    assert len(reqs) == 2


def test_api_redirect_and_second_redirect_refused(monkeypatch):
    reqs = install(monkeypatch, [redirect()])
    with pytest.raises(ValueError):
        gitea.download_observation_asset(number=7, asset_id=1, limit=10)
    assert len(reqs) == 1
    reqs = install(monkeypatch, [metadata(), redirect(), redirect()])
    with pytest.raises(ValueError):
        gitea.download_observation_asset(number=7, asset_id=1, limit=10)
    assert len(reqs) == 3


def test_content_budget_and_sanitized_network_failure(monkeypatch):
    install(monkeypatch, [metadata(), redirect(), b"123456"])
    with pytest.raises(ValueError, match="budget"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)
    install(monkeypatch, [metadata(), redirect(), OSError(R2)])
    with pytest.raises(ValueError) as caught:
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)
    assert "signature" not in str(caught.value)


def test_redirect_shares_deadline(monkeypatch):
    install(monkeypatch, [metadata(), redirect(), b"x"])
    ticks = iter([0, 0, 0, 0, 0, 0, 0, 0, 16])
    monkeypatch.setattr(gitea, "time", SimpleNamespace(monotonic=lambda: next(ticks, 16)))
    with pytest.raises(ValueError, match="budget"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)


@pytest.mark.parametrize("status", [201, 204, 206])
def test_final_response_must_be_200(monkeypatch, status):
    install(monkeypatch, [metadata(), redirect(), b"x"])
    original = Response.status
    # Apply to all responses: metadata API itself must also be a direct 200.
    monkeypatch.setattr(Response, "status", status)
    with pytest.raises(ValueError, match="refused"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)
    assert original == 200


def test_non_member_never_requests_download(monkeypatch):
    reqs = install(monkeypatch, [b"[]"])
    with pytest.raises(ValueError, match="outside issue"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)
    assert len(reqs) == 1


def test_actual_read_size_is_bounded(monkeypatch):
    install(monkeypatch, [metadata(), redirect(), b"123456"])
    sizes = []
    original = Response.read1

    def bounded(self, size):
        sizes.append(size)
        return original(self, size)

    monkeypatch.setattr(Response, "read1", bounded)
    with pytest.raises(ValueError, match="budget"):
        gitea.download_observation_asset(number=7, asset_id=1, limit=5)
    assert sizes[-1] == 6
