"""Tests for the ORCID session cookie the app hands out.

A frontend served from another subdomain reaches these endpoints through a
same-origin reverse proxy, so the cookie has to be scoped to the shared parent
domain for the OAuth callback (which runs on the backend's own host) to be
usable from that frontend.
"""

import importlib
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient


def _login_cookie_header(**env) -> str:
    """Return the raw Set-Cookie header a login start emits under *env*.

    @param env Environment variables to build the app with.
    """
    with mock.patch.dict(os.environ, env, clear=False):
        main = importlib.reload(importlib.import_module("aind_metadata_viz.main"))
        client = TestClient(main.app)
        response = client.get("/auth/orcid/login?next=/", follow_redirects=False)
        return response.headers.get("set-cookie", "")


class TestSessionCookieDomain(unittest.TestCase):
    def tearDown(self):
        # Leave the module in its unconfigured state for other test modules.
        importlib.reload(importlib.import_module("aind_metadata_viz.main"))

    def test_cookie_is_host_only_by_default(self):
        header = _login_cookie_header(SESSION_COOKIE_DOMAIN="").lower()

        self.assertIn("session=", header)
        self.assertNotIn("domain=", header)

    def test_cookie_is_widened_to_the_configured_domain(self):
        header = _login_cookie_header(
            SESSION_COOKIE_DOMAIN=".allenneuraldynamics.org"
        ).lower()

        self.assertIn("domain=.allenneuraldynamics.org", header)


if __name__ == "__main__":
    unittest.main()
