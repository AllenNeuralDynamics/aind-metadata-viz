import json
import unittest
from datetime import date
from io import BytesIO
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError

from tornado.testing import AsyncHTTPTestCase
from tornado.web import Application

from aind_data_schema_models.registries import Registry
from pydantic import ValidationError

from aind_metadata_viz.contributions.models import (
    Author,
    AuthorContribution,
    ContributionLevel,
    CreditRole,
    ProjectContributions,
    RoleContribution,
)
from aind_metadata_viz.contributions.serializers import (
    from_json,
    from_yaml,
    load,
    to_json,
    to_yaml,
)
from aind_metadata_viz.contributions.store import (
    _safe_filename,
    get_contributions,
    get_contributions_by_doi,
    list_project_commits,
    set_project_password,
    store_contributions,
    verify_project_password,
    create_token,
    lookup_token,
    consume_token,
)
from aind_metadata_viz.contributions.handlers import CONTRIBUTION_ROUTES


class _FakePaginator:
    def __init__(self, store):
        self._store = store

    def paginate(self, Bucket, Prefix="", Delimiter=None):
        keys = sorted(k for k in self._store if k.startswith(Prefix))
        if Delimiter:
            prefixes = set()
            contents = []
            for k in keys:
                rest = k[len(Prefix):]
                idx = rest.find(Delimiter)
                if idx >= 0:
                    prefixes.add(Prefix + rest[: idx + 1])
                else:
                    contents.append({"Key": k})
            yield {
                "CommonPrefixes": [{"Prefix": p} for p in sorted(prefixes)],
                "Contents": contents,
            }
        else:
            yield {"Contents": [{"Key": k} for k in keys], "CommonPrefixes": []}


class _FakeS3:
    def __init__(self):
        self._store = {}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self._store[Key] = Body if isinstance(Body, bytes) else Body.encode()

    def get_object(self, Bucket, Key):
        if Key not in self._store:
            raise ClientError({"Error": {"Code": "NoSuchKey", "Message": "Not Found"}}, "GetObject")
        return {"Body": BytesIO(self._store[Key])}

    def get_paginator(self, operation_name):
        return _FakePaginator(self._store)


def _s3_patch(fake):
    return patch("aind_metadata_viz.contributions.store._s3", return_value=fake)


def _make_role(role=CreditRole.SOFTWARE, level=ContributionLevel.LEAD):
    return RoleContribution(role=role, level=level)


def _make_author(name="Jane Smith", affiliation=None):
    return Author(
        name=name,
        affiliation=affiliation or ["AIND"],
        registry=Registry.ORCID,
    )


def _make_project(name="test-project"):
    return ProjectContributions(
        project_name=name,
        contributors=[
            AuthorContribution(
                author=_make_author(),
                credit_levels=[_make_role()],
            )
        ],
    )


class TestRoleContribution(unittest.TestCase):
    def test_valid_creation(self):
        r = RoleContribution(role=CreditRole.SOFTWARE, level=ContributionLevel.LEAD)
        self.assertEqual(r.role, CreditRole.SOFTWARE)
        self.assertEqual(r.level, ContributionLevel.LEAD)

    def test_all_roles_valid(self):
        for role in CreditRole:
            r = RoleContribution(role=role, level=ContributionLevel.EQUAL)
            self.assertEqual(r.role, role)

    def test_all_levels_valid(self):
        for level in ContributionLevel:
            r = RoleContribution(role=CreditRole.SOFTWARE, level=level)
            self.assertEqual(r.level, level)

    def test_optional_fields_default_none(self):
        r = _make_role()
        self.assertIsNone(r.start_date)
        self.assertIsNone(r.end_date)
        self.assertIsNone(r.description)
        self.assertIsNone(r.linked_sections)

    def test_dates_valid_range(self):
        r = RoleContribution(
            role=CreditRole.SOFTWARE,
            level=ContributionLevel.LEAD,
            start_date=date(2020, 1, 1),
            end_date=date(2021, 1, 1),
        )
        self.assertEqual(r.start_date, date(2020, 1, 1))

    def test_end_date_without_start_raises(self):
        with self.assertRaises(ValidationError):
            RoleContribution(
                role=CreditRole.SOFTWARE,
                level=ContributionLevel.LEAD,
                end_date=date(2021, 1, 1),
            )

    def test_end_date_before_start_raises(self):
        with self.assertRaises(ValidationError):
            RoleContribution(
                role=CreditRole.SOFTWARE,
                level=ContributionLevel.LEAD,
                start_date=date(2021, 6, 1),
                end_date=date(2021, 1, 1),
            )

    def test_start_date_without_end_date_valid(self):
        r = RoleContribution(
            role=CreditRole.SOFTWARE,
            level=ContributionLevel.LEAD,
            start_date=date(2020, 1, 1),
        )
        self.assertIsNone(r.end_date)

    def test_same_start_and_end_date_valid(self):
        r = RoleContribution(
            role=CreditRole.SOFTWARE,
            level=ContributionLevel.LEAD,
            start_date=date(2021, 1, 1),
            end_date=date(2021, 1, 1),
        )
        self.assertEqual(r.start_date, r.end_date)

    def test_description_and_linked_sections(self):
        r = RoleContribution(
            role=CreditRole.VISUALIZATION,
            level=ContributionLevel.SUPPORTING,
            description="Made figures",
            linked_sections=["Methods", "Results"],
        )
        self.assertEqual(r.description, "Made figures")
        self.assertEqual(r.linked_sections, ["Methods", "Results"])

    def test_invalid_role_raises(self):
        with self.assertRaises(ValidationError):
            RoleContribution(role="not-a-role", level=ContributionLevel.LEAD)

    def test_invalid_level_raises(self):
        with self.assertRaises(ValidationError):
            RoleContribution(role=CreditRole.SOFTWARE, level="not-a-level")


