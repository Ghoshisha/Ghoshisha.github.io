"""Server-side retrieval of student signature images from Google Drive.

Spec §4.4 and §9.8, refined by Appendix A.6. This is the most failure-prone part of the
system: links that were never shared publicly, Drive's virus-scan interstitial returning
HTML where an image was expected, and a free-tier request timeout if we fetch more than
we need. Every one of those is handled into the manifest rather than aborting a batch.

A signature that comes back as anything but a real image is rejected -- never embedded.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from tempfile import gettempdir

import httpx

logger = logging.getLogger(__name__)

#: Primary endpoint -- what the teacher's own SignURL formula used. Server-side
#: size-capped, so a 4MB phone photo costs one small transfer (Appendix A.6).
THUMBNAIL_URL = "https://docs.google.com/thumbnail?sz=w{width}&id={file_id}"
#: Fallback -- serves the original bytes, and can return the virus-scan interstitial.
DOWNLOAD_URL = "https://drive.google.com/uc?export=download&id={file_id}"

DEFAULT_WIDTH = 500
DEFAULT_CONCURRENCY = 10
DEFAULT_TIMEOUT = 20.0
#: A signature is a small image. Anything larger is a document scan or an error page.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

#: Magic bytes, checked because Content-Type alone lies on the interstitial path.
_IMAGE_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"BM", "image/bmp"),
)


def sniff_image_type(data: bytes) -> str | None:
    """Identify an image by its magic bytes, or ``None`` if it is not one.

    Drive answers an unshared or scan-pending file with an HTML page and a 200 status,
    so trusting the response's own Content-Type would embed a web page as a signature.
    """
    if not data:
        return None
    for prefix, media_type in _IMAGE_SIGNATURES:
        if data.startswith(prefix):
            return media_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


@dataclass
class FetchResult:
    roll: str
    file_id: str | None
    data: bytes | None = None
    media_type: str | None = None
    error: str | None = None
    from_cache: bool = False

    @property
    def ok(self) -> bool:
        return self.data is not None


class ImageCache:
    """On-disk cache keyed by Drive file ID (spec §4.4 item 5).

    Lives in the system temp directory for the lifetime of the instance. It does not
    survive a Render cold start, which the spec accepts for this version.
    """

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or Path(gettempdir()) / "topsheet-signature-cache"
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, file_id: str) -> Path:
        # File IDs are URL-safe but not necessarily filesystem-safe at length.
        return self.directory / hashlib.sha256(file_id.encode()).hexdigest()[:32]

    def get(self, file_id: str) -> bytes | None:
        path = self._path(file_id)
        try:
            return path.read_bytes() if path.exists() else None
        except OSError:
            return None

    def put(self, file_id: str, data: bytes) -> None:
        try:
            # Write via a temp name so a crash mid-write cannot leave a truncated image.
            temp = self._path(file_id).with_suffix(".part")
            temp.write_bytes(data)
            temp.replace(self._path(file_id))
        except OSError as exc:
            logger.warning("could not cache %s: %s", file_id, exc)


#: Drive's interstitial has appeared with both quote styles and with the token in a
#: form field or in a download href, so all three shapes are accepted.
_CONFIRM_PATTERNS = (
    re.compile(r"""name=['"]confirm['"][^>]*?value=['"]([^'"]+)['"]""", re.I),
    re.compile(r"""value=['"]([^'"]+)['"][^>]*?name=['"]confirm['"]""", re.I),
    re.compile(r"confirm=([0-9A-Za-z_-]+)"),
)


def _confirm_token(html: bytes) -> str | None:
    """Pull the virus-scan confirmation token out of Drive's interstitial page."""
    text = html[:20000].decode("utf-8", errors="replace")
    for pattern in _CONFIRM_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


async def _fetch_one(
    client: httpx.AsyncClient,
    roll: str,
    file_id: str,
    cache: ImageCache | None,
    width: int,
) -> FetchResult:
    if cache and (cached := cache.get(file_id)) is not None:
        media_type = sniff_image_type(cached)
        if media_type:
            return FetchResult(roll, file_id, cached, media_type, from_cache=True)

    attempts: list[str] = [
        THUMBNAIL_URL.format(width=width, file_id=file_id),
        DOWNLOAD_URL.format(file_id=file_id),
    ]

    last_error = "no response"
    for url in attempts:
        try:
            response = await client.get(url, follow_redirects=True)
        except httpx.TimeoutException:
            last_error = "timed out fetching the signature from Google Drive"
            continue
        except httpx.HTTPError as exc:
            last_error = f"network error fetching the signature ({type(exc).__name__})"
            continue

        if response.status_code in (401, 403):
            last_error = (
                "signature not accessible - check that the Drive file is shared as "
                "'Anyone with the link'"
            )
            continue
        if response.status_code == 404:
            last_error = "signature file not found on Drive (deleted or wrong link)"
            continue
        if response.status_code >= 400:
            last_error = f"Drive returned HTTP {response.status_code}"
            continue

        data = response.content
        if len(data) > MAX_IMAGE_BYTES:
            last_error = (
                f"signature image is too large ({len(data) // 1024}KB); "
                f"ask the student to re-upload a smaller image"
            )
            continue

        media_type = sniff_image_type(data)
        if media_type:
            if cache:
                cache.put(file_id, data)
            return FetchResult(roll, file_id, data, media_type)

        # Not an image: the virus-scan interstitial. Retry once with its token.
        token = _confirm_token(data)
        if token:
            # copy_merge_params, not params= -- the latter REPLACES the query string,
            # which would drop the file id and request a bare uc?confirm=<token>.
            confirm_url = httpx.URL(url).copy_merge_params({"confirm": token})
            try:
                confirmed = await client.get(confirm_url, follow_redirects=True)
            except httpx.HTTPError:
                last_error = "could not follow Drive's download confirmation page"
                continue
            media_type = sniff_image_type(confirmed.content)
            if media_type:
                if cache:
                    cache.put(file_id, confirmed.content)
                return FetchResult(roll, file_id, confirmed.content, media_type)

        last_error = (
            "could not retrieve signature (Drive returned a web page, not an image) - "
            "the link is most likely not shared publicly"
        )

    return FetchResult(roll, file_id, error=last_error)


async def fetch_signatures(
    wanted: dict[str, str],
    *,
    concurrency: int = DEFAULT_CONCURRENCY,
    timeout: float = DEFAULT_TIMEOUT,
    width: int = DEFAULT_WIDTH,
    cache: ImageCache | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, FetchResult]:
    """Fetch signature images for ``{roll: drive_file_id}``, bounded and concurrent.

    Only the rolls present in the uploaded marks sheet should ever reach here (§4.4
    item 1) -- fetching all ~760 known students would exhaust the free tier's request
    timeout. Never raises for a single bad link; every failure comes back as a
    :class:`FetchResult` carrying an ``error`` for the manifest.

    ``cache=None`` means no caching at all -- callers that want one pass it explicitly,
    so a shared on-disk cache can never appear by accident and serve stale images.
    ``transport`` is an injection point for tests; production callers leave it unset.
    """
    if not wanted:
        return {}

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(max_connections=max(1, concurrency)),
        headers={"User-Agent": "topsheet-generator/1.0"},
        transport=transport,
    ) as client:

        async def run(roll: str, file_id: str) -> FetchResult:
            async with semaphore:
                return await _fetch_one(client, roll, file_id, cache, width)

        results = await asyncio.gather(
            *(run(roll, file_id) for roll, file_id in wanted.items())
        )

    return {result.roll: result for result in results}
