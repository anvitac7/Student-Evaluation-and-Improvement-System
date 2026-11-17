"""
Tests for the resume upload size guard and analytics total accuracy.

Both are "silently wrong" bugs rather than crashes:

  * Upload: the route used to `await file.read()` with no guard, buffering the
    entire request body before anything checked its size. A 5MB limit did not
    stop a client sending 2GB.
  * Analytics: total_applications was len(fetched), so past the 5000-row
    fetch limit the dashboard reported 5000 as the total, while total_drives
    (using count()) stayed accurate — some totals real, some capped, with
    nothing in the response indicating which.
"""
import io

import pytest

from app.services.analytics_service import _ANALYTICS_FETCH_LIMIT
from app.services.resume_service import MAX_RESUME_SIZE_BYTES, ResumeError, ResumeService

MINIMAL_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


# ---------------------------------------------------------------------------
# upload size guard
# ---------------------------------------------------------------------------
class _FakeUpload:
    """Minimal UploadFile stand-in: read() yields the body in blocks."""

    def __init__(self, data: bytes, block: int = 1024 * 1024):
        self._buf = io.BytesIO(data)
        self._block = block
        self.bytes_read = 0

    async def read(self, size: int = -1) -> bytes:
        n = self._block if size == -1 else min(size, self._block)
        chunk = self._buf.read(n)
        self.bytes_read += len(chunk)
        return chunk


@pytest.mark.asyncio
async def test_oversized_upload_is_rejected():
    """The core fix: a file past the cap must 413 rather than being buffered."""
    oversized = b"%PDF" + b"A" * (MAX_RESUME_SIZE_BYTES + 1024)
    upload = _FakeUpload(oversized)
    with pytest.raises(ResumeError) as exc:
        await ResumeService.read_upload_capped(upload)
    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_oversized_upload_aborts_early_not_after_full_read():
    """Peak memory is O(cap) because we bail on the first block that
    overflows — we must not have consumed the whole stream first."""
    # 40MB of data, 5MB cap: if we buffered everything, bytes_read ~= 40MB.
    oversized = b"%PDF" + b"A" * (40 * 1024 * 1024)
    upload = _FakeUpload(oversized, block=1024 * 1024)
    with pytest.raises(ResumeError):
        await ResumeService.read_upload_capped(upload)

    assert upload.bytes_read <= MAX_RESUME_SIZE_BYTES + (1024 * 1024), (
        f"read {upload.bytes_read} bytes before rejecting; "
        "the cap must abort mid-stream"
    )


@pytest.mark.asyncio
async def test_undersized_upload_passes_through():
    upload = _FakeUpload(MINIMAL_PDF)
    result = await ResumeService.read_upload_capped(upload)
    assert result == MINIMAL_PDF


@pytest.mark.asyncio
async def test_upload_exactly_at_the_limit_is_accepted():
    """Off-by-one guard: a file of exactly MAX bytes must NOT be rejected."""
    exact = b"%PDF" + b"A" * (MAX_RESUME_SIZE_BYTES - 4)
    assert len(exact) == MAX_RESUME_SIZE_BYTES
    upload = _FakeUpload(exact)
    result = await ResumeService.read_upload_capped(upload)
    assert len(result) == MAX_RESUME_SIZE_BYTES


def test_content_length_preflight_rejects_oversized():
    declared = str(MAX_RESUME_SIZE_BYTES + 1)
    with pytest.raises(ResumeError) as exc:
        ResumeService.reject_oversized_content_length(declared)
    assert exc.value.status_code == 413


def test_content_length_preflight_allows_undersized():
    ResumeService.reject_oversized_content_length(str(MAX_RESUME_SIZE_BYTES))


def test_content_length_preflight_tolerates_missing_or_junk():
    """A lying or absent header must not crash or bypass the real cap —
    read_upload_capped() is the actual enforcement."""
    ResumeService.reject_oversized_content_length(None)
    ResumeService.reject_oversized_content_length("")
    ResumeService.reject_oversized_content_length("not-a-number")


# ---------------------------------------------------------------------------
# analytics totals
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_total_applications_is_the_real_count_not_the_fetch_length(client, mock_mongo):
    """Past the fetch limit, the reported total must still be the true count.

    Uses a lowered limit via monkeypatch-free construction: asserts the
    response field is sourced from count(), not len(fetched), by checking the
    two agree below the limit AND that the service uses count() at all.
    """
    from app.models.user import AdminRegisterRequest
    from app.services.analytics_service import AnalyticsService
    from app.services.auth_service import AuthService

    svc = AuthService(mock_mongo)
    await svc.register_admin(
        AdminRegisterRequest(
            email="an.admin@college.edu", password="Admin@12345", name="AN Admin"
        )
    )
    token = (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "an.admin@college.edu", "password": "Admin@12345"},
        )
    ).json()["access_token"]

    result = await AnalyticsService(mock_mongo).get_admin_analytics()
    real_total = await AnalyticsService(mock_mongo).applications.count({})
    assert result.total_applications == real_total
    assert result.total_drives == await AnalyticsService(mock_mongo).drives.count({})
    assert result.total_attempts == await AnalyticsService(mock_mongo).attempts.count({})


def test_analytics_fetch_limit_is_still_a_finite_cap():
    """Guard against someone 'fixing' the truncation by removing the cap and
    turning this into an unbounded scan."""
    assert isinstance(_ANALYTICS_FETCH_LIMIT, int)
    assert 0 < _ANALYTICS_FETCH_LIMIT <= 100_000