class TestAuthor(unittest.TestCase):
    def test_valid_creation(self):
        a = Author(name="Alice", affiliation=["AIND"], registry=Registry.ORCID)
        self.assertEqual(a.name, "Alice")

    def test_affiliation_defaults_empty(self):
        a = Author(name="Alice", registry=Registry.ORCID)
        self.assertEqual(a.affiliation, [])

    def test_email_optional(self):
        a = Author(name="Alice", registry=Registry.ORCID)
        self.assertIsNone(a.email)

    def test_email_stored(self):
        a = Author(name="Alice", registry=Registry.ORCID, email="a@b.com")
        self.assertEqual(a.email, "a@b.com")

    def test_orcid_stored(self):
        a = Author(
            name="Alice",
            registry=Registry.ORCID,
            registry_identifier="0000-0000-0000-0001",
        )
        self.assertEqual(a.registry_identifier, "0000-0000-0000-0001")

    def test_multiple_affiliations(self):
        a = Author(name="Alice", affiliation=["Org A", "Org B"], registry=Registry.ORCID)
        self.assertEqual(len(a.affiliation), 2)


class TestAuthorContribution(unittest.TestCase):
    def test_valid_creation(self):
        ac = AuthorContribution(author=_make_author(), credit_levels=[_make_role()])
        self.assertEqual(len(ac.credit_levels), 1)

    def test_empty_credit_levels(self):
        ac = AuthorContribution(author=_make_author())
        self.assertEqual(ac.credit_levels, [])

    def test_multiple_roles(self):
        ac = AuthorContribution(
            author=_make_author(),
            credit_levels=[
                _make_role(CreditRole.SOFTWARE, ContributionLevel.LEAD),
                _make_role(CreditRole.VISUALIZATION, ContributionLevel.SUPPORTING),
            ],
        )
        self.assertEqual(len(ac.credit_levels), 2)


class TestProjectContributions(unittest.TestCase):
    def test_valid_creation(self):
        pc = ProjectContributions(project_name="my-project")
        self.assertEqual(pc.project_name, "my-project")

    def test_empty_contributors(self):
        pc = ProjectContributions(project_name="p")
        self.assertEqual(pc.contributors, [])

    def test_sections_and_doi(self):
        pc = ProjectContributions(
            project_name="p",
            sections=["Intro", "Methods"],
            doi="10.1234/test",
        )
        self.assertEqual(pc.sections, ["Intro", "Methods"])
        self.assertEqual(pc.doi, "10.1234/test")

    def test_assets(self):
        pc = ProjectContributions(project_name="p", assets=["asset-001"])
        self.assertEqual(pc.assets, ["asset-001"])

    def test_project_name_required(self):
        with self.assertRaises(ValidationError):
            ProjectContributions()

    def test_with_contributors(self):
        pc = _make_project()
        self.assertEqual(len(pc.contributors), 1)
        self.assertEqual(pc.contributors[0].author.name, "Jane Smith")


class TestSerializersJson(unittest.TestCase):
    def setUp(self):
        self.pc = _make_project()

    def test_to_json_returns_string(self):
        result = to_json(self.pc)
        self.assertIsInstance(result, str)

    def test_to_json_valid_json(self):
        result = to_json(self.pc)
        parsed = json.loads(result)
        self.assertEqual(parsed["project_name"], "test-project")

    def test_from_json_roundtrip(self):
        j = to_json(self.pc)
        restored = from_json(j)
        self.assertEqual(restored.project_name, self.pc.project_name)
        self.assertEqual(len(restored.contributors), 1)
        self.assertEqual(restored.contributors[0].author.name, "Jane Smith")

    def test_from_json_roles_preserved(self):
        j = to_json(self.pc)
        restored = from_json(j)
        self.assertEqual(restored.contributors[0].credit_levels[0].role, CreditRole.SOFTWARE)
        self.assertEqual(restored.contributors[0].credit_levels[0].level, ContributionLevel.LEAD)

    def test_from_json_invalid_raises(self):
        with self.assertRaises(Exception):
            from_json("not valid json")

    def test_from_json_missing_project_name_raises(self):
        with self.assertRaises(Exception):
            from_json('{"contributors": []}')


