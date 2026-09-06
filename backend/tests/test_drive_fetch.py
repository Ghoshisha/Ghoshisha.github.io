"""Drive fetch behaviour (spec §4.4, §9.8; Appendix A.6).

All offline: a transport stub stands in for Drive so the failure paths that matter --
403, the virus-scan interstitial, an HTML body served with a 200 -- are tested
deterministically. The one test that touches the network is opt-in.
"""

from __future__ import annotations

import asyncio
import os

import httpx
import pytest

from app.drive_fetch import (
    DOWNLOAD_URL,
    THUMBNAIL_URL,
    ImageCache,
    fetch_signatures,
    sniff_image_type,
)

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
INTERSTITIAL = (
    b"<html><body><form action='/uc'>"
    b"<input type='hidden' name='confirm' value='t-abc123'>"
    b"</form></body></html>"
)
ABHISHA_DRIVE_ID = "12uZuuQ3MIeNzTPD-u41bZSrgFyLIrYOF"


class TestSniffImageType:
    @pytest.mark.parametrize(
        "data, expected",
        [
            (PNG, "image/png"),
            (JPEG, "image/jpeg"),
            (b"GIF89a....", "image/gif"),
            (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
        ],
    )
    def test_recognises_real_images(self, data, expected):
        assert sniff_image_type(data) == expected

    @pytest.mark.parametrize("data", [INTERSTITIAL, b"<!DOCTYPE html>", b"", b"not an image"])
    def test_rejects_everything_else(self, data):
        """§9.8: an HTML page must be rejected, never embedded as a broken image."""
        assert sniff_image_type(data) is None


async def _fetch(handler, wanted, **kwargs):
    """Run fetch_signatures against a stubbed Drive."""
    return await fetch_signatures(
        wanted, transport=httpx.MockTransport(handler), **kwargs
    )


class TestFetchSignatures:
    def test_fetches_an_image(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

        results = asyncio.run(
            _fetch(handler, {"25371025001": "abc"}, cache=ImageCache(tmp_path))
        )
        result = results["25371025001"]
        assert result.ok
        assert result.media_type == "image/png"
        assert result.error is None

    def test_prefers_the_thumbnail_endpoint(self, tmp_path):
        """Appendix A.6 -- the size-capped endpoint is tried first."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(200, content=PNG)

        asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        assert seen[0] == THUMBNAIL_URL.format(width=500, file_id="abc")

    def test_falls_back_to_the_download_endpoint(self, tmp_path):
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            if "thumbnail" in str(request.url):
                return httpx.Response(404)
            return httpx.Response(200, content=PNG)

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        assert results["r"].ok
        assert DOWNLOAD_URL.format(file_id="abc") in seen

    def test_403_becomes_a_sharing_message_not_a_crash(self, tmp_path):
        """§4.4 item 4 -- the original workflow's most common failure."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(403)

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        result = results["r"]
        assert not result.ok
        assert "Anyone with the link" in result.error

    def test_handles_the_virus_scan_interstitial(self, tmp_path):
        """§4.4 item 3 -- HTML first, the real bytes after the confirm token."""
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            # Drive only serves the file if the id survives alongside the token.
            if "confirm" in request.url.params and request.url.params.get("id") == "abc":
                return httpx.Response(200, content=JPEG)
            if "confirm" in request.url.params:
                return httpx.Response(400, content=b"missing file id")
            return httpx.Response(
                200, content=INTERSTITIAL, headers={"Content-Type": "text/html"}
            )

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        assert results["r"].ok, results["r"].error
        assert results["r"].media_type == "image/jpeg"

        retry = [c for c in calls if "confirm" in c.url.params]
        assert retry, "the confirm token should trigger a second request"
        # params= would have replaced the query and lost these.
        assert retry[0].url.params.get("id") == "abc"
        assert retry[0].url.params.get("confirm") == "t-abc123"

    def test_html_with_no_token_is_rejected(self, tmp_path):
        """A 200 carrying a web page is a failure, not a signature."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"<html>Sign in</html>", headers={"Content-Type": "image/png"}
            )

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        result = results["r"]
        assert not result.ok
        assert "not an image" in result.error

    def test_oversized_response_is_rejected(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PNG + b"\x00" * (9 * 1024 * 1024))

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=ImageCache(tmp_path)))
        assert not results["r"].ok
        assert "too large" in results["r"].error

    def test_a_timeout_does_not_fail_the_batch(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("too slow", request=request)

        results = asyncio.run(
            _fetch(handler, {"good": "abc", "bad": "def"}, cache=ImageCache(tmp_path))
        )
        assert len(results) == 2
        assert all(not r.ok and "timed out" in r.error for r in results.values())

    def test_one_bad_link_does_not_stop_the_others(self, tmp_path):
        def handler(request: httpx.Request) -> httpx.Response:
            if "bad" in str(request.url):
                return httpx.Response(403)
            return httpx.Response(200, content=PNG)

        results = asyncio.run(
            _fetch(handler, {"a": "good1", "b": "bad", "c": "good2"}, cache=ImageCache(tmp_path))
        )
        assert results["a"].ok and results["c"].ok
        assert not results["b"].ok

    def test_empty_request_makes_no_calls(self):
        assert asyncio.run(fetch_signatures({})) == {}


class TestImageCache:
    def test_second_fetch_is_served_from_cache(self, tmp_path):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=PNG)

        cache = ImageCache(tmp_path)
        asyncio.run(_fetch(handler, {"r": "abc"}, cache=cache))
        second = asyncio.run(_fetch(handler, {"r": "abc"}, cache=cache))
        assert calls == 1
        assert second["r"].from_cache is True
        assert second["r"].ok

    def test_two_students_sharing_a_file_id_hit_the_network_once(self, tmp_path):
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            return httpx.Response(200, content=PNG)

        cache = ImageCache(tmp_path)
        asyncio.run(_fetch(handler, {"a": "same"}, cache=cache))
        asyncio.run(_fetch(handler, {"b": "same"}, cache=cache))
        assert calls == 1

    def test_a_corrupt_cache_entry_is_ignored(self, tmp_path):
        cache = ImageCache(tmp_path)
        cache.put("abc", b"<html>not an image</html>")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=PNG)

        results = asyncio.run(_fetch(handler, {"r": "abc"}, cache=cache))
        assert results["r"].ok
        assert results["r"].from_cache is False


@pytest.mark.skipif(
    os.environ.get("TOPSHEET_NETWORK_TESTS") != "1",
    reason="set TOPSHEET_NETWORK_TESTS=1 to test against real Google Drive",
)
def test_real_drive_fetch_of_the_reference_signature(tmp_path):
    """Appendix A.6 -- the endpoint choice, verified against the actual file."""
    results = asyncio.run(
        fetch_signatures({"25371025001": ABHISHA_DRIVE_ID}, cache=ImageCache(tmp_path))
    )
    result = results["25371025001"]
    assert result.ok, result.error
    assert result.media_type in ("image/png", "image/jpeg")
