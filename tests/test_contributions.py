import json
import unittest
from datetime import date
from io import BytesIO
from unittest.mock import MagicMock, patch

from botocore.exceptions import ClientError


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
    get_author_image_key,
    get_contributions,
    get_contributions_by_doi,
    list_project_commits,
    store_contributions,
)
from aind_metadata_viz.contributions.handlers import contributions_router
from fastapi.testclient import TestClient
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

_app = FastAPI()
_app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
_app.include_router(contributions_router)
client = TestClient(_app)


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


def _make_author(name="Jane Smith", affiliation=None, orcid=None):
    return Author(
        name=name,
        affiliation=affiliation or ["AIND"],
        registry=Registry.ORCID,
        registry_identifier=orcid,
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

    def test_list_project_commits_newest_first(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1, message="first")
        second_id = store_contributions("store-test", pc2, message="second")
        commits = list_project_commits("store-test")
        self.assertEqual(commits[0]["commit"], second_id)

    def test_list_project_commits_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            list_project_commits("no-such-project")

    def test_store_does_not_recurse_on_fresh_repo(self):
        pc = ProjectContributions(project_name="fresh")
        commit = store_contributions("fresh", pc)
        self.assertIsInstance(commit, str)


def _make_project_json(name="handler-project"):
    pc = _make_project(name)
    return to_json(pc)


class ContributionsHandlerTestCase(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._s3_patch = _s3_patch(self._fake)
        self._s3_patch.start()

    def tearDown(self):
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
        resp = client.get("/contributions/get")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("error", body)

    def test_unknown_project_returns_404(self):
        with self._patch_get():
            resp = client.get("/contributions/get?project=no-such-project")
            self.assertEqual(resp.status_code, 404)

    def test_get_existing_project_returns_200(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/get?project=handler-project")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["project_name"], "handler-project")

    def test_get_returns_json_content_type(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/get?project=handler-project")
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_get_yaml_format(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/get?project=handler-project&format=yaml")
            self.assertEqual(resp.status_code, 200)
            self.assertIn("text/plain", resp.headers.get("Content-Type", ""))
            self.assertIn("handler-project", resp.text)

    def test_get_specific_commit(self):
        self._seed_project()
        pc2 = ProjectContributions(project_name="handler-project", doi="10.0/v2")
        store_contributions("handler-project", pc2)
        commits = list_project_commits("handler-project")
        old_hash = commits[-1]["commit"]
        with self._patch_get():
            resp = client.get(f"/contributions/get?project=handler-project&commit={old_hash}")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsNone(body["doi"])

    def test_get_history(self):
        self._seed_project()
        store_contributions(
            "handler-project",
            _make_project("handler-project"),
        )
        with self._patch_list():
            resp = client.get("/contributions/get?project=handler-project&history=true")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsInstance(body, list)
            self.assertGreater(len(body), 0)

    def test_get_history_missing_project_returns_404(self):
        with self._patch_list():
            resp = client.get("/contributions/get?project=no-such&history=true")
            self.assertEqual(resp.status_code, 404)

    def test_options_returns_204(self):
        resp = client.options("/contributions/get", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"})
        self.assertIn(resp.status_code, (200, 204))

    def test_cors_headers_present(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get(
                "/contributions/get?project=handler-project",
                headers={"Origin": "http://example.com"},
            )
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")


class TestContributionsPostHandler(ContributionsHandlerTestCase):
    def setUp(self):
        # Creating a new project requires an ORCID login, so these
        # POST-mechanics tests run as a logged-in global admin.
        super().setUp()
        self._user_patch = _patch_current_user(_ADMIN)
        self._user_patch.start()

    def tearDown(self):
        self._user_patch.stop()
        super().tearDown()

    def test_post_missing_project_param_returns_400(self):
        body = _make_project_json()
        resp = client.post("/contributions/post", content=body, headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)

    def test_post_missing_body_returns_400(self):
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content="", headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 400)

    def test_post_invalid_body_returns_400(self):
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content="not valid json or yaml", headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 400)

    def test_post_valid_json_returns_200(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("commit", data)
            self.assertEqual(data["project"], "handler-project")

    def test_post_valid_yaml_returns_200(self):
        pc = _make_project("handler-project")
        y = to_yaml(pc)
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content=y, headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)

    def test_post_commit_hash_is_32_chars(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content=body, headers={"Content-Type": "application/json"})
            data = resp.json()
            self.assertEqual(len(data["commit"]), 32)

    def test_post_options_returns_204(self):
        resp = client.options("/contributions/post", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"})
        self.assertIn(resp.status_code, (200, 204))

    def test_post_cors_headers_present(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project", content=body, headers={"Content-Type": "application/json", "Origin": "http://example.com"})
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    def test_post_with_custom_message(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/post?project=handler-project&message=my-commit", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)


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


class TestGetHandlerPublic(ContributionsHandlerTestCase):
    """GET /contributions/get is public — no password or auth required."""

    def _patch_doi(self, contributions):
        return patch(
            "aind_metadata_viz.contributions.handlers.get_contributions_by_doi",
            return_value=contributions,
        )

    def _seed_project(self, name="pub-handler-project"):
        pc = _make_project(name)
        store_contributions(name, pc)
        return pc

    def test_get_is_public(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/get?project=pub-handler-project")
            self.assertEqual(resp.status_code, 200)

    def test_doi_lookup_returns_200(self):
        pc = _make_project("doi-handler-project")
        with self._patch_doi(pc):
            resp = client.get("/contributions/get?doi=10.1234/test")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
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
            resp = client.get("/contributions/get?doi=10.9999/nope")
            self.assertEqual(resp.status_code, 404)

    def test_missing_both_project_and_doi_returns_400(self):
        resp = client.get("/contributions/get")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("error", body)


class TestGetAuthorImageKey(unittest.TestCase):
    def setUp(self):
        self._fake = _FakeS3()
        self._patch = _s3_patch(self._fake)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def _put_image(self, author_name, ext=".jpeg"):
        from aind_metadata_viz.contributions.store import _S3_PREFIX
        key = f"{_S3_PREFIX}/images/{author_name}{ext}"
        self._fake._store[key] = b"fake-image-bytes"
        return key

    def test_returns_key_when_image_exists(self):
        key = self._put_image("Jane Smith")
        result = get_author_image_key("Jane Smith")
        self.assertEqual(result, key)

    def test_returns_none_when_no_image(self):
        result = get_author_image_key("Unknown Person")
        self.assertIsNone(result)

    def test_works_with_webp_extension(self):
        key = self._put_image("Dan Birman", ext=".webp")
        result = get_author_image_key("Dan Birman")
        self.assertEqual(result, key)

    def test_works_with_png_extension(self):
        key = self._put_image("Anna L", ext=".png")
        result = get_author_image_key("Anna L")
        self.assertEqual(result, key)

    def test_prefix_match_only_returns_exact_author(self):
        self._put_image("Jane Smith Extra")
        result = get_author_image_key("Jane")
        self.assertIsNone(result)


class TestContributionsAuthorImageHandler(ContributionsHandlerTestCase):
    def _put_image(self, author_name, ext=".jpeg"):
        from aind_metadata_viz.contributions.store import _S3_PREFIX
        key = f"{_S3_PREFIX}/images/{author_name}{ext}"
        self._fake._store[key] = b"fake-image-bytes"
        return key

    def _patch_image(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.get_author_image_key",
            side_effect=get_author_image_key,
        )

    def test_missing_author_param_returns_400(self):
        resp = client.get("/contributions/author-image")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("error", body)

    def test_unknown_author_returns_404(self):
        with self._patch_image():
            resp = client.get("/contributions/author-image?author=Nobody")
            self.assertEqual(resp.status_code, 404)
            body = resp.json()
            self.assertIn("error", body)

    def test_known_author_returns_200_with_key(self):
        key = self._put_image("Jane Smith")
        with self._patch_image():
            resp = client.get("/contributions/author-image?author=Jane+Smith")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["author"], "Jane Smith")
            self.assertEqual(body["image_key"], key)

    def test_response_is_json_content_type(self):
        self._put_image("Jane Smith")
        with self._patch_image():
            resp = client.get("/contributions/author-image?author=Jane+Smith")
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_options_returns_204(self):
        resp = client.options("/contributions/author-image", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"})
        self.assertIn(resp.status_code, (200, 204))


def _patch_current_user(user):
    """Patch the session-user lookup used by the contributions handlers."""
    return patch(
        "aind_metadata_viz.contributions.handlers.get_current_user",
        return_value=user,
    )


# Global admin (ADMIN_ORCIDS). Carol is a plain logged-in user; Bob's ORCID
# matches a seeded contributor flagged is_admin (a project admin).
_ADMIN = {"orcid": "0000-9999", "name": "Admin", "is_admin": True}
_MEMBER = {"orcid": "0000-0007", "name": "Carol", "is_admin": False}
_PROJECT_ADMIN = {"orcid": "0000-0002", "name": "Bob", "is_admin": False}


class TestAccessHandler(ContributionsHandlerTestCase):
    def _seed(self, name="p"):
        pc = ProjectContributions(
            project_name=name,
            contributors=[
                AuthorContribution(
                    author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                    credit_levels=[_make_role()],
                    is_admin=True,
                ),
                AuthorContribution(
                    author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                    credit_levels=[_make_role()],
                ),
            ],
        )
        store_contributions(name, pc)

    def test_anon_cannot_edit(self):
        with _patch_current_user(None):
            resp = client.get("/contributions/access?project=p")
        data = resp.json()
        self.assertFalse(data["logged_in"])
        self.assertFalse(data["can_edit"])

    def test_global_admin_is_admin(self):
        with _patch_current_user(_ADMIN):
            resp = client.get("/contributions/access?project=p")
        data = resp.json()
        self.assertTrue(data["is_admin"])
        self.assertTrue(data["can_edit"])

    def test_contributor_flagged_admin_is_admin(self):
        self._seed()
        with _patch_current_user(_PROJECT_ADMIN):
            resp = client.get("/contributions/access?project=p")
        data = resp.json()
        self.assertTrue(data["is_admin"])
        self.assertTrue(data["can_edit"])

    def test_logged_in_non_admin_can_edit_but_not_admin(self):
        self._seed()
        # Carol is a contributor without the admin flag: she can self-edit
        # her own row (can_edit) but is not an admin.
        with _patch_current_user(_MEMBER):
            resp = client.get("/contributions/access?project=p")
        data = resp.json()
        self.assertTrue(data["logged_in"])
        self.assertTrue(data["can_edit"])
        self.assertFalse(data["is_admin"])


class TestSessionPostAuth(ContributionsHandlerTestCase):
    """POST /contributions/post authenticated by an ORCID session."""

    def _seed_project(self, name="sess-project"):
        pc = ProjectContributions(
            project_name=name,
            contributors=[
                AuthorContribution(
                    author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                    credit_levels=[_make_role()],
                    is_admin=True,
                ),
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            ],
        )
        store_contributions(name, pc)
        return pc

    def _payload(self, contributors, name="sess-project"):
        pc = ProjectContributions(project_name=name, contributors=contributors)
        return to_json(pc)

    def _post(self, body, name="sess-project"):
        return client.post(
            f"/contributions/post?project={name}",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    def test_user_can_add_own_row(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_MEMBER):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    def test_non_admin_cannot_remove_other_author(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_MEMBER):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_cannot_grant_admin(self):
        self._seed_project()
        # Carol tries to flag her own new row as admin — rejected.
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
        ])
        with _patch_current_user(_MEMBER):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_global_admin_can_edit_everything(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    def test_contributor_admin_can_edit_everything(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
        ])
        with _patch_current_user(_PROJECT_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    def test_admin_can_lock_project(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
        ])
        pc = json.loads(body); pc["edit_locked"] = True; body = json.dumps(pc)
        with _patch_current_user(_PROJECT_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(get_contributions("sess-project").edit_locked)

    def test_locked_project_blocks_non_admin(self):
        pc = self._seed_project()
        pc.edit_locked = True
        store_contributions("sess-project", pc)
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_MEMBER):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("locked", resp.json()["error"].lower())

    def test_admin_can_edit_and_unlock_locked_project(self):
        pc = self._seed_project()
        pc.edit_locked = True
        store_contributions("sess-project", pc)
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
        ])  # edit_locked defaults False -> admin unlocks
        with _patch_current_user(_PROJECT_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(get_contributions("sess-project").edit_locked)

    def test_creator_of_new_project_is_made_admin(self):
        # Posting to a project that does not exist yet: the creator's own row
        # (matched by ORCID) is forced to is_admin=True.
        body = self._payload([
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()]),
        ], name="brand-new")
        with _patch_current_user(_MEMBER):
            resp = self._post(body, name="brand-new")
        self.assertEqual(resp.status_code, 200)
        stored = get_contributions("brand-new")
        carol = next(c for c in stored.contributors if c.author.name == "Carol")
        self.assertTrue(carol.is_admin)


class TestAnonymousPostAuth(ContributionsHandlerTestCase):
    """POST /contributions/post by an anonymous (not logged-in) visitor.

    With passwords removed, an anonymous caller has no identity to own a row,
    so they may only append a single new author entry to an unlocked project
    and may not touch existing rows. A locked project rejects them outright.
    """

    def _seed_project(self, name="anon-project", edit_locked=False):
        pc = ProjectContributions(
            project_name=name,
            edit_locked=edit_locked,
            contributors=[
                AuthorContribution(
                    author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                    credit_levels=[_make_role()],
                    is_admin=True,
                ),
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            ],
        )
        store_contributions(name, pc)
        return pc

    def _payload(self, contributors, name="anon-project"):
        return to_json(ProjectContributions(project_name=name, contributors=contributors))

    def _post(self, body, name="anon-project"):
        return client.post(
            f"/contributions/post?project={name}",
            content=body,
            headers={"Content-Type": "application/json"},
        )

    def test_anon_cannot_create_new_project(self):
        body = self._payload([
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
        ], name="anon-brand-new")
        with _patch_current_user(None):
            resp = self._post(body, name="anon-brand-new")
        self.assertEqual(resp.status_code, 401)

    def test_anon_can_add_single_new_row(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(None):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    def test_anon_cannot_modify_existing_row(self):
        self._seed_project()
        # Change Alice's affiliation while leaving the author set unchanged.
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice", affiliation=["Elsewhere"]),
                               credit_levels=[_make_role()]),
        ])
        with _patch_current_user(None):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_anon_cannot_remove_existing_row(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
        ])
        with _patch_current_user(None):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_anon_cannot_add_multiple_rows(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Erin"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(None):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_anon_blocked_on_locked_project(self):
        self._seed_project(edit_locked=True)
        body = self._payload([
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
            AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(None):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("locked", resp.json()["error"].lower())


if __name__ == "__main__":
    unittest.main()