class TestSerializersYaml(unittest.TestCase):
    def setUp(self):
        self.pc = _make_project()

    def test_to_yaml_returns_string(self):
        result = to_yaml(self.pc)
        self.assertIsInstance(result, str)

    def test_to_yaml_contains_project_name(self):
        result = to_yaml(self.pc)
        self.assertIn("test-project", result)

    def test_from_yaml_roundtrip(self):
        y = to_yaml(self.pc)
        restored = from_yaml(y)
        self.assertEqual(restored.project_name, self.pc.project_name)
        self.assertEqual(len(restored.contributors), 1)

    def test_from_yaml_role_preserved(self):
        y = to_yaml(self.pc)
        restored = from_yaml(y)
        self.assertEqual(restored.contributors[0].credit_levels[0].role, CreditRole.SOFTWARE)

    def test_from_yaml_missing_project_name(self):
        y = "version: 1\nproject:\n  contributors: []\n"
        restored = from_yaml(y)
        self.assertEqual(restored.project_name, "")

    def test_from_yaml_unknown_role_skipped(self):
        y = (
            "version: 1\n"
            "project:\n"
            "  name: test-project\n"
            "  contributors:\n"
            "    - name: Alice\n"
            "      credit_levels:\n"
            "        - role: not-a-role\n"
            "          level: lead\n"
        )
        restored = from_yaml(y)
        self.assertEqual(len(restored.contributors[0].credit_levels), 0)

    def test_from_yaml_empty_contributors(self):
        y = "version: 1\nproject:\n  name: empty\n  contributors: []\n"
        restored = from_yaml(y)
        self.assertEqual(restored.contributors, [])


class TestSerializersLoad(unittest.TestCase):
    def setUp(self):
        self.pc = _make_project()

    def test_load_from_json_string(self):
        j = to_json(self.pc)
        restored = load(j)
        self.assertEqual(restored.project_name, "test-project")

    def test_load_from_yaml_string(self):
        y = to_yaml(self.pc)
        restored = load(y)
        self.assertEqual(restored.project_name, "test-project")

    def test_load_from_dict(self):
        d = json.loads(to_json(self.pc))
        restored = load(d)
        self.assertEqual(restored.project_name, "test-project")


class TestSafeFilename(unittest.TestCase):
    def test_simple_name(self):
        self.assertEqual(_safe_filename("my-project"), "my-project.json")

    def test_forward_slash_replaced(self):
        self.assertEqual(_safe_filename("a/b"), "a_b.json")

    def test_backslash_replaced(self):
        self.assertEqual(_safe_filename("a\\b"), "a_b.json")

    def test_multiple_slashes(self):
        self.assertEqual(_safe_filename("a/b/c"), "a_b_c.json")


