"""Tests for the verification graph's pure derivation and validation rules."""

import unittest

from aind_metadata_viz.verification.graph import (
    axis_summary,
    compile_manifest,
    compile_snapshot,
    compute_depths,
    compute_effective_status,
    filter_by_status,
    mark_descendants_stale,
    node_label,
    statement_sentence,
    subgraph,
    validate_node,
)


def entity(node_id, entity_type="unit", **extra):
    """Build an entity node document."""
    return {"id": node_id, "kind": "entity", "entity_type": entity_type, "label": node_id, **extra}


def relation(node_id, subject=("unit",), obj=("stimulus",)):
    """Build a relation node document."""
    return {
        "id": node_id,
        "kind": "relation",
        "label": "responds to",
        "signature": {"subject": list(subject), "object": list(obj)},
    }


def statement(node_id, status="verified", depends_on=(), **extra):
    """Build a statement node document."""
    return {
        "id": node_id,
        "kind": "statement",
        "subject": "ent-unit",
        "relation": "rel-responds",
        "object": "ent-stim",
        "status": status,
        "depends_on": list(depends_on),
        **extra,
    }


BASE = [entity("ent-unit"), entity("ent-stim", "stimulus"), relation("rel-responds")]


class EffectiveStatusTestCase(unittest.TestCase):
    def test_entities_and_relations_never_drag_a_statement_down(self):
        by_id = {n["id"]: n for n in BASE}
        self.assertEqual(compute_effective_status(by_id)["ent-unit"], "verified")

    def test_own_status_is_used_when_there_are_no_dependencies(self):
        by_id = {n["id"]: n for n in BASE + [statement("s1", "proposed")]}
        self.assertEqual(compute_effective_status(by_id)["s1"], "proposed")

    def test_worst_dependency_status_wins(self):
        nodes = BASE + [
            statement("low", "failed"),
            statement("mid", "verified", ["low"]),
            statement("top", "verified", ["mid"]),
        ]
        effective = compute_effective_status({n["id"]: n for n in nodes})
        self.assertEqual(effective["top"], "failed")
        self.assertEqual(effective["mid"], "failed")

    def test_staleness_propagates_up_the_derivation_chain(self):
        nodes = BASE + [statement("low", "stale"), statement("top", "verified", ["low"])]
        self.assertEqual(compute_effective_status({n["id"]: n for n in nodes})["top"], "stale")

    def test_a_missing_dependency_is_a_failure(self):
        nodes = BASE + [statement("top", "verified", ["gone"])]
        self.assertEqual(compute_effective_status({n["id"]: n for n in nodes})["top"], "failed")

    def test_a_dependency_cycle_is_never_reported_as_verified(self):
        nodes = BASE + [statement("a", "verified", ["b"]), statement("b", "verified", ["a"])]
        effective = compute_effective_status({n["id"]: n for n in nodes})
        self.assertEqual(effective["a"], "failed")

    def test_a_statement_with_no_stored_status_defaults_to_proposed(self):
        node = {"id": "s", "kind": "statement", "depends_on": []}
        self.assertEqual(compute_effective_status({"s": node})["s"], "proposed")


class DepthTestCase(unittest.TestCase):
    def test_foundations_sit_at_depth_zero(self):
        nodes = BASE + [statement("low")]
        depths = compute_depths({n["id"]: n for n in nodes})
        self.assertEqual(depths["low"], 0)
        self.assertEqual(depths["ent-unit"], 0)

    def test_each_claim_sits_one_above_its_deepest_evidence(self):
        nodes = BASE + [
            statement("l1"),
            statement("l2", depends_on=["l1"]),
            statement("l3", depends_on=["l1", "l2"]),
        ]
        depths = compute_depths({n["id"]: n for n in nodes})
        self.assertEqual((depths["l1"], depths["l2"], depths["l3"]), (0, 1, 2))

    def test_a_cycle_terminates_instead_of_recursing_forever(self):
        nodes = [statement("a", depends_on=["b"]), statement("b", depends_on=["a"])]
        depths = compute_depths({n["id"]: n for n in nodes})
        self.assertIn("a", depths)

    def test_a_missing_dependency_contributes_no_depth(self):
        depths = compute_depths({"a": statement("a", depends_on=["gone"])})
        self.assertEqual(depths["a"], 1)


