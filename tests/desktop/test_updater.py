"""Update-checker unit tests. All network is faked via pytest-httpx."""

from __future__ import annotations

import httpx
from pytest_httpx import HTTPXMock

from desktop import updater


class TestSemverKey:
    def test_basic_triplet(self) -> None:
        assert updater._semver_key("1.2.3") == (1, 2, 3)

    def test_v_prefix_stripped(self) -> None:
        assert updater._semver_key("v0.4.1") == (0, 4, 1)

    def test_prerelease_suffix_stripped(self) -> None:
        assert updater._semver_key("1.0.0-rc1") == (1, 0, 0)

    def test_double_digit_minor_greater_than_single(self) -> None:
        assert updater._semver_key("0.10.0") > updater._semver_key("0.9.99")


class TestIsNewer:
    def test_higher_patch(self) -> None:
        assert updater.is_newer("0.5.1", baseline="0.5.0")

    def test_same_version(self) -> None:
        assert not updater.is_newer("0.5.0", baseline="0.5.0")

    def test_lower_version(self) -> None:
        assert not updater.is_newer("0.4.9", baseline="0.5.0")


class TestCheckLatest:
    URL = "https://api.github.com/repos/example/repo/releases/latest"

    def test_returns_none_when_no_release_newer(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=self.URL,
            json={"tag_name": "v0.5.0", "html_url": "https://example/release/v0.5.0"},
        )
        assert updater.check_latest("example/repo", baseline="0.5.0") is None

    def test_returns_tuple_when_newer(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url=self.URL,
            json={"tag_name": "v0.6.0", "html_url": "https://example/release/v0.6.0"},
        )
        got = updater.check_latest("example/repo", baseline="0.5.0")
        assert got == ("0.6.0", "https://example/release/v0.6.0")

    def test_swallows_http_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=self.URL, status_code=503)
        assert updater.check_latest("example/repo") is None

    def test_swallows_network_error(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_exception(httpx.ConnectError("no route"))
        assert updater.check_latest("example/repo") is None

    def test_missing_fields_return_none(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=self.URL, json={"tag_name": "v0.6.0"})  # no html_url
        assert updater.check_latest("example/repo", baseline="0.5.0") is None

    def test_non_json_response_returns_none(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(url=self.URL, text="not json")
        assert updater.check_latest("example/repo") is None