class TestStore(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._patch = _s3_patch(self._fake)
        self._patch.start()
        self.pc = _make_project("store-test")

    def tearDown(self):
        self._patch.stop()

    def test_store_returns_commit_hash(self):
        commit = store_contributions("store-test", self.pc)
        self.assertIsInstance(commit, str)
        self.assertEqual(len(commit), 32)

    def test_store_and_retrieve(self):
        store_contributions("store-test", self.pc)
        retrieved = get_contributions("store-test")
        self.assertEqual(retrieved.project_name, "store-test")
        self.assertEqual(retrieved.contributors[0].author.name, "Jane Smith")

    def test_store_with_json_string(self):
        j = to_json(self.pc)
        store_contributions("store-test", j)
        retrieved = get_contributions("store-test")
        self.assertEqual(retrieved.project_name, "store-test")

    def test_store_with_dict(self):
        d = json.loads(to_json(self.pc))
        store_contributions("store-test", d)
        retrieved = get_contributions("store-test")
        self.assertEqual(retrieved.project_name, "store-test")

    def test_multiple_commits_retrievable_by_hash(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        hash1 = store_contributions("store-test", pc1)
        store_contributions("store-test", pc2)
        old = get_contributions("store-test", commit_hash=hash1)
        self.assertEqual(old.doi, "10.1/v1")

    def test_get_contributions_head_is_latest(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1)
        store_contributions("store-test", pc2)
        latest = get_contributions("store-test")
        self.assertEqual(latest.doi, "10.1/v2")

    def test_get_contributions_missing_project_raises(self):
        with self.assertRaises(Exception):
            get_contributions("does-not-exist")

    def test_list_project_commits_returns_list(self):
        store_contributions("store-test", self.pc)
        commits = list_project_commits("store-test")
        self.assertIsInstance(commits, list)
        self.assertGreater(len(commits), 0)

    def test_list_project_commits_structure(self):
        store_contributions("store-test", self.pc)
        commits = list_project_commits("store-test")
        entry = commits[0]
        self.assertIn("commit", entry)
        self.assertIn("timestamp", entry)
        self.assertIn("message", entry)

    def test_list_project_commits_newest_first(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1, message="first")
        store_contributions("store-test", pc2, message="second")
        commits = list_project_commits("store-test")
        self.assertEqual(commits[0]["message"], "second")

    def test_list_project_commits_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            list_project_commits("no-such-project")

    def test_store_does_not_recurse_on_fresh_repo(self):
        pc = ProjectContributions(project_name="fresh")
        commit = store_contributions("fresh", pc)
        self.assertIsInstance(commit, str)

    def test_custom_message_stored(self):
        store_contributions("store-test", self.pc, message="my-msg")
        commits = list_project_commits("store-test")
        self.assertEqual(commits[0]["message"], "my-msg")

    def test_default_message_used_when_none(self):
        store_contributions("store-test", self.pc)
        commits = list_project_commits("store-test")
        self.assertIn("store-test", commits[0]["message"])


def _make_project_json(name="handler-project"):
    pc = _make_project(name)
    return to_json(pc)


class ContributionsHandlerTestCase(AsyncHTTPTestCase):
    def get_app(self):
        return Application(CONTRIBUTION_ROUTES)

    def setUp(self):
        self._fake = _FakeS3()
        self._s3_patch = _s3_patch(self._fake)
        self._s3_patch.start()
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._s3_patch.stop()

    def _patch_store(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.store_contributions",
            side_effect=lambda project, data, message=None: store_contributions(project, data, message=message),
        )

    def _patch_get(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.get_contributions",
            side_effect=lambda project, commit_hash=None: get_contributions(project, commit_hash=commit_hash),
        )

    def _patch_list(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.list_project_commits",
            side_effect=lambda project: list_project_commits(project),
        )


class TestContributionsGetHandler(ContributionsHandlerTestCase):
    def _seed_project(self, name="handler-project"):
        pc = _make_project(name)
        store_contributions(name, pc)
        return pc

    def test_missing_project_param_returns_400(self):
        resp = self.fetch("/contributions/get")
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("error", body)

    def test_unknown_project_returns_404(self):
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=no-such-project")
            self.assertEqual(resp.code, 404)

    def test_get_existing_project_returns_200(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=handler-project")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["project_name"], "handler-project")

    def test_get_returns_json_content_type(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=handler-project")
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_get_yaml_format(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=handler-project&format=yaml")
            self.assertEqual(resp.code, 200)
            self.assertIn("text/plain", resp.headers.get("Content-Type", ""))
            self.assertIn("handler-project", resp.body.decode())

    def test_get_specific_commit(self):
        self._seed_project()
        pc2 = ProjectContributions(project_name="handler-project", doi="10.0/v2")
        store_contributions("handler-project", pc2)
        commits = list_project_commits("handler-project")
        old_hash = commits[-1]["commit"]
        with self._patch_get():
            resp = self.fetch(f"/contributions/get?project=handler-project&commit={old_hash}")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertIsNone(body["doi"])

    def test_get_history(self):
        self._seed_project()
        store_contributions(
            "handler-project",
            _make_project("handler-project"),
        )
        with self._patch_list():
            resp = self.fetch("/contributions/get?project=handler-project&history=true")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertIsInstance(body, list)
            self.assertGreater(len(body), 0)

    def test_get_history_missing_project_returns_404(self):
        with self._patch_list():
            resp = self.fetch("/contributions/get?project=no-such&history=true")
            self.assertEqual(resp.code, 404)

    def test_options_returns_204(self):
        resp = self.fetch("/contributions/get", method="OPTIONS")
        self.assertEqual(resp.code, 204)

    def test_cors_headers_present(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=handler-project")
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")


class TestContributionsPostHandler(ContributionsHandlerTestCase):
    def test_post_missing_project_param_returns_400(self):
        body = _make_project_json()
        resp = self.fetch(
            "/contributions/post",
            method="POST",
            body=body,
            headers={"Content-Type": "application/json"},
        )
        self.assertEqual(resp.code, 400)

    def test_post_missing_body_returns_400(self):
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body="",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 400)

    def test_post_invalid_body_returns_400(self):
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body="not valid json or yaml",
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 400)

    def test_post_valid_json_returns_200(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)
            data = json.loads(resp.body)
            self.assertIn("commit", data)
            self.assertEqual(data["project"], "handler-project")

    def test_post_valid_yaml_returns_200(self):
        pc = _make_project("handler-project")
        y = to_yaml(pc)
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=y,
                headers={"Content-Type": "text/plain"},
            )
            self.assertEqual(resp.code, 200)

    def test_post_commit_hash_is_32_chars(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            data = json.loads(resp.body)
            self.assertEqual(len(data["commit"]), 32)

    def test_post_options_returns_204(self):
        resp = self.fetch("/contributions/post", method="OPTIONS")
        self.assertEqual(resp.code, 204)

    def test_post_cors_headers_present(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    def test_post_with_custom_message(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = self.fetch(
                "/contributions/post?project=handler-project&message=my-commit",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)


class TestPasswordStore(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._patch = _s3_patch(self._fake)
        self._patch.start()
        store_contributions("pw-project", _make_project("pw-project"))

    def tearDown(self):
        self._patch.stop()

    def test_no_password_set_returns_true(self):
        self.assertTrue(verify_project_password("pw-project", "anything"))

    def test_no_password_set_empty_string_returns_true(self):
        self.assertTrue(verify_project_password("pw-project", ""))

    def test_correct_password_returns_true(self):
        set_project_password("pw-project", "abc123hash")
        self.assertTrue(verify_project_password("pw-project", "abc123hash"))

    def test_wrong_password_returns_false(self):
        set_project_password("pw-project", "abc123hash")
        self.assertFalse(verify_project_password("pw-project", "wronghash"))

    def test_empty_password_wrong_returns_false(self):
        set_project_password("pw-project", "abc123hash")
        self.assertFalse(verify_project_password("pw-project", ""))

    def test_replace_password_old_fails(self):
        set_project_password("pw-project", "first")
        set_project_password("pw-project", "second")
        self.assertFalse(verify_project_password("pw-project", "first"))
        self.assertTrue(verify_project_password("pw-project", "second"))

    def test_password_on_unknown_project_returns_true(self):
        self.assertTrue(verify_project_password("no-such-project", "pw"))


class TestGetContributionsByDoi(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._patch = _s3_patch(self._fake)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_find_project_by_doi(self):
        pc = ProjectContributions(project_name="doi-project", doi="10.1234/test")
        store_contributions("doi-project", pc)
        result = get_contributions_by_doi("10.1234/test")
        self.assertEqual(result.project_name, "doi-project")
        self.assertEqual(result.doi, "10.1234/test")

    def test_missing_doi_raises(self):
        pc = ProjectContributions(project_name="no-doi-project")
        store_contributions("no-doi-project", pc)
        with self.assertRaises(FileNotFoundError):
            get_contributions_by_doi("10.9999/missing")

    def test_returns_latest_version_for_doi(self):
        pc1 = ProjectContributions(project_name="doi-project", doi="10.1/v", assets=["v1"])
        pc2 = ProjectContributions(project_name="doi-project", doi="10.1/v", assets=["v2"])
        store_contributions("doi-project", pc1)
        store_contributions("doi-project", pc2)
        result = get_contributions_by_doi("10.1/v")
        self.assertEqual(result.assets, ["v2"])

    def test_multiple_projects_correct_one_returned(self):
        pc_a = ProjectContributions(project_name="proj-a", doi="10.0/a")
        pc_b = ProjectContributions(project_name="proj-b", doi="10.0/b")
        store_contributions("proj-a", pc_a)
        store_contributions("proj-b", pc_b)
        result = get_contributions_by_doi("10.0/b")
        self.assertEqual(result.project_name, "proj-b")


class TestGetHandlerWithPassword(ContributionsHandlerTestCase):
    def _patch_doi(self, contributions):
        return patch(
            "aind_metadata_viz.contributions.handlers.get_contributions_by_doi",
            return_value=contributions,
        )

    def _seed_project(self, name="pw-handler-project"):
        pc = _make_project(name)
        store_contributions(name, pc)
        return pc

    def test_get_always_public_no_password(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=pw-handler-project")
            self.assertEqual(resp.code, 200)

    def test_get_always_public_with_password_param(self):
        self._seed_project()
        with self._patch_get():
            resp = self.fetch("/contributions/get?project=pw-handler-project&password=anything")
            self.assertEqual(resp.code, 200)

    def test_doi_lookup_returns_200(self):
        pc = _make_project("doi-handler-project")
        with self._patch_doi(pc):
            resp = self.fetch("/contributions/get?doi=10.1234/test")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["project_name"], "doi-handler-project")

    def test_doi_not_found_returns_404(self):
        from unittest.mock import patch as _patch
        with _patch(
            "aind_metadata_viz.contributions.handlers.get_contributions_by_doi",
            side_effect=FileNotFoundError("not found"),
        ), _patch(
            "aind_metadata_viz.contributions.handlers.get_contributions",
            side_effect=FileNotFoundError("not found"),
        ):
            resp = self.fetch("/contributions/get?doi=10.9999/nope")
            self.assertEqual(resp.code, 404)

    def test_missing_both_project_and_doi_returns_400(self):
        resp = self.fetch("/contributions/get")
        self.assertEqual(resp.code, 400)
        body = json.loads(resp.body)
        self.assertIn("error", body)


class TestPostHandlerWithPassword(ContributionsHandlerTestCase):
    def _patch_verify(self, return_value):
        return patch(
            "aind_metadata_viz.contributions.handlers.verify_project_password",
            return_value=return_value,
        )

    def test_post_no_password_set_returns_200(self):
        body = _make_project_json("handler-project")
        with self._patch_store(), self._patch_verify(True):
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)

    def test_post_correct_password_returns_200(self):
        body = _make_project_json("handler-project")
        with self._patch_store(), self._patch_verify(True):
            resp = self.fetch(
                "/contributions/post?project=handler-project&password=correct",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)

    def test_post_wrong_password_returns_401(self):
        body = _make_project_json("handler-project")
        with self._patch_verify(False):
            resp = self.fetch(
                "/contributions/post?project=handler-project&password=wrong",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 401)
            data = json.loads(resp.body)
            self.assertIn("error", data)

    def test_post_missing_password_returns_401_when_required(self):
        body = _make_project_json("handler-project")
        with self._patch_verify(False):
            resp = self.fetch(
                "/contributions/post?project=handler-project",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 401)




class TestTokenStore(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._patch = _s3_patch(self._fake)
        self._patch.start()
        self.pc = ProjectContributions(
            project_name="tok-project",
            doi="10.99/tok",
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]),
            ],
        )
        store_contributions("tok-project", self.pc)

    def tearDown(self):
        self._patch.stop()

    def test_create_token_returns_hex_string(self):
        token = create_token("tok-project", "add_author")
        self.assertIsInstance(token, str)
        self.assertEqual(len(token), 32)

    def test_create_add_author_token(self):
        token = create_token("tok-project", "add_author")
        record = lookup_token("tok-project", token)
        self.assertIsNotNone(record)
        self.assertEqual(record["token_type"], "add_author")
        self.assertIsNone(record["author_name"])

    def test_create_edit_author_token(self):
        token = create_token("tok-project", "edit_author", author_name="Alice")
        record = lookup_token("tok-project", token)
        self.assertIsNotNone(record)
        self.assertEqual(record["token_type"], "edit_author")
        self.assertEqual(record["author_name"], "Alice")

    def test_invalid_token_type_raises(self):
        with self.assertRaises(ValueError):
            create_token("tok-project", "bad_type")

    def test_edit_author_without_name_raises(self):
        with self.assertRaises(ValueError):
            create_token("tok-project", "edit_author")

    def test_create_multi_author_token(self):
        token = create_token("tok-project", "multi_author")
        record = lookup_token("tok-project", token)
        self.assertIsNotNone(record)
        self.assertEqual(record["token_type"], "multi_author")
        self.assertIsNone(record["author_name"])

    def test_multi_author_expires_capped_at_7_days(self):
        from datetime import datetime, timezone
        token = create_token("tok-project", "multi_author", expires_days=9999)
        record = lookup_token("tok-project", token)
        expires = datetime.fromisoformat(record["expires_at"])
        delta = expires - datetime.now(timezone.utc)
        self.assertLessEqual(delta.days, 7)

    def test_multi_author_expires_custom_within_7_days(self):
        from datetime import datetime, timezone
        token = create_token("tok-project", "multi_author", expires_days=3)
        record = lookup_token("tok-project", token)
        expires = datetime.fromisoformat(record["expires_at"])
        delta = expires - datetime.now(timezone.utc)
        self.assertLessEqual(delta.days, 3)
        self.assertGreater(delta.days, 1)

    def test_lookup_unknown_token_returns_none(self):
        self.assertIsNone(lookup_token("tok-project", "notavalidtoken"))

    def test_lookup_returns_none_for_missing_project(self):
        self.assertIsNone(lookup_token("no-such-project", "abc"))

    def test_expires_days_capped_at_365(self):
        from datetime import datetime, timezone
        token = create_token("tok-project", "add_author", expires_days=9999)
        record = lookup_token("tok-project", token)
        expires = datetime.fromisoformat(record["expires_at"])
        delta = expires - datetime.now(timezone.utc)
        self.assertLessEqual(delta.days, 365)

    def test_expires_days_custom(self):
        from datetime import datetime, timezone
        token = create_token("tok-project", "add_author", expires_days=30)
        record = lookup_token("tok-project", token)
        expires = datetime.fromisoformat(record["expires_at"])
        delta = expires - datetime.now(timezone.utc)
        self.assertLessEqual(delta.days, 30)
        self.assertGreater(delta.days, 27)

    def test_consume_token_marks_used(self):
        token = create_token("tok-project", "add_author")
        consume_token("tok-project", token)
        self.assertIsNone(lookup_token("tok-project", token))

    def test_consume_nonexistent_token_is_noop(self):
        consume_token("tok-project", "doesnotexist")

    def test_multiple_tokens_stored_independently(self):
        t1 = create_token("tok-project", "add_author")
        t2 = create_token("tok-project", "edit_author", author_name="Bob")
        consume_token("tok-project", t1)
        self.assertIsNone(lookup_token("tok-project", t1))
        self.assertIsNotNone(lookup_token("tok-project", t2))

    def test_expired_token_returns_none(self):
        from datetime import datetime, timezone, timedelta
        token = create_token("tok-project", "add_author")
        token_key = "contributions-app/_tokens/tok-project.json"
        import json as _json
        raw = self._fake._store[token_key]
        data = _json.loads(raw)
        for t in data["tokens"]:
            if t["token_id"] == token:
                t["expires_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        self._fake._store[token_key] = _json.dumps(data).encode()
        self.assertIsNone(lookup_token("tok-project", token))


class TestValidateTokenScope(unittest.TestCase):
    """Tests for the _validate_token_scope helper in handlers."""

    def setUp(self):
        self.existing = ProjectContributions(
            project_name="scope-project",
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]),
            ],
        )
        self._patch_get = patch(
            "aind_metadata_viz.contributions.handlers.get_contributions",
            return_value=self.existing,
        )
        self._patch_get.start()

    def tearDown(self):
        self._patch_get.stop()

    def _scope(self, token_type, author_name, new_contributions):
        from aind_metadata_viz.contributions.handlers import _validate_token_scope
        return _validate_token_scope("scope-project", token_type, author_name, new_contributions)

    def _clone_with_extra(self, extra_name):
        contribs = list(self.existing.contributors) + [
            AuthorContribution(author=_make_author(extra_name), credit_levels=[_make_role()])
        ]
        return ProjectContributions(project_name="scope-project", contributors=contribs)

    def test_add_author_valid_one_new(self):
        new = self._clone_with_extra("Carol")
        ok, err = self._scope("add_author", None, new)
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_add_author_zero_new_fails(self):
        ok, err = self._scope("add_author", None, self.existing)
        self.assertFalse(ok)
        self.assertIn("exactly one", err)

    def test_add_author_two_new_fails(self):
        new = self._clone_with_extra("Carol")
        new2 = ProjectContributions(
            project_name="scope-project",
            contributors=list(new.contributors) + [
                AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()])
            ],
        )
        ok, err = self._scope("add_author", None, new2)
        self.assertFalse(ok)

    def test_add_author_cannot_remove_existing(self):
        new = ProjectContributions(
            project_name="scope-project",
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                AuthorContribution(author=_make_author("Carol"), credit_levels=[_make_role()]),
            ],
        )
        ok, err = self._scope("add_author", None, new)
        self.assertFalse(ok)
        self.assertIn("cannot remove", err)

    def test_add_author_cannot_modify_existing(self):
        modified_alice = AuthorContribution(
            author=_make_author("Alice", affiliation=["New Org"]),
            credit_levels=[_make_role()],
        )
        new = ProjectContributions(
            project_name="scope-project",
            contributors=[
                modified_alice,
                AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]),
                AuthorContribution(author=_make_author("Carol"), credit_levels=[_make_role()]),
            ],
        )
        ok, err = self._scope("add_author", None, new)
        self.assertFalse(ok)
        self.assertIn("cannot modify", err)

    def test_edit_author_valid_change(self):
        modified_alice = AuthorContribution(
            author=_make_author("Alice", affiliation=["New Org"]),
            credit_levels=[_make_role()],
        )
        new = ProjectContributions(
            project_name="scope-project",
            contributors=[
                modified_alice,
                AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]),
            ],
        )
        ok, err = self._scope("edit_author", "Alice", new)
        self.assertTrue(ok)
        self.assertIsNone(err)

    def test_edit_author_cannot_add_author(self):
        new = self._clone_with_extra("Carol")
        ok, err = self._scope("edit_author", "Alice", new)
        self.assertFalse(ok)
        self.assertIn("cannot add or remove", err)

    def test_edit_author_cannot_remove_author(self):
        new = ProjectContributions(
            project_name="scope-project",
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            ],
        )
        ok, err = self._scope("edit_author", "Alice", new)
        self.assertFalse(ok)
        self.assertIn("cannot add or remove", err)

    def test_edit_author_cannot_modify_other_author(self):
        modified_bob = AuthorContribution(
            author=_make_author("Bob", affiliation=["Different Org"]),
            credit_levels=[_make_role()],
        )
        new = ProjectContributions(
            project_name="scope-project",
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                modified_bob,
            ],
        )
        ok, err = self._scope("edit_author", "Alice", new)
        self.assertFalse(ok)
        self.assertIn("can only modify", err)

    def test_edit_author_not_found_fails(self):
        ok, err = self._scope("edit_author", "NoOne", self.existing)
        self.assertFalse(ok)
        self.assertIn("not found", err)


