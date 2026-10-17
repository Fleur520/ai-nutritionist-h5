import ast
import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bisheng_food_workflow import (build_workflow, PARSE_VISION_CODE,
                                   RETRIEVE_QA_CODE, COLLECT_EVIDENCE_CODE, FINALIZE_CODE, main)


SNAPSHOT = "a" * 64


def code_main(source):
    """Execute with the same separate global/local maps as v1.3.1 CodeParser."""
    global_values, local_values = {}, {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                global_values[alias.asname or alias.name] = importlib.import_module(alias.name)
        elif isinstance(node, ast.ImportFrom):
            module = importlib.import_module(node.module)
            for alias in node.names:
                global_values[alias.asname or alias.name] = getattr(module, alias.name)
        elif isinstance(node, ast.FunctionDef):
            exec(compile(ast.Module(body=[node], type_ignores=[]), "<workflow>", "exec"),
                 global_values, local_values)
    return local_values["main"]


def answer(code="rice", preparation="煮熟", **overrides):
    record = {"code": code, "name": "白米饭", "preparation": preparation,
              "basis_g": 100, "kcal": 116, "protein": 2.6, "fat": 0.3,
              "carbs": 25.6, "source_type": "ai_estimate", "verified": False}
    record.update(overrides)
    canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return json.dumps({"record": record, "snapshot_id": SNAPSHOT,
                       "record_sha256": hashlib.sha256(canonical.encode()).hexdigest()}, ensure_ascii=False)


def matches(*raw_answers):
    return [{"raw_answer": raw, "score": 0.5} for raw in raw_answers]


def native_retriever(fake_store, calls):
    """Load exact native code with only the two server-only dependencies stubbed."""
    def instantiate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(vectorstore=fake_store)
    modules = {"bisheng.interface.initialize.loading": SimpleNamespace(instantiate_vectorstore=instantiate),
               "bisheng.interface.vector_store.custom": SimpleNamespace(MilvusWithPermissionCheck=object)}
    with patch.dict(sys.modules, modules):
        return code_main(RETRIEVE_QA_CODE)


class WorkflowGeneratorTests(unittest.TestCase):
    def test_native_file_visual_top_eight_retrieval_and_output_schema(self):
        body = build_workflow(7, 11, 12, snapshot_id=SNAPSHOT)
        nodes = {node["id"]: node["data"] for node in body["data"]["nodes"]}
        self.assertEqual(body["status"], 1)
        self.assertEqual(body["flow_type"], 10)
        self.assertNotIn("qa_retriever", [node["type"] for node in nodes.values()])
        self.assertEqual(len(nodes), 10)
        get = lambda node: {p["key"]: p["value"] for group in nodes[node]["group_params"] for p in group["params"]}
        self.assertEqual(nodes["input_meal"]["tab"]["value"], "form_input")
        form = get("input_meal")["form_input"][0]
        self.assertEqual((form["key"], form["type"], form["image_file"]),
                         ("meal_image", "file", "meal_image_files"))
        self.assertEqual(get("llm_vision")["image_prompt"], ["input_meal.meal_image_files"])
        retrieve_inputs = {row["key"]: row["value"] for row in get("code_retrieve")["code_input"]}
        self.assertEqual(retrieve_inputs, {"items": "code_foods.items", "knowledge_id": 7,
                                          "score_threshold": 0.3, "top_k": 8})
        self.assertIn({"source": "code_foods", "target": "code_retrieve"},
                      [{"source": e["source"], "target": e["target"]} for e in body["data"]["edges"]])
        self.assertEqual(get("output_food")["message"]["msg"], "{{#code_result.result#}}")
        self.assertIn("{{#code_evidence.matching_json#}}", get("llm_match")["user_prompt"])
        self.assertEqual(get("code_result")["code_input"][0]["value"], "code_evidence.evidence_json")
        for node in nodes.values():
            if node["type"] == "code":
                params = {p["key"]: p["value"] for group in node["group_params"] for p in group["params"]}
                if node["id"] == "code_retrieve":
                    self.assertTrue(callable(native_retriever(None, [])))
                else:
                    self.assertTrue(callable(code_main(params["code"])))

    def test_generator_rejects_invalid_platform_ids_snapshot_and_limits(self):
        for kwargs in ({"knowledge_id": 0}, {"vision_model_id": True}, {"text_model_id": -1},
                       {"snapshot_id": ""}, {"max_items": 9}, {"score_threshold": float("nan")}):
            args = {"knowledge_id": 1, "vision_model_id": 2, "text_model_id": 3, "snapshot_id": SNAPSHOT}
            args.update(kwargs)
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                build_workflow(**args)

    def test_multiple_visual_foods_retained_without_padding_fake_foods(self):
        items = [{"name": "白米饭", "preparation": "煮熟", "estimated_grams": 150},
                 {"name": "紫薯", "preparation": "蒸熟", "estimated_grams": 90}]
        result = code_main(PARSE_VISION_CODE)(json.dumps({"items": items}), 8)
        self.assertEqual(result["items"], items)
        self.assertEqual(set(result), {"items"})

    def test_invalid_visual_result_fails_instead_of_fabricating_food(self):
        parser = code_main(PARSE_VISION_CODE)
        for value in ({"items": [{}]}, {"items": [{"name": "饭", "estimated_grams": True}]},
                      {"items": [{"name": "饭", "estimated_grams": float("inf")}]}, {"items": [1]},
                      {"items": [{}] * 9}, {"result": []}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parser(json.dumps(value), 8)

    def test_no_food_image_can_return_empty_items(self):
        parsed = code_main(PARSE_VISION_CODE)('{"items":[]}', 8)
        collected = code_main(COLLECT_EVIDENCE_CODE)(parsed["items"], [], 7, SNAPSHOT)
        result = code_main(FINALIZE_CODE)(collected["evidence_json"], '{"items":[]}')
        self.assertEqual(json.loads(result["result"])["items"], [])

    def test_candidates_and_evidence_come_from_native_qa_answer(self):
        raw = answer()
        items = [{"name": "米饭", "preparation": "煮熟", "estimated_grams": 150}]
        collected = code_main(COLLECT_EVIDENCE_CODE)(items, [matches(raw)], 7, SNAPSHOT)
        original = collected["evidence"]["items"][0]
        self.assertEqual(len(collected["evidence"]["items"]), 1)
        self.assertEqual(original["candidates"][0]["food_code"], "rice")
        self.assertEqual(original["candidates"][0]["kcal"], 116)
        self.assertIs(original["candidates"][0]["verified"], False)
        self.assertEqual(original["retrieval_evidence"][0]["raw_answer"], raw)
        self.assertEqual(original["retrieval_evidence"][0]["knowledge_id"], 7)
        self.assertEqual(json.loads(collected["evidence_json"]), collected["evidence"])

    def test_stale_tampered_or_unverified_promoted_record_rejected(self):
        items = [{"name": "米饭", "estimated_grams": 150}]
        good = json.loads(answer())
        bad_hash = dict(good, record_sha256="b" * 64)
        bad_snapshot = dict(good, snapshot_id="c" * 64)
        for raw in ("not-json", "[]", json.dumps(bad_hash), json.dumps(bad_snapshot),
                    answer(verified=True), answer(basis_g=1)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                code_main(COLLECT_EVIDENCE_CODE)(items, [matches(raw)], 7, SNAPSHOT)

    def test_llm_cannot_add_candidates_evidence_or_override_visual_weights(self):
        items = [{"name": "米饭", "preparation": "煮熟", "estimated_grams": 150}]
        evidence = code_main(COLLECT_EVIDENCE_CODE)(items, [matches(answer())], 7, SNAPSHOT)["evidence"]
        forged = {"items": [{"index": 0, "food_code": "rice", "estimated_grams": 1,
                              "candidates": [{"food_code": "apple"}], "retrieval_evidence": ["fake"]}]}
        result = json.loads(code_main(FINALIZE_CODE)(json.dumps(evidence), json.dumps(forged))["result"])
        self.assertEqual(result["items"][0]["estimated_grams"], 150)
        self.assertEqual(result["items"][0]["candidates"], evidence["items"][0]["candidates"])
        self.assertEqual(result["items"][0]["retrieval_evidence"], evidence["items"][0]["retrieval_evidence"])

    def test_unretrieved_code_reordering_and_added_food_rejected(self):
        evidence = code_main(COLLECT_EVIDENCE_CODE)([{"name": "米饭", "estimated_grams": 150}], [matches(answer())], 7, SNAPSHOT)["evidence"]
        for chosen in ([{"index": 0, "food_code": "apple"}], [{"index": 1, "food_code": "rice"}], [],
                       [{"index": 0, "food_code": "rice"}] * 2):
            with self.subTest(chosen=chosen), self.assertRaises(ValueError):
                code_main(FINALIZE_CODE)(json.dumps(evidence), json.dumps({"items": chosen}))

    def test_no_kb_match_stays_unselected(self):
        evidence = code_main(COLLECT_EVIDENCE_CODE)([{"name": "未知菜", "estimated_grams": 150}], [[]], 7, SNAPSHOT)["evidence"]
        result = json.loads(code_main(FINALIZE_CODE)(json.dumps(evidence), '{"items":[{"index":0,"food_code":null}]}')["result"])
        self.assertIsNone(result["items"][0]["food_code"])
        self.assertEqual(result["items"][0]["retrieval_evidence"], [])

    def test_native_retrieval_uses_same_fixed_qa_store_and_top_eight_per_real_food(self):
        queries, calls = [], []
        raw = answer()
        def search(query, k):
            queries.append((query, k))
            return [(SimpleNamespace(metadata={"knowledge_id": "7", "extra": json.dumps({"answer": raw})}), 0.53),
                    (SimpleNamespace(metadata={"knowledge_id": "7", "extra": json.dumps({"answer": raw})}), 0.8)]
        retrieve = native_retriever(SimpleNamespace(similarity_search_with_score=search), calls)
        items = [{"name": "米饭", "preparation": "蒸熟"}, {"name": "宫保鸡丁", "preparation": "炒熟"}]
        result = retrieve(items, 7, 0.3, 8)
        self.assertEqual(queries, [("米饭，蒸熟", 8), ("宫保鸡丁，炒熟", 8)])
        self.assertEqual(len(result["answers"]), 2)
        self.assertEqual(len(result["answers"][0]), 1)
        self.assertAlmostEqual(result["answers"][0][0]["score"], 0.47)
        self.assertEqual(result["answers"][0][0]["raw_answer"], raw)
        self.assertEqual(calls[0]["node_type"], "MilvusWithPermissionCheck")
        self.assertEqual(calls[0]["params"]["collection_name"], [{"key": 7, "label": "food"}])
        self.assertIs(calls[0]["params"]["_is_check_auth"], False)

    def test_empty_items_do_not_initialize_store_or_embed_fake_queries(self):
        calls = []
        retrieve = native_retriever(None, calls)
        self.assertEqual(retrieve([], 7, 0.3, 8), {"answers": []})
        self.assertEqual(calls, [])

    def test_native_empty_query_fails_without_searching(self):
        queries = []
        retrieve = native_retriever(SimpleNamespace(similarity_search_with_score=lambda *args, **kwargs: queries.append(args)), [])
        with self.assertRaises(ValueError):
            retrieve([{"name": "   "}], 7, 0.3, 8)
        self.assertEqual(queries, [])

    def test_native_retrieval_rejects_foreign_or_malformed_qa_metadata(self):
        for metadata in ({"knowledge_id": "8", "extra": json.dumps({"answer": answer()})},
                         {"extra": json.dumps({"answer": answer()})},
                         {"knowledge_id": "7", "extra": "[]"},
                         {"knowledge_id": "7", "extra": "malformed"},
                         {"knowledge_id": "7", "extra": json.dumps({"answer": {"record": "fake"}})}):
            with self.subTest(metadata=metadata):
                retrieve = native_retriever(SimpleNamespace(similarity_search_with_score=lambda *args, **kwargs: [(SimpleNamespace(metadata=metadata), 0.5)]), [])
                with self.assertRaises(ValueError):
                    retrieve([{"name": "米饭"}], 7, 0.3, 8)

    def test_native_retrieval_rejects_invalid_distances(self):
        metadata = {"knowledge_id": "7", "extra": json.dumps({"answer": answer()})}
        for distance in (True, float("nan"), float("inf"), -0.5):
            with self.subTest(distance=distance):
                retrieve = native_retriever(SimpleNamespace(similarity_search_with_score=lambda *args, **kwargs: [(SimpleNamespace(metadata=metadata), distance)]), [])
                with self.assertRaises(ValueError):
                    retrieve([{"name": "米饭"}], 7, 0.3, 8)

    def test_candidates_keep_score_order_and_deduplicate_same_food(self):
        raw_rice, raw_millet = answer(), answer("millet", name="小米饭")
        retrieved = [{"raw_answer": raw_rice, "score": 0.4},
                     {"raw_answer": raw_millet, "score": 0.6},
                     {"raw_answer": raw_rice, "score": 0.5}]
        result = code_main(COLLECT_EVIDENCE_CODE)([{"name": "米饭"}], [retrieved], 7, SNAPSHOT)["evidence"]["items"][0]
        self.assertEqual([row["food_code"] for row in result["candidates"]], ["millet", "rice"])
        self.assertEqual([row["retrieval_score"] for row in result["candidates"]], [0.6, 0.5])
        self.assertEqual([row["raw_answer"] for row in result["retrieval_evidence"]], [raw_millet, raw_rice])

    def test_matcher_projection_keeps_food_identity_and_drops_nutrition_and_evidence(self):
        raw = answer(aliases=["大米饭", "米饭"])
        collected = code_main(COLLECT_EVIDENCE_CODE)([{"name": "米饭", "preparation": "蒸熟", "estimated_grams": 150}],
                                                     [matches(raw)], 7, SNAPSHOT)
        projection = json.loads(collected["matching_json"])
        self.assertEqual(projection, {"items": [{"index": 0, "name": "米饭", "preparation": "蒸熟", "candidates": [
            {"food_code": "rice", "name": "白米饭", "preparation": "煮熟", "aliases": ["大米饭", "米饭"]}]}]})
        for key in ("estimated_grams", "kcal", "protein", "fat", "carbs", "source_type", "verified",
                    "record_sha256", "snapshot_id", "raw_answer", "retrieval_evidence", "retrieval_score"):
            self.assertNotIn('"' + key + '"', collected["matching_json"])
        full = json.loads(collected["evidence_json"])["items"][0]
        self.assertEqual(full["estimated_grams"], 150)
        self.assertEqual(full["candidates"][0]["kcal"], 116)
        self.assertEqual(full["retrieval_evidence"][0]["raw_answer"], raw)

    def test_conflicting_records_with_same_code_are_rejected(self):
        with self.assertRaises(ValueError):
            code_main(COLLECT_EVIDENCE_CODE)([{"name": "米饭"}], [matches(answer(), answer(kcal=999))], 7, SNAPSHOT)

    def test_candidate_evidence_rejects_malformed_scores_rows_and_counts(self):
        for rows in ([{"raw_answer": answer(), "score": True}], [{"raw_answer": answer(), "score": float("nan")}],
                     [{"raw_answer": answer(), "score": -0.1}], [{"raw_answer": answer(), "score": 1.5}],
                     ["invalid"], [{"raw_answer": answer()}], matches(*[answer()] * 9)):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                code_main(COLLECT_EVIDENCE_CODE)([{"name": "米饭"}], [rows], 7, SNAPSHOT)

    def test_full_native_code_chain_can_select_second_retrieved_food(self):
        raw_rice, raw_millet = answer(), answer("millet", name="薏米饭")
        def search(query, k):
            return [(SimpleNamespace(metadata={"knowledge_id": "7", "extra": json.dumps({"answer": raw})}), distance)
                    for raw, distance in ((raw_millet, 0.528), (raw_rice, 0.533))]
        parsed = code_main(PARSE_VISION_CODE)('{"items":[{"name":"米饭","preparation":"蒸熟","estimated_grams":150}]}', 8)
        answers = native_retriever(SimpleNamespace(similarity_search_with_score=search), [])(parsed["items"], 7, 0.3, 8)["answers"]
        collected = code_main(COLLECT_EVIDENCE_CODE)(parsed["items"], answers, 7, SNAPSHOT)
        result = json.loads(code_main(FINALIZE_CODE)(collected["evidence_json"], '{"items":[{"index":0,"food_code":"rice"}]}')["result"])
        self.assertEqual(result["items"][0]["food_code"], "rice")
        self.assertEqual([row["food_code"] for row in result["items"][0]["candidates"]], ["millet", "rice"])
        self.assertEqual(result["items"][0]["estimated_grams"], 150)

    def test_cli_requires_explicit_output_and_will_not_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "workflow.json"
            args = ["--knowledge-id", "7", "--vision-model-id", "11", "--text-model-id", "12",
                    "--snapshot-id", SNAPSHOT, "--output", str(path)]
            main(args)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["name"], "食光餐食识别与食品热量检索")
            with self.assertRaises(FileExistsError):
                main(args)


if __name__ == "__main__":
    unittest.main()