class SnapshotTestCase(unittest.TestCase):
    def setUp(self):
        self.nodes = BASE + [
            statement("l1", verification={"reproducible": {"status": "passed"}}),
            statement("l2", "verified", ["l1"]),
            entity("ent-pop", "population", members=["ent-unit"]),
        ]
        self.snapshot = compile_snapshot(self.nodes)

    def test_every_node_is_summarized(self):
        self.assertEqual(len(self.snapshot["nodes"]), len(self.nodes))

    def test_axes_default_to_not_attempted(self):
        summary = next(n for n in self.snapshot["nodes"] if n["id"] == "l1")
        self.assertEqual(summary["axes"]["reproducible"], "passed")
        self.assertEqual(summary["axes"]["robust"], "not_attempted")

    def test_entities_carry_no_status_or_axes(self):
        summary = next(n for n in self.snapshot["nodes"] if n["id"] == "ent-unit")
        self.assertIsNone(summary["status"])
        self.assertEqual(summary["axes"], {})

    def test_triple_and_derivation_edges_are_materialized(self):
        types = {e["type"] for e in self.snapshot["edges"]}
        self.assertEqual(types, {"subject", "relation", "object", "depends_on", "member"})

    def test_nodes_are_ordered_by_derivation_depth(self):
        depths = [n["depth"] for n in self.snapshot["nodes"]]
        self.assertEqual(depths, sorted(depths))

    def test_documents_without_an_id_are_skipped(self):
        self.assertEqual(compile_snapshot([{"kind": "entity"}])["nodes"], [])

    def test_has_code_reflects_the_sidecar_pointer(self):
        snapshot = compile_snapshot([statement("s", code="code/s/")])
        self.assertTrue(snapshot["nodes"][0]["has_code"])

    def test_updated_falls_back_to_the_creation_stamp(self):
        node = statement("s", provenance={"author": "a", "created": "2026-01-01T00:00:00Z"})
        self.assertEqual(compile_snapshot([node])["nodes"][0]["updated"], "2026-01-01T00:00:00Z")


class SnapshotFilterTestCase(unittest.TestCase):
    def setUp(self):
        self.snapshot = compile_snapshot(
            BASE + [statement("l1"), statement("l2", "verified", ["l1"]), statement("bad", "failed")]
        )

    def test_subgraph_keeps_only_what_a_root_reaches(self):
        result = subgraph(self.snapshot, "l2")
        ids = {n["id"] for n in result["nodes"]}
        self.assertIn("l1", ids)
        self.assertNotIn("bad", ids)

    def test_subgraph_of_an_unknown_root_is_empty(self):
        self.assertEqual(subgraph(self.snapshot, "nope")["nodes"], [])

    def test_status_filter_keeps_matching_statements_and_their_triples(self):
        result = filter_by_status(self.snapshot, "failed")
        ids = {n["id"] for n in result["nodes"]}
        self.assertIn("bad", ids)
        self.assertIn("ent-unit", ids)
        self.assertNotIn("l1", ids)


class ManifestTestCase(unittest.TestCase):
    def test_manifest_reports_effective_status_for_statements_only(self):
        entries = compile_manifest(BASE + [statement("l1", "failed"), statement("l2", "verified", ["l1"])])
        by_id = {e["id"]: e for e in entries}
        self.assertEqual(by_id["l2"]["status"], "failed")
        self.assertIsNone(by_id["ent-unit"]["status"])

    def test_manifest_is_sorted_by_id(self):
        entries = compile_manifest(BASE)
        self.assertEqual([e["id"] for e in entries], sorted(e["id"] for e in entries))


class ValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.existing = {n["id"]: n for n in BASE}

    def test_a_well_formed_triple_validates(self):
        doc = statement("s")
        self.assertIsNone(validate_node(doc, {**self.existing, "s": doc}))

    def test_a_subject_of_the_wrong_entity_type_is_rejected(self):
        existing = {**self.existing, "ent-stim2": entity("ent-stim2", "stimulus")}
        doc = statement("s", subject="ent-stim2")
        error = validate_node(doc, {**existing, "s": doc})
        self.assertIn("relation accepts", error)

    def test_an_object_of_the_wrong_entity_type_is_rejected(self):
        doc = statement("s", object="ent-unit")
        self.assertIn("relation accepts", validate_node(doc, {**self.existing, "s": doc}))

    def test_a_missing_subject_is_rejected(self):
        doc = statement("s", subject="gone")
        self.assertIn("not in the graph", validate_node(doc, {**self.existing, "s": doc}))

    def test_a_relation_used_as_a_subject_is_rejected(self):
        doc = statement("s", subject="rel-responds")
        self.assertIn("not an entity node", validate_node(doc, {**self.existing, "s": doc}))

    def test_a_missing_relation_is_rejected(self):
        doc = statement("s", relation="gone")
        self.assertIn("not in the graph", validate_node(doc, {**self.existing, "s": doc}))

    def test_an_entity_used_as_a_relation_is_rejected(self):
        doc = statement("s", relation="ent-unit")
        self.assertIn("not a relation node", validate_node(doc, {**self.existing, "s": doc}))

    def test_a_dangling_dependency_is_rejected(self):
        doc = statement("s", depends_on=["gone"])
        self.assertIn("depends_on 'gone'", validate_node(doc, {**self.existing, "s": doc}))

    def test_depending_on_a_non_statement_is_rejected(self):
        doc = statement("s", depends_on=["ent-unit"])
        self.assertIn("not a statement node", validate_node(doc, {**self.existing, "s": doc}))

    def test_a_dependency_cycle_is_rejected(self):
        other = statement("other", depends_on=["s"])
        doc = statement("s", depends_on=["other"])
        existing = {**self.existing, "other": other, "s": doc}
        self.assertEqual(validate_node(doc, existing), "depends_on introduces a cycle")

    def test_a_cycle_check_on_an_id_less_document_is_skipped(self):
        doc = {"kind": "statement", "subject": "ent-unit", "relation": "rel-responds",
               "object": "ent-stim", "depends_on": []}
        self.assertIsNone(validate_node(doc, self.existing))

    def test_a_population_member_must_be_an_existing_entity(self):
        doc = entity("ent-pop", "population", members=["gone"])
        self.assertIn("not in the graph", validate_node(doc, {}))

    def test_a_population_member_must_not_be_a_statement(self):
        doc = entity("ent-pop", "population", members=["s"])
        self.assertIn("not an entity node", validate_node(doc, {"s": statement("s")}))

    def test_a_valid_population_validates(self):
        doc = entity("ent-pop", "population", members=["ent-unit"])
        self.assertIsNone(validate_node(doc, self.existing))

    def test_relations_have_nothing_to_validate(self):
        self.assertIsNone(validate_node(relation("rel-x"), {}))

    def test_an_unknown_kind_is_rejected(self):
        self.assertIn("unknown node kind", validate_node({"kind": "wat"}, {}))

    def test_a_relation_with_an_open_signature_accepts_any_entity(self):
        existing = {**self.existing, "rel-open": relation("rel-open", subject=(), obj=())}
        doc = statement("s", relation="rel-open", subject="ent-stim", object="ent-unit")
        self.assertIsNone(validate_node(doc, {**existing, "s": doc}))


