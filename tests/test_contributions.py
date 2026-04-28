import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

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
    list_project_commits,
    store_contributions,
)
from aind_metadata_viz.contributions.handlers import CONTRIBUTION_ROUTES


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
        self._tmpdir = tempfile.TemporaryDirectory()
        self.store_dir = Path(self._tmpdir.name)
        self.pc = _make_project("store-test")

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_store_returns_commit_hash(self):
        commit = store_contributions("store-test", self.pc, store_dir=self.store_dir)
        self.assertIsInstance(commit, str)
        self.assertEqual(len(commit), 32)

    def test_store_and_retrieve(self):
        store_contributions("store-test", self.pc, store_dir=self.store_dir)
        retrieved = get_contributions("store-test", store_dir=self.store_dir)
        self.assertEqual(retrieved.project_name, "store-test")
        self.assertEqual(retrieved.contributors[0].author.name, "Jane Smith")

    def test_store_with_json_string(self):
        j = to_json(self.pc)
        store_contributions("store-test", j, store_dir=self.store_dir)
        retrieved = get_contributions("store-test", store_dir=self.store_dir)
        self.assertEqual(retrieved.project_name, "store-test")

    def test_store_with_dict(self):
        d = json.loads(to_json(self.pc))
        store_contributions("store-test", d, store_dir=self.store_dir)
        retrieved = get_contributions("store-test", store_dir=self.store_dir)
        self.assertEqual(retrieved.project_name, "store-test")

    def test_multiple_commits_retrievable_by_hash(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        hash1 = store_contributions("store-test", pc1, store_dir=self.store_dir)
        store_contributions("store-test", pc2, store_dir=self.store_dir)
        old = get_contributions("store-test", commit_hash=hash1, store_dir=self.store_dir)
        self.assertEqual(old.doi, "10.1/v1")

    def test_get_contributions_head_is_latest(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1, store_dir=self.store_dir)
        store_contributions("store-test", pc2, store_dir=self.store_dir)
        latest = get_contributions("store-test", store_dir=self.store_dir)
        self.assertEqual(latest.doi, "10.1/v2")

    def test_get_contributions_missing_project_raises(self):
        with self.assertRaises(Exception):
            get_contributions("does-not-exist", store_dir=self.store_dir)

    def test_list_project_commits_returns_list(self):
        store_contributions("store-test", self.pc, store_dir=self.store_dir)
        commits = list_project_commits("store-test", store_dir=self.store_dir)
        self.assertIsInstance(commits, list)
        self.assertGreater(len(commits), 0)

    def test_list_project_commits_structure(self):
        store_contributions("store-test", self.pc, store_dir=self.store_dir)
        commits = list_project_commits("store-test", store_dir=self.store_dir)
        entry = commits[0]
        self.assertIn("commit", entry)
        self.assertIn("timestamp", entry)
        self.assertIn("message", entry)

    def test_list_project_commits_newest_first(self):
        pc1 = ProjectContributions(project_name="store-test", doi="10.1/v1")
        pc2 = ProjectContributions(project_name="store-test", doi="10.1/v2")
        store_contributions("store-test", pc1, message="first", store_dir=self.store_dir)
        store_contributions("store-test", pc2, message="second", store_dir=self.store_dir)
        commits = list_project_commits("store-test", store_dir=self.store_dir)
        self.assertEqual(commits[0]["message"], "second")

    def test_list_project_commits_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            list_project_commits("no-such-project", store_dir=self.store_dir)

    def test_store_does_not_recurse_on_fresh_repo(self):
        pc = ProjectContributions(project_name="fresh")
        commit = store_contributions("fresh", pc, store_dir=self.store_dir)
        self.assertIsInstance(commit, str)

    def test_custom_message_stored(self):
        store_contributions("store-test", self.pc, message="my-msg", store_dir=self.store_dir)
        commits = list_project_commits("store-test", store_dir=self.store_dir)
        self.assertEqual(commits[0]["message"], "my-msg")

    def test_default_message_used_when_none(self):
        store_contributions("store-test", self.pc, store_dir=self.store_dir)
        commits = list_project_commits("store-test", store_dir=self.store_dir)
        self.assertIn("store-test", commits[0]["message"])


def _make_project_json(name="handler-project"):
    pc = _make_project(name)
    return to_json(pc)


class ContributionsHandlerTestCase(AsyncHTTPTestCase):
    def get_app(self):
        return Application(CONTRIBUTION_ROUTES)

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._store_dir = Path(self._tmpdir.name)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self._tmpdir.cleanup()

    def _patch_store(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.store_contributions",
            side_effect=lambda project, data, message=None: store_contributions(
                project, data, message=message, store_dir=self._store_dir
            ),
        )

    def _patch_get(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.get_contributions",
            side_effect=lambda project, commit_hash=None: get_contributions(
                project, commit_hash=commit_hash, store_dir=self._store_dir
            ),
        )

    def _patch_list(self):
        return patch(
            "aind_metadata_viz.contributions.handlers.list_project_commits",
            side_effect=lambda project: list_project_commits(project, store_dir=self._store_dir),
        )


class TestContributionsGetHandler(ContributionsHandlerTestCase):
    def _seed_project(self, name="handler-project"):
        pc = _make_project(name)
        store_contributions(name, pc, store_dir=self._store_dir)
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
        store_contributions("handler-project", pc2, store_dir=self._store_dir)
        commits = list_project_commits("handler-project", store_dir=self._store_dir)
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
            store_dir=self._store_dir,
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


if __name__ == "__main__":
    unittest.main()
