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
    AuthorLevel,
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
from aind_metadata_viz.contributions.handlers import (
    contributions_router,
    _merge_author_contribution,
)
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
        self.assertEqual(pc.doi, ["10.1234/test"])

    def test_doi_is_a_list(self):
        """A paper may be published in several venues, so doi is a list."""
        pc = ProjectContributions(
            project_name="p", doi=["10.1234/preprint", "10.5678/journal"]
        )
        self.assertEqual(pc.doi, ["10.1234/preprint", "10.5678/journal"])

    def test_doi_legacy_forms_coerced(self):
        """Documents written before doi became a list still load."""
        self.assertEqual(ProjectContributions(project_name="p").doi, [])
        self.assertEqual(ProjectContributions(project_name="p", doi=None).doi, [])
        self.assertEqual(ProjectContributions(project_name="p", doi="").doi, [])
        self.assertEqual(
            ProjectContributions(project_name="p", doi="10.1/x").doi, ["10.1/x"]
        )

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

    def test_to_yaml_orders_byline_by_publication_order(self):
        pc = ProjectContributions(
            project_name="p",
            doi=["10.1/a", "10.2/b"],
            contributors=[
                AuthorContribution(author=_make_author("Zoe"), publication_order=2),
                AuthorContribution(author=_make_author("Amy"), publication_order=1),
                AuthorContribution(author=_make_author("Unset")),
            ],
        )
        restored = from_yaml(to_yaml(pc))
        self.assertEqual(
            [c.author.name for c in restored.contributors], ["Amy", "Zoe", "Unset"]
        )
        self.assertEqual(
            [c.publication_order for c in restored.contributors], [1, 2, None]
        )
        self.assertEqual(restored.doi, ["10.1/a", "10.2/b"])

    def test_from_yaml_role_preserved(self):
        y = to_yaml(self.pc)
        restored = from_yaml(y)
        self.assertEqual(restored.contributors[0].credit_levels[0].role, CreditRole.SOFTWARE)

    def test_yaml_roundtrip_preserves_admin(self):
        self.pc.contributors[0].is_admin = True
        restored = from_yaml(to_yaml(self.pc))
        self.assertTrue(restored.contributors[0].is_admin)

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
        self.assertEqual(old.doi, ["10.1/v1"])

    def test_get_contributions_head_is_latest(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1)
        store_contributions("store-test", pc2)
        latest = get_contributions("store-test")
        self.assertEqual(latest.doi, ["10.1/v2"])

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
    pc.contributors[0].author.registry_identifier = _ADMIN["orcid"]
    pc.contributors[0].is_admin = True
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
        resp = client.get("/contributions/project")
        self.assertEqual(resp.status_code, 400)
        body = resp.json()
        self.assertIn("error", body)

    def test_unknown_project_returns_404(self):
        with self._patch_get():
            resp = client.get("/contributions/project?project=no-such-project")
            self.assertEqual(resp.status_code, 404)

    def test_get_existing_project_returns_200(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/project?project=handler-project")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["project_name"], "handler-project")

    def test_get_returns_json_content_type(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/project?project=handler-project")
            self.assertIn("application/json", resp.headers.get("Content-Type", ""))

    def test_get_yaml_format(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get("/contributions/project?project=handler-project&format=yaml")
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
            resp = client.get(f"/contributions/project?project=handler-project&commit={old_hash}")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["doi"], [])

    def test_get_history(self):
        self._seed_project()
        store_contributions(
            "handler-project",
            _make_project("handler-project"),
        )
        with self._patch_list():
            resp = client.get("/contributions/project?project=handler-project&history=true")
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertIsInstance(body, list)
            self.assertGreater(len(body), 0)

    def test_get_history_missing_project_returns_404(self):
        with self._patch_list():
            resp = client.get("/contributions/project?project=no-such&history=true")
            self.assertEqual(resp.status_code, 404)

    def test_options_returns_204(self):
        resp = client.options("/contributions/project", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"})
        self.assertIn(resp.status_code, (200, 204))

    def test_cors_headers_present(self):
        self._seed_project()
        with self._patch_get():
            resp = client.get(
                "/contributions/project?project=handler-project",
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
        resp = client.post("/contributions/project", content=body, headers={"Content-Type": "application/json"})
        self.assertEqual(resp.status_code, 400)

    def test_post_missing_body_returns_400(self):
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content="", headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 400)

    def test_post_invalid_body_returns_400(self):
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content="not valid json or yaml", headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 400)

    def test_post_valid_json_returns_200(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content=body, headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("commit", data)
            self.assertEqual(data["project"], "handler-project")

    def test_post_without_admin_returns_400(self):
        body = to_json(_make_project("handler-project"))
        with self._patch_store():
            resp = client.post(
                "/contributions/project?project=handler-project",
                content=body,
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("admin", resp.json()["error"].lower())

    def test_post_valid_yaml_returns_200(self):
        pc = _make_project("handler-project")
        pc.contributors[0].author.registry_identifier = _ADMIN["orcid"]
        pc.contributors[0].is_admin = True
        y = to_yaml(pc)
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content=y, headers={"Content-Type": "application/json"})
            self.assertEqual(resp.status_code, 200)

    def test_post_commit_hash_is_32_chars(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content=body, headers={"Content-Type": "application/json"})
            data = resp.json()
            self.assertEqual(len(data["commit"]), 32)

    def test_post_options_returns_204(self):
        resp = client.options("/contributions/project", headers={"Origin": "http://example.com", "Access-Control-Request-Method": "GET"})
        self.assertIn(resp.status_code, (200, 204))

    def test_post_cors_headers_present(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project", content=body, headers={"Content-Type": "application/json", "Origin": "http://example.com"})
            self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")

    def test_post_with_custom_message(self):
        body = _make_project_json("handler-project")
        with self._patch_store():
            resp = client.post("/contributions/project?project=handler-project&message=my-commit", content=body, headers={"Content-Type": "application/json"})
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
        self.assertEqual(result.doi, ["10.1234/test"])

    def test_find_project_by_any_of_several_dois(self):
        pc = ProjectContributions(
            project_name="multi-doi", doi=["10.1/preprint", "10.2/journal"]
        )
        store_contributions("multi-doi", pc)
        for doi in ("10.1/preprint", "10.2/journal"):
            self.assertEqual(
                get_contributions_by_doi(doi).project_name, "multi-doi"
            )

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
    """GET /contributions/project is public — no password or auth required."""

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
            resp = client.get("/contributions/project?project=pub-handler-project")
            self.assertEqual(resp.status_code, 200)

    def test_doi_lookup_returns_200(self):
        pc = _make_project("doi-handler-project")
        with self._patch_doi(pc):
            resp = client.get("/contributions/project?doi=10.1234/test")
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
            resp = client.get("/contributions/project?doi=10.9999/nope")
            self.assertEqual(resp.status_code, 404)

    def test_missing_both_project_and_doi_returns_400(self):
        resp = client.get("/contributions/project")
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
    """The full-project POST is reserved for global/project admins."""

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
            f"/contributions/project?project={name}",
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
        self.assertEqual(resp.status_code, 403)
        self.assertIn("full project", resp.json()["error"].lower())

    def test_non_admin_cannot_remove_other_author(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Carol", orcid=_MEMBER["orcid"]),
                               credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_MEMBER):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 403)

    def test_non_admin_cannot_use_full_post_to_grant_admin(self):
        self._seed_project()
        # Carol adds herself and tries to flag her own new row as admin. The
        # save succeeds but the admin grant is stripped by the server merge.
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
            AuthorContribution(author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                               credit_levels=[_make_role()], is_admin=True),
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 200)

    def test_admin_cannot_remove_last_project_admin(self):
        self._seed_project()
        body = self._payload([
            AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
        ])
        with _patch_current_user(_PROJECT_ADMIN):
            resp = self._post(body)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("admin", resp.json()["error"].lower())
        self.assertTrue(get_contributions("sess-project").contributors[0].is_admin)

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


class TestAuthorPostAuth(ContributionsHandlerTestCase):
    """POST /contributions/author accepts one author row only."""

    def _seed_project(self, name="author-project", edit_locked=False):
        pc = ProjectContributions(
            project_name=name,
            doi=["10.1/original"],
            show_levels=False,
            edit_locked=edit_locked,
            contributors=[
                AuthorContribution(
                    author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
                    credit_levels=[_make_role()],
                    is_admin=True,
                ),
                AuthorContribution(
                    author=_make_author("Alice", orcid="0000-0001"),
                    credit_levels=[_make_role(CreditRole.INVESTIGATION, ContributionLevel.SUPPORTING)],
                ),
            ],
        )
        store_contributions(name, pc)
        return pc

    def _post(self, author, name="author-project"):
        return client.post(
            f"/contributions/author?project={name}",
            content=author.model_dump_json(),
            headers={"Content-Type": "application/json"},
        )

    def test_add_upload_sends_one_author_and_server_keeps_project_state(self):
        """The add contract must not depend on a client project copy.

        This is the regression guard for backend validation changes: the
        request contains only Carol's new row, while the stored admin, DOI,
        settings, and existing contributors are recovered from storage.
        """
        self._seed_project()
        incoming = AuthorContribution(
            author=_make_author("Carol", orcid=_MEMBER["orcid"], affiliation=["Elsewhere"]),
            credit_levels=[_make_role(CreditRole.SOFTWARE, ContributionLevel.EQUAL)],
            is_admin=True,
        )
        with _patch_current_user(_MEMBER):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 200)

        stored = get_contributions("author-project")
        self.assertEqual(stored.doi, ["10.1/original"])
        self.assertFalse(stored.show_levels)
        self.assertTrue(any(c.author.name == "Bob" and c.is_admin for c in stored.contributors))
        self.assertEqual(
            next(c for c in stored.contributors if c.author.name == "Alice").credit_levels[0].role,
            CreditRole.INVESTIGATION,
        )
        carol = next(c for c in stored.contributors if c.author.name == "Carol")
        self.assertFalse(carol.is_admin)
        self.assertEqual(carol.author.affiliation, ["Elsewhere"])

    def test_project_admin_can_use_author_endpoint_without_sending_admin_flag(self):
        """Author updates preserve admin membership in storage."""
        self._seed_project()
        incoming = AuthorContribution(
            author=_make_author("Bob", orcid=_PROJECT_ADMIN["orcid"]),
            credit_levels=[_make_role(CreditRole.SUPERVISION, ContributionLevel.LEAD)],
        )
        with _patch_current_user(_PROJECT_ADMIN):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 200)
        bob = next(c for c in get_contributions("author-project").contributors if c.author.name == "Bob")
        self.assertTrue(bob.is_admin)

    def test_non_admin_can_update_only_their_existing_author_row(self):
        self._seed_project()
        incoming = AuthorContribution(
            author=_make_author("Alice", orcid="0000-0001", affiliation=["Elsewhere"]),
            credit_levels=[_make_role(CreditRole.VALIDATION, ContributionLevel.EQUAL)],
        )
        alice_user = {"orcid": "0000-0001", "name": "Alice", "is_admin": False}
        with _patch_current_user(alice_user):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 200)
        stored = get_contributions("author-project")
        alice = next(c for c in stored.contributors if c.author.name == "Alice")
        self.assertEqual(alice.author.affiliation, ["Elsewhere"])
        self.assertTrue(next(c for c in stored.contributors if c.author.name == "Bob").is_admin)

    def test_author_endpoint_cannot_edit_another_author(self):
        self._seed_project()
        incoming = AuthorContribution(
            author=_make_author("Alice", affiliation=["Elsewhere"]),
            credit_levels=[_make_role()],
        )
        with _patch_current_user(_MEMBER):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 403)

    def test_author_endpoint_requires_existing_admin(self):
        pc = self._seed_project()
        pc.contributors[0].is_admin = False
        store_contributions("author-project", pc)
        incoming = AuthorContribution(
            author=_make_author("Carol", orcid=_MEMBER["orcid"]),
            credit_levels=[_make_role()],
        )
        with _patch_current_user(_MEMBER):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 400)
        self.assertIn("admin", resp.json()["error"].lower())

    def test_author_endpoint_rejects_full_project_payload(self):
        self._seed_project()
        with _patch_current_user(_MEMBER):
            resp = client.post(
                "/contributions/author?project=author-project",
                content=to_json(ProjectContributions(project_name="author-project")),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_author_endpoint_respects_lock(self):
        self._seed_project(edit_locked=True)
        incoming = AuthorContribution(
            author=_make_author("Carol", orcid=_MEMBER["orcid"]),
            credit_levels=[_make_role()],
        )
        with _patch_current_user(_MEMBER):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 403)
        self.assertIn("locked", resp.json()["error"].lower())


