"""Tests for personal access tokens, against a fake S3 double."""

import unittest
from datetime import datetime, timezone
from io import BytesIO
from unittest.mock import patch

from botocore.exceptions import ClientError
from fastapi import HTTPException
from starlette.requests import Request

from aind_metadata_viz.auth import session, tokens


class _FakeS3:
    """An in-memory stand-in for the handful of S3 calls tokens.py makes."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType=None, **kwargs):
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "nope"}}, "GetObject")
        return {"Body": BytesIO(self.objects[Key])}


def _request_with_header(header_value):
    """Build a bare Starlette Request carrying an Authorization header, no session."""
    headers = [(b"authorization", header_value.encode())] if header_value else []
    scope = {"type": "http", "headers": headers}
    return Request(scope)


class TokenStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.fake = _FakeS3()
        self._s3_patch = patch.object(tokens, "_s3", return_value=self.fake)
        self._s3_patch.start()
        self.addCleanup(self._s3_patch.stop)
        # The in-process manifest cache is module-global; start every test clean.
        tokens._cache = {}
        tokens._cache_loaded_at = 0.0

    def _freeze(self, when):
        patcher = patch.object(tokens, "_now", return_value=when)
        patcher.start()
        self.addCleanup(patcher.stop)


class CreateTokenTests(TokenStoreTestCase):
    def test_returns_a_prefixed_raw_token_once(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        self.assertTrue(created["token"].startswith(tokens.TOKEN_PREFIX))
        self.assertEqual(created["label"], "laptop CLI")
        self.assertEqual(len(created["id"]), 8)

    def test_stores_only_the_hash_not_the_raw_value(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        manifest = tokens._load_manifest(force=True)
        self.assertNotIn(created["token"], manifest)
        stored = next(iter(manifest.values()))
        self.assertNotEqual(stored, created["token"])

    def test_ttl_is_clamped_to_the_maximum(self):
        created = tokens.create_token("0000-0001", "Ada", "x", ttl_days=10_000)
        expires = datetime.fromisoformat(created["expires_at"])
        created_at = datetime.fromisoformat(created["created_at"])
        self.assertLessEqual((expires - created_at).days, tokens.MAX_TTL_DAYS)


class ResolveTokenTests(TokenStoreTestCase):
    def test_a_freshly_created_token_resolves_to_its_owner(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        resolved = tokens.resolve_token(created["token"])
        self.assertEqual(resolved, {"orcid": "0000-0001", "name": "Ada"})

    def test_garbage_does_not_resolve(self):
        self.assertIsNone(tokens.resolve_token("not-a-real-token"))

    def test_wrong_prefix_does_not_resolve(self):
        self.assertIsNone(tokens.resolve_token("ghp_somethingelse"))

    def test_unknown_token_with_correct_prefix_does_not_resolve(self):
        self.assertIsNone(tokens.resolve_token(tokens.TOKEN_PREFIX + "neverissued"))

    def test_expired_token_does_not_resolve(self):
        self._freeze(datetime(2020, 1, 1, tzinfo=timezone.utc))
        created = tokens.create_token("0000-0001", "Ada", "old token", ttl_days=1)
        self._freeze(datetime(2020, 1, 10, tzinfo=timezone.utc))
        self.assertIsNone(tokens.resolve_token(created["token"]))

    def test_revoked_token_does_not_resolve(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        tokens.revoke_token("0000-0001", created["id"])
        self.assertIsNone(tokens.resolve_token(created["token"]))

    def test_updates_last_used_at_on_first_use(self):
        self._freeze(datetime(2020, 1, 1, tzinfo=timezone.utc))
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        tokens.resolve_token(created["token"])
        entry = tokens._load_manifest(force=True)[tokens._hash(created["token"])]
        self.assertEqual(entry["last_used_at"], "2020-01-01T00:00:00+00:00")

    def test_does_not_rewrite_last_used_at_within_the_throttle_window(self):
        self._freeze(datetime(2020, 1, 1, tzinfo=timezone.utc))
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        tokens.resolve_token(created["token"])
        self._freeze(datetime(2020, 1, 1, 0, 1, tzinfo=timezone.utc))  # one minute later
        tokens.resolve_token(created["token"])
        entry = tokens._load_manifest(force=True)[tokens._hash(created["token"])]
        self.assertEqual(entry["last_used_at"], "2020-01-01T00:00:00+00:00")


class ListAndRevokeTests(TokenStoreTestCase):
    def test_list_only_returns_the_caller_own_tokens(self):
        tokens.create_token("0000-0001", "Ada", "ada's token")
        tokens.create_token("0000-0002", "Bea", "bea's token")
        listed = tokens.list_tokens("0000-0001")
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["label"], "ada's token")

    def test_listed_entries_never_carry_the_raw_or_hash_value(self):
        tokens.create_token("0000-0001", "Ada", "laptop CLI")
        listed = tokens.list_tokens("0000-0001")
        self.assertNotIn("token", listed[0])
        self.assertNotIn("hash", listed[0])

    def test_revoke_returns_false_for_a_nonexistent_id(self):
        self.assertFalse(tokens.revoke_token("0000-0001", "deadbeef"))

    def test_cannot_revoke_someone_elses_token(self):
        created = tokens.create_token("0000-0002", "Bea", "bea's token")
        self.assertFalse(tokens.revoke_token("0000-0001", created["id"]))
        # And it still resolves - the attempt had no effect.
        self.assertIsNotNone(tokens.resolve_token(created["token"]))

    def test_revoke_is_idempotent(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        self.assertTrue(tokens.revoke_token("0000-0001", created["id"]))
        self.assertTrue(tokens.revoke_token("0000-0001", created["id"]))


class BearerAuthIntegrationTests(TokenStoreTestCase):
    def test_get_current_user_accepts_a_valid_bearer_token(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        request = _request_with_header(f"Bearer {created['token']}")
        user = session.get_current_user(request)
        self.assertEqual(user["orcid"], "0000-0001")

    def test_get_current_user_rejects_a_missing_header(self):
        request = _request_with_header(None)
        self.assertIsNone(session.get_current_user(request))

    def test_get_current_user_rejects_a_malformed_header(self):
        request = _request_with_header("Token abc123")
        self.assertIsNone(session.get_current_user(request))

    def test_get_current_user_rejects_a_revoked_token(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        tokens.revoke_token("0000-0001", created["id"])
        request = _request_with_header(f"Bearer {created['token']}")
        self.assertIsNone(session.get_current_user(request))

    def test_require_user_accepts_a_bearer_token(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        request = _request_with_header(f"Bearer {created['token']}")
        user = session.require_user(request)
        self.assertEqual(user["orcid"], "0000-0001")

    def test_require_browser_user_rejects_a_bearer_token(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        request = _request_with_header(f"Bearer {created['token']}")
        with self.assertRaises(HTTPException) as ctx:
            session.require_browser_user(request)
        self.assertEqual(ctx.exception.status_code, 401)

    def test_get_browser_user_ignores_a_valid_bearer_token(self):
        created = tokens.create_token("0000-0001", "Ada", "laptop CLI")
        request = _request_with_header(f"Bearer {created['token']}")
        self.assertIsNone(session.get_browser_user(request))


if __name__ == "__main__":
    unittest.main()