class StalenessTestCase(unittest.TestCase):
    def test_verified_descendants_are_marked_stale(self):
        nodes = {n["id"]: n for n in [statement("l1"), statement("l2", "verified", ["l1"]),
                                      statement("l3", "verified", ["l2"])]}
        touched = mark_descendants_stale(nodes, "l1")
        self.assertEqual(sorted(touched), ["l2", "l3"])
        self.assertEqual(nodes["l2"]["status"], "stale")

    def test_the_changed_node_itself_is_left_alone(self):
        nodes = {"l1": statement("l1"), "l2": statement("l2", "verified", ["l1"])}
        mark_descendants_stale(nodes, "l1")
        self.assertEqual(nodes["l1"]["status"], "verified")

    def test_non_verified_descendants_are_not_touched(self):
        nodes = {"l1": statement("l1"), "l2": statement("l2", "failed", ["l1"])}
        self.assertEqual(mark_descendants_stale(nodes, "l1"), [])

    def test_a_cycle_does_not_loop_forever(self):
        nodes = {"a": statement("a", "verified", ["b"]), "b": statement("b", "verified", ["a"])}
        mark_descendants_stale(nodes, "a")
        self.assertEqual(nodes["b"]["status"], "stale")

    def test_a_dependent_that_no_longer_exists_is_skipped(self):
        nodes = {"l2": statement("l2", "verified", ["l1"])}
        self.assertEqual(mark_descendants_stale(nodes, "l2"), [])


class RenderingTestCase(unittest.TestCase):
    def test_a_node_falls_back_to_its_id_for_a_label(self):
        self.assertEqual(node_label({"id": "x"}), "x")
        self.assertEqual(node_label({}), "")

    def test_a_statement_renders_from_its_triples_labels(self):
        by_id = {n["id"]: n for n in BASE}
        sentence = statement_sentence(statement("s"), by_id)
        self.assertEqual(sentence, "ent-unit responds to ent-stim")

    def test_an_explicit_label_wins(self):
        sentence = statement_sentence(statement("s", label="Unit 1 responds to vis1"), {})
        self.assertEqual(sentence, "Unit 1 responds to vis1")

    def test_missing_triple_members_fall_back_to_their_ids(self):
        self.assertEqual(statement_sentence(statement("s"), {}), "ent-unit rel-responds ent-stim")

    def test_axis_summary_defaults_every_axis(self):
        summary = axis_summary({})
        self.assertEqual(set(summary), {"reproducible", "replicable", "robust", "generalizable"})
        self.assertTrue(all(v == "not_attempted" for v in summary.values()))


class DiamondDependencyTestCase(unittest.TestCase):
    """A claim that reaches the same evidence by two routes."""

    def setUp(self):
        self.nodes = {
            "deep": statement("deep"),
            "shared": statement("shared", depends_on=["deep"]),
            "left": statement("left", depends_on=["shared"]),
            "right": statement("right", depends_on=["shared"]),
        }
        self.nodes.update({n["id"]: n for n in BASE})

    def test_shared_evidence_is_only_walked_once(self):
        doc = statement("top", depends_on=["left", "right"])
        self.assertIsNone(validate_node(doc, {**self.nodes, "top": doc}))

    def test_a_diamond_takes_its_depth_from_the_deepest_route(self):
        self.nodes["top"] = statement("top", depends_on=["left", "right"])
        self.assertEqual(compute_depths(self.nodes)["top"], 3)

    def test_one_failed_foundation_fails_every_route_above_it(self):
        self.nodes["deep"]["status"] = "failed"
        self.nodes["top"] = statement("top", depends_on=["left", "right"])
        self.assertEqual(compute_effective_status(self.nodes)["top"], "failed")

    def test_staleness_reaches_a_diamond_apex_once(self):
        self.nodes["top"] = statement("top", depends_on=["left", "right"])
        touched = mark_descendants_stale(self.nodes, "deep")
        self.assertEqual(sorted(touched), ["left", "right", "shared", "top"])


if __name__ == "__main__":
    unittest.main()