class TestTokenHandler(ContributionsHandlerTestCase):
    """Tests for GET /contributions/token."""

    def _patch_contributions_by_doi(self, pc=None, side_effect=None):
        if side_effect:
            return patch(
                "aind_metadata_viz.contributions.handlers.get_contributions_by_doi",
                side_effect=side_effect,
            )
        return patch(
            "aind_metadata_viz.contributions.handlers.get_contributions_by_doi",
            return_value=pc or _make_project("tok-project"),
        )

    def _patch_create_token(self, return_value="aabbccdd" * 4):
        return patch(
            "aind_metadata_viz.contributions.handlers.create_token",
            return_value=return_value,
        )

    def _patch_verify(self, return_value=True):
        return patch(
            "aind_metadata_viz.contributions.handlers.verify_project_password",
            return_value=return_value,
        )

    def test_missing_doi_returns_400(self):
        resp = self.fetch("/contributions/token?type=add_author")
        self.assertEqual(resp.code, 400)
        self.assertIn("doi", json.loads(resp.body)["error"])

    def test_invalid_type_returns_400(self):
        resp = self.fetch("/contributions/token?doi=10.1/x&type=bad_type")
        self.assertEqual(resp.code, 400)

    def test_multi_author_token_created(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token("ccddee11" * 4):
            resp = self.fetch("/contributions/token?doi=10.1/x&type=multi_author")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["type"], "multi_author")
            self.assertEqual(body["token"], "ccddee11" * 4)

    def test_multi_author_expires_days_capped_at_7(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token():
            resp = self.fetch("/contributions/token?doi=10.1/x&type=multi_author&days=9999")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["expires_days"], 7)

    def test_multi_author_custom_days_within_cap(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token():
            resp = self.fetch("/contributions/token?doi=10.1/x&type=multi_author&days=3")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["expires_days"], 3)

    def test_edit_author_without_author_param_returns_400(self):
        resp = self.fetch("/contributions/token?doi=10.1/x&type=edit_author")
        self.assertEqual(resp.code, 400)
        self.assertIn("author", json.loads(resp.body)["error"])

    def test_doi_not_found_returns_404(self):
        with self._patch_contributions_by_doi(side_effect=FileNotFoundError("nope")), \
                patch(
                    "aind_metadata_viz.contributions.handlers.get_contributions",
                    side_effect=FileNotFoundError("nope"),
                ):
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author")
            self.assertEqual(resp.code, 404)

    def test_wrong_password_returns_401(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(False):
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author&password=bad")
            self.assertEqual(resp.code, 401)

    def test_add_author_token_created(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token("aabbccdd" * 4):
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["type"], "add_author")
            self.assertEqual(body["token"], "aabbccdd" * 4)

    def test_edit_author_token_created(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token("11223344" * 4):
            resp = self.fetch(
                "/contributions/token?doi=10.1/x&type=edit_author&author=Jane+Smith"
            )
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["type"], "edit_author")

    def test_expires_days_capped_at_365(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token():
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author&days=9999")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["expires_days"], 365)

    def test_custom_days_reflected(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token():
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author&days=30")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["expires_days"], 30)

    def test_non_integer_days_returns_400(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True):
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author&days=abc")
            self.assertEqual(resp.code, 400)

    def test_options_returns_204(self):
        resp = self.fetch("/contributions/token", method="OPTIONS")
        self.assertEqual(resp.code, 204)

    def test_cors_headers_present(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(pc), self._patch_verify(True), \
                self._patch_create_token():
            resp = self.fetch("/contributions/token?doi=10.1/x&type=add_author")
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    def test_project_name_lookup_creates_token(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(side_effect=FileNotFoundError("no doi")), \
                patch(
                    "aind_metadata_viz.contributions.handlers.get_contributions",
                    return_value=pc,
                ), \
                self._patch_verify(True), \
                self._patch_create_token("aabbccdd" * 4):
            resp = self.fetch("/contributions/token?doi=tok-project&type=add_author")
            self.assertEqual(resp.code, 200)
            body = json.loads(resp.body)
            self.assertEqual(body["type"], "add_author")
            self.assertEqual(body["token"], "aabbccdd" * 4)

    def test_project_name_not_found_returns_404(self):
        with self._patch_contributions_by_doi(side_effect=FileNotFoundError("no doi")), \
                patch(
                    "aind_metadata_viz.contributions.handlers.get_contributions",
                    side_effect=FileNotFoundError("no project"),
                ):
            resp = self.fetch("/contributions/token?doi=missing&type=add_author")
            self.assertEqual(resp.code, 404)

    def test_project_name_wrong_password_returns_401(self):
        pc = _make_project("tok-project")
        with self._patch_contributions_by_doi(side_effect=FileNotFoundError("no doi")), \
                patch(
                    "aind_metadata_viz.contributions.handlers.get_contributions",
                    return_value=pc,
                ), \
                self._patch_verify(False):
            resp = self.fetch("/contributions/token?doi=tok-project&type=add_author&password=bad")
            self.assertEqual(resp.code, 401)


class TestPostHandlerWithToken(ContributionsHandlerTestCase):
    """Tests for token-based auth in POST /contributions/post."""

    def _make_project_with_two_authors(self, name="tok-post-project"):
        return ProjectContributions(
            project_name=name,
            contributors=[
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]),
            ],
        )

    def _patch_lookup_token(self, record):
        return patch(
            "aind_metadata_viz.contributions.handlers.lookup_token",
            return_value=record,
        )

    def _patch_validate_scope(self, result):
        ok, err = result
        return patch(
            "aind_metadata_viz.contributions.handlers._validate_token_scope",
            return_value=(ok, err),
        )

    def _patch_consume(self):
        return patch("aind_metadata_viz.contributions.handlers.consume_token")

    def test_valid_add_author_token_returns_200(self):
        record = {"token_id": "tok1", "token_type": "add_author", "author_name": None}
        body = to_json(self._make_project_with_two_authors())
        with self._patch_store(), self._patch_lookup_token(record), \
                self._patch_validate_scope((True, None)), self._patch_consume():
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=tok1",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)

    def test_add_author_token_consumed_after_store(self):
        record = {"token_id": "tok1", "token_type": "add_author", "author_name": None}
        body = to_json(self._make_project_with_two_authors())
        mock_consume = MagicMock()
        with self._patch_store(), self._patch_lookup_token(record), \
                self._patch_validate_scope((True, None)), \
                patch("aind_metadata_viz.contributions.handlers.consume_token", mock_consume):
            self.fetch(
                "/contributions/post?project=tok-post-project&password=tok1",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            mock_consume.assert_called_once_with("tok-post-project", "tok1")

    def test_valid_edit_author_token_not_consumed(self):
        record = {"token_id": "tok2", "token_type": "edit_author", "author_name": "Alice"}
        body = to_json(self._make_project_with_two_authors())
        mock_consume = MagicMock()
        with self._patch_store(), self._patch_lookup_token(record), \
                self._patch_validate_scope((True, None)), \
                patch("aind_metadata_viz.contributions.handlers.consume_token", mock_consume):
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=tok2",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)
            mock_consume.assert_not_called()

    def test_valid_multi_author_token_not_consumed(self):
        record = {"token_id": "tok4", "token_type": "multi_author", "author_name": None}
        body = to_json(self._make_project_with_two_authors())
        mock_consume = MagicMock()
        with self._patch_store(), self._patch_lookup_token(record), \
                self._patch_validate_scope((True, None)), \
                patch("aind_metadata_viz.contributions.handlers.consume_token", mock_consume):
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=tok4",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)
            mock_consume.assert_not_called()

    def test_out_of_scope_token_returns_403(self):
        record = {"token_id": "tok1", "token_type": "add_author", "author_name": None}
        body = to_json(self._make_project_with_two_authors())
        with self._patch_lookup_token(record), \
                self._patch_validate_scope((False, "add_author token allows adding exactly one new author")):
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=tok1",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 403)
            self.assertIn("error", json.loads(resp.body))

    def test_invalid_token_falls_back_to_password_check(self):
        body = to_json(self._make_project_with_two_authors())
        with self._patch_lookup_token(None), \
                patch("aind_metadata_viz.contributions.handlers.verify_project_password", return_value=False):
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=notavalidtoken",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 401)

    def test_valid_token_bypasses_admin_password(self):
        record = {"token_id": "tok3", "token_type": "edit_author", "author_name": "Alice"}
        body = to_json(self._make_project_with_two_authors())
        mock_verify = MagicMock(return_value=False)
        with self._patch_store(), self._patch_lookup_token(record), \
                self._patch_validate_scope((True, None)), self._patch_consume(), \
                patch("aind_metadata_viz.contributions.handlers.verify_project_password", mock_verify):
            resp = self.fetch(
                "/contributions/post?project=tok-post-project&password=tok3",
                method="POST",
                body=body,
                headers={"Content-Type": "application/json"},
            )
            self.assertEqual(resp.code, 200)
            mock_verify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