class TestAnonymousPostAuth(ContributionsHandlerTestCase):
    """POST /contributions/author by an anonymous visitor.

    Anonymous visitors may append one new author row to an existing unlocked
    project. They cannot overwrite a stored row or submit a full project.
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

    def _payload(self, author):
        return author.model_dump_json()

    def _post(self, author, name="anon-project"):
        return client.post(
            f"/contributions/author?project={name}",
            content=self._payload(author),
            headers={"Content-Type": "application/json"},
        )

    def test_anon_cannot_create_new_project(self):
        with _patch_current_user(None):
            resp = self._post(
                AuthorContribution(author=_make_author("Alice"), credit_levels=[_make_role()]),
                name="anon-brand-new",
            )
        self.assertEqual(resp.status_code, 404)

    def test_anon_can_add_single_new_row(self):
        self._seed_project()
        with _patch_current_user(None):
            resp = self._post(AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()]))
        self.assertEqual(resp.status_code, 200)

    def test_anon_edit_of_existing_row_is_ignored(self):
        self._seed_project()
        # Anonymous visitors have no identity to own an existing row.
        with _patch_current_user(None):
            resp = self._post(
                AuthorContribution(
                    author=_make_author("Alice", affiliation=["Elsewhere"]),
                    credit_levels=[_make_role()],
                )
            )
        self.assertEqual(resp.status_code, 403)

    def test_anon_add_preserves_other_rows_from_storage(self):
        # Regression for the "add one author, get 403 / clobbered rows" bug:
        # the add wizard sends only the new author. The server must keep the
        # stored copy of every existing row.
        pc = ProjectContributions(
            project_name="anon-project",
            contributors=[
                AuthorContribution(
                    author=_make_author("Bob", affiliation=["AIND", "UW"],
                                        orcid=_PROJECT_ADMIN["orcid"]),
                    credit_levels=[_make_role(CreditRole.SOFTWARE, ContributionLevel.LEAD),
                                   _make_role(CreditRole.INVESTIGATION, ContributionLevel.SUPPORTING)],
                    is_admin=True,
                ),
            ],
        )
        store_contributions("anon-project", pc)
        incoming = AuthorContribution(author=_make_author("Test"), credit_levels=[_make_role()])
        with _patch_current_user(None):
            resp = self._post(incoming)
        self.assertEqual(resp.status_code, 200)
        stored = get_contributions("anon-project")
        names = [c.author.name for c in stored.contributors]
        self.assertIn("Test", names)
        bob = next(c for c in stored.contributors if c.author.name == "Bob")
        # Bob's stored data survived the lossy client payload intact.
        self.assertEqual(bob.author.affiliation, ["AIND", "UW"])
        self.assertEqual(bob.author.registry_identifier, _PROJECT_ADMIN["orcid"])
        self.assertTrue(bob.is_admin)
        self.assertEqual(len(bob.credit_levels), 2)

    def test_anon_cannot_remove_existing_row(self):
        self._seed_project()
        with _patch_current_user(None):
            resp = self._post(AuthorContribution(author=_make_author("Bob"), credit_levels=[_make_role()]))
        self.assertEqual(resp.status_code, 403)

    def test_anon_cannot_add_multiple_rows(self):
        self._seed_project()
        with _patch_current_user(None):
            resp = client.post(
                "/contributions/author?project=anon-project",
                content=json.dumps({"contributors": []}),
                headers={"Content-Type": "application/json"},
            )
        self.assertEqual(resp.status_code, 400)

    def test_anon_blocked_on_locked_project(self):
        self._seed_project(edit_locked=True)
        with _patch_current_user(None):
            resp = self._post(AuthorContribution(author=_make_author("Dave"), credit_levels=[_make_role()]))
        self.assertEqual(resp.status_code, 403)
        self.assertIn("locked", resp.json()["error"].lower())


class TestScopedMergeProtectsAdminState(unittest.TestCase):
    """Author-scoped merges must not rewrite admin-owned state."""

    def _existing(self):
        return ProjectContributions(
            project_name="p",
            doi=["10.1/journal"],
            show_levels=False,
            allow_lead=False,
            allow_levels=False,
            show_sections=True,
            show_timeline=True,
            contributors=[
                AuthorContribution(
                    author=_make_author("Alice", orcid="0000-0001"),
                    credit_levels=[_make_role()],
                    publication_order=2,
                    author_level=AuthorLevel.FIRST,
                ),
                AuthorContribution(
                    author=_make_author("Bob", orcid="0000-0002"),
                    credit_levels=[_make_role()],
                    publication_order=1,
                    author_level=AuthorLevel.SENIOR,
                ),
            ],
        )

    def test_self_edit_keeps_publication_order_and_author_level(self):
        existing = self._existing()
        incoming = AuthorContribution(
            author=_make_author("Alice", orcid="0000-0001"),
            credit_levels=[_make_role()],
        )
        ok, err, merged = _merge_author_contribution(existing, "0000-0001", "Alice", incoming)
        self.assertTrue(ok, err)
        by_name = {c.author.name: c for c in merged.contributors}
        self.assertEqual(by_name["Alice"].publication_order, 2)
        self.assertEqual(by_name["Alice"].author_level, AuthorLevel.FIRST)
        self.assertEqual(by_name["Bob"].publication_order, 1)
        self.assertEqual(by_name["Bob"].author_level, AuthorLevel.SENIOR)

    def test_self_edit_keeps_project_settings_and_doi(self):
        existing = self._existing()
        incoming = AuthorContribution(
            author=_make_author("Alice", orcid="0000-0001"),
            credit_levels=[_make_role()],
        )
        ok, err, merged = _merge_author_contribution(existing, "0000-0001", "Alice", incoming)
        self.assertTrue(ok, err)
        self.assertFalse(merged.show_levels)
        self.assertFalse(merged.allow_lead)
        self.assertFalse(merged.allow_levels)
        self.assertTrue(merged.show_sections)
        self.assertTrue(merged.show_timeline)
        self.assertEqual(merged.doi, ["10.1/journal"])


if __name__ == "__main__":
    unittest.main()
