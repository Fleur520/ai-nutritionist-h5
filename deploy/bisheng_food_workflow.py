"""Generate a BiSheng 1.3.1 food workflow without contacting the platform.

The native QA retriever fixes k=1, which loses valid foods ranked below first.
A native Code node uses that same QA vector store to retrieve up to eight actual
QA answers per food, then deterministically preserves their evidence around the
matching LLM. The API call and answer metadata were verified on BiSheng 1.3.1.
Requires a working default embedding model, Milvus/ES and image parser in BiSheng.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re


PARSE_VISION_CODE = '''import json
import math

def main(vision, max_items):
    text = vision.strip()
    if text.startswith("```"):
        text = text.split("\\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    items = value.get("items") if isinstance(value, dict) else None
    if not isinstance(items, list) or len(items) > max_items:
        raise ValueError("视觉输出items无效或超过支持数量")
    result = {"items": []}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("视觉输出食物格式无效")
        name = item.get("name")
        preparation = item.get("preparation") or ""
        grams = item.get("estimated_grams")
        if not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError("食物名称无效")
        if not isinstance(preparation, str) or len(preparation) > 32:
            raise ValueError("食物制作状态无效")
        if isinstance(grams, bool) or not isinstance(grams, (int, float)) or not math.isfinite(grams) or not 5 <= grams <= 3000:
            raise ValueError("食物估算重量无效")
        clean = {"name": name.strip(), "preparation": preparation.strip(), "estimated_grams": grams}
        result["items"].append(clean)
    return result
'''


RETRIEVE_QA_CODE = '''import json
import math
from bisheng.interface.initialize.loading import instantiate_vectorstore
from bisheng.interface.vector_store.custom import MilvusWithPermissionCheck

def main(items, knowledge_id, score_threshold, top_k):
    if not isinstance(items, list) or len(items) > 8:
        raise ValueError("逐菜检索输入数量无效")
    if type(knowledge_id) is not int or knowledge_id <= 0 or type(top_k) is not int or not 1 <= top_k <= 8:
        raise ValueError("知识库或候选数量配置无效")
    if isinstance(score_threshold, bool) or not isinstance(score_threshold, (int, float)) or not math.isfinite(score_threshold) or not 0.01 <= score_threshold <= 0.99:
        raise ValueError("知识库候选阈值无效")
    if not items:
        return {"answers": []}
    params = {"collection_name": [{"key": knowledge_id, "label": "food"}], "user_name": "admin",
              "_is_check_auth": False, "search_kwargs": {"k": top_k}}
    retriever = instantiate_vectorstore(node_type="MilvusWithPermissionCheck", class_object=MilvusWithPermissionCheck, params=params)
    store = retriever.vectorstore
    answers = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("逐菜检索问题不能为空")
        preparation = item.get("preparation") or ""
        if not isinstance(preparation, str):
            raise ValueError("逐菜检索制作状态无效")
        query = item["name"].strip() + ("，" + preparation.strip() if preparation.strip() else "")
        rows = []
        for doc, distance in store.similarity_search_with_score(query, k=top_k):
            if isinstance(distance, bool) or not math.isfinite(float(distance)) or float(distance) < -0.000001:
                raise ValueError("知识库返回的检索距离无效")
            score = 1.0 - float(distance)
            if score < score_threshold:
                continue
            metadata = doc.metadata
            if not isinstance(metadata, dict) or str(metadata.get("knowledge_id")) != str(knowledge_id):
                raise ValueError("知识库候选不属于指定食品知识库")
            extra = json.loads(metadata.get("extra", ""))
            raw = extra.get("answer") if isinstance(extra, dict) else None
            if not isinstance(raw, str) or not raw:
                raise ValueError("知识库候选缺少原始QA答案")
            rows.append({"raw_answer": raw, "score": score})
        rows.sort(key=lambda row: row["score"], reverse=True)
        answers.append(rows[:top_k])
    return {"answers": answers}
'''


COLLECT_EVIDENCE_CODE = '''import json
import hashlib
import re
import math

def main(items, answers, knowledge_id, snapshot_id):
    if not isinstance(items, list) or not isinstance(answers, list) or len(items) != len(answers) or len(items) > 8:
        raise ValueError("检索结果数量无效")
    evidence_items = []
    for index, item in enumerate(items):
        retrieved = answers[index]
        evidence = []
        candidates = []
        seen = {}
        if not isinstance(retrieved, list) or len(retrieved) > 8:
            raise ValueError("单项食品知识库候选数量无效")
        for match in retrieved:
            if not isinstance(match, dict):
                raise ValueError("知识库候选格式无效")
            score = match.get("score")
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0.01 <= score <= 1.000001:
                raise ValueError("知识库候选相关度无效")
        for match in sorted(retrieved, key=lambda row: row["score"], reverse=True):
            raw = match.get("raw_answer")
            score = match.get("score")
            if not isinstance(raw, str) or len(raw) > 100000:
                raise ValueError("知识库答案格式无效")
            try:
                answer = json.loads(raw)
            except (TypeError, ValueError):
                raise ValueError("知识库答案必须为食品记录JSON")
            if not isinstance(answer, dict) or not isinstance(answer.get("record"), dict):
                raise ValueError("知识库答案缺少record")
            record = answer["record"]
            canonical = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            record_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
            if answer.get("record_sha256") != record_hash:
                raise ValueError("知识库食品记录校验失败")
            actual_snapshot = answer.get("snapshot_id")
            if not isinstance(actual_snapshot, str) or not re.fullmatch("[0-9a-f]{64}", actual_snapshot):
                raise ValueError("知识库目录版本无效")
            if snapshot_id and actual_snapshot != snapshot_id:
                raise ValueError("知识库目录版本与工作流不一致")
            code = record.get("code")
            if not isinstance(code, str) or not code or not isinstance(record.get("name"), str) or record.get("basis_g") != 100:
                raise ValueError("知识库食品编码或营养基准无效")
            if record.get("source_type") == "ai_estimate" and record.get("verified") not in (False, 0):
                raise ValueError("模型估算食品不允许标记为已核验")
            if code in seen:
                if seen[code] != record_hash:
                    raise ValueError("同一食品编码存在冲突知识库记录")
                continue
            seen[code] = record_hash
            candidate = dict(record)
            candidate.update(food_code=code, snapshot_id=actual_snapshot, record_sha256=record_hash, retrieval_score=score)
            candidates.append(candidate)
            evidence.append({"food_code": code, "knowledge_id": knowledge_id, "snapshot_id": actual_snapshot,
                             "record_sha256": record_hash, "source": "bisheng_qa", "raw_answer": raw,
                             "retrieval_score": score})
        row = dict(item)
        row.update(candidates=candidates, retrieval_evidence=evidence)
        evidence_items.append(row)
    result = {"schema_version": 1, "snapshot_id": snapshot_id, "items": evidence_items}
    matching = {"items": [{"index": index, "name": row["name"], "preparation": row.get("preparation", ""),
                           "candidates": [{"food_code": candidate["food_code"], "name": candidate["name"],
                                           "preparation": candidate.get("preparation", ""),
                                           "aliases": candidate.get("aliases", [])}
                                          for candidate in row["candidates"]]}
                          for index, row in enumerate(evidence_items)]}
    return {"evidence": result, "evidence_json": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
            "matching_json": json.dumps(matching, ensure_ascii=False, separators=(",", ":"))}
'''


FINALIZE_CODE = '''import json

def main(evidence, selection):
    evidence = json.loads(evidence)
    text = selection.strip()
    if text.startswith("```"):
        text = text.split("\\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    chosen = value.get("items") if isinstance(value, dict) else None
    if not isinstance(chosen, list) or len(chosen) != len(evidence["items"]):
        raise ValueError("匹配输出数量与识别食物不一致")
    result = {"schema_version": 1, "snapshot_id": evidence["snapshot_id"], "items": []}
    for index, original in enumerate(evidence["items"]):
        proposal = chosen[index]
        if not isinstance(proposal, dict) or type(proposal.get("index")) is not int or proposal.get("index") != index:
            raise ValueError("匹配输出食物顺序无效")
        code = proposal.get("food_code")
        allowed = {candidate["food_code"] for candidate in original["candidates"]}
        if code is not None and (not isinstance(code, str) or code not in allowed):
            raise ValueError("匹配食品编码不属于该菜检索结果")
        row = dict(original)
        row["food_code"] = code
        result["items"].append(row)
    return {"result": json.dumps(result, ensure_ascii=False, separators=(",", ":"))}
'''


def _param(key, value, kind="var", **extra):
    return {"key": key, "value": value, "type": kind, **extra}


def _node(node_id, kind, name, params, x, y, *, version=1, tab=None):
    data = {"id": node_id, "type": kind, "name": name, "description": name,
            "v": str(version), "group_params": [{"name": "配置", "params": params}]}
    if tab:
        data["tab"] = {"value": tab, "options": [{"label": tab, "key": tab}]}
    return {"id": node_id, "type": "flowNode", "position": {"x": x, "y": y}, "data": data}


def _code_node(node_id, name, code, inputs, outputs, x, y):
    return _node(node_id, "code", name, [
        _param("code_input", inputs, "code_input", required=True),
        _param("code", code, "code", required=True),
        _param("code_output", [{"key": key, "type": kind} for key, kind in outputs],
               "code_output", required=True, **{"global": "code:value.map(el => ({ label: el.key, value: el.key }))"}),
    ], x, y)


def _ref(key, value):
    return {"key": key, "type": "ref", "value": value}


def _literal(key, value):
    return {"key": key, "type": "input", "value": value}


def build_workflow(knowledge_id: int, vision_model_id: int, text_model_id: int,
                   *, snapshot_id: str, max_items: int = 8, score_threshold: float = 0.3,
                   name: str = "食光餐食识别与食品热量检索") -> dict:
    """Return the POST /api/v1/workflow/create body, initially offline.

    QA answers must be JSON {record, snapshot_id, record_sha256} from
    backend.app.knowledge_export. The workflow does not create/import a KB.
    The threshold must be calibrated with the deployed embedding model.
    """
    for label, number in (("knowledge_id", knowledge_id), ("vision_model_id", vision_model_id),
                          ("text_model_id", text_model_id)):
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ValueError(f"{label} must be a positive integer")
    if isinstance(max_items, bool) or not isinstance(max_items, int) or not 1 <= max_items <= 8:
        raise ValueError("max_items must be between 1 and 8")
    if not isinstance(snapshot_id, str) or not re.fullmatch(r"[0-9a-f]{64}", snapshot_id):
        raise ValueError("snapshot_id must be the catalog's 64 character SHA256")
    if isinstance(score_threshold, bool) or not isinstance(score_threshold, (float, int)) or not math.isfinite(score_threshold) or not 0.01 <= score_threshold <= 0.99:
        raise ValueError("score_threshold must be between 0.01 and 0.99")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("name is required")

    start = _node("start_food", "start", "开始", [
        _param("guide_word", "", "textarea"), _param("guide_question", [], "input_list"),
        _param("chat_history", 0, "chat_history_num"), _param("preset_question", [], "input_list"),
    ], 0, 0)
    image_field = {"key": "meal_image", "value": "上传一张餐食照片", "type": "file", "required": True,
                   "multiple": False, "file_type": "image", "file_content": "meal_image_content",
                   "file_path": "meal_image_path", "image_file": "meal_image_files", "file_content_size": 0}
    input_node = _node("input_meal", "input", "上传餐食图片", [
        _param("form_input", [image_field], "form", tab="form_input", **{"global": "item:form_input"}),
    ], 400, 0, version=2, tab="form_input")
    visual_system = ("你是餐食图像识别器。仅根据图片识别实际可见的食物，最多" + str(max_items) +
                     "项；复合菜作为一项，不再重复列配料。不要猜测不可见食物，不要输出热量或食品编码。"
                     "只输出JSON：{\"items\":[{\"name\":\"菜名\",\"estimated_grams\":150,\"preparation\":\"蒸熟\"}]}。"
                     "preparation仅可为生鲜、煮熟、蒸熟、炒熟、煎熟、烤熟、炸熟、炖熟、干制、即食、饮用、烘焙、熟制或空字符串。"
                     "能确认已熟但具体做法不明用熟制，不能确认生熟则为空；不要创造炒制、炖煮等类别。"
                     "图片无食物输出items空数组。重量为每项可食部分5至3000克的估算。")
    vision = _node("llm_vision", "llm", "识别菜名与估算重量", [
        _param("model_id", vision_model_id, "bisheng_model"), _param("temperature", 0.1, "slide"),
        _param("system_prompt", visual_system, "var_textarea"),
        _param("user_prompt", "识别这张餐食图片中的食物，返回指定JSON。", "var_textarea"),
        _param("image_prompt", ["input_meal.meal_image_files"], "image_prompt"),
        _param("output_user", False, "switch"), _param("output", [], "var"),
    ], 800, 0, version=2, tab="single")
    parse = _code_node("code_foods", "校验视觉输出并逐菜检索", PARSE_VISION_CODE,
                       [_ref("vision", "llm_vision.output"), _literal("max_items", max_items)],
                       [("items", "list")], 1200, 0)
    nodes = [start, input_node, vision, parse]
    nodes.append(_code_node("code_retrieve", "逐菜检索食品知识库前8候选", RETRIEVE_QA_CODE,
                           [_ref("items", "code_foods.items"), _literal("knowledge_id", knowledge_id),
                            _literal("score_threshold", score_threshold), _literal("top_k", 8)],
                           [("answers", "list")], 1600, 0))
    nodes.append(_code_node("code_evidence", "校验目录并保留检索证据", COLLECT_EVIDENCE_CODE,
                           [_ref("items", "code_foods.items"), _ref("answers", "code_retrieve.answers"),
                            _literal("knowledge_id", knowledge_id), _literal("snapshot_id", snapshot_id)],
                           [("evidence_json", "str"), ("matching_json", "str")], 2400, 0))
    nodes.append(_node("llm_match", "llm", "判断菜品与数据库食品是否一致", [
        _param("model_id", text_model_id, "bisheng_model"), _param("temperature", 0.0, "slide"),
        _param("system_prompt", "你负责判断图像识别菜品是否与候选数据库食品相同。仅使用该项candidates里的food_code。名称、生熟或做法不一致、不明确、无候选时food_code必须为null；禁止仅凭向量检索命中就确认匹配。严格保持顺序，不增删食物。只输出JSON：{\"items\":[{\"index\":0,\"food_code\":null}]}。不要输出候选、证据、热量或其他字段。", "var_textarea"),
        _param("user_prompt", "逐项校对以下识别结果和知识库候选：\n{{#code_evidence.matching_json#}}", "var_textarea"),
        _param("image_prompt", [], "image_prompt"), _param("output_user", False, "switch"),
        _param("output", [], "var"),
    ], 2800, 0, version=2, tab="single"))
    nodes.append(_code_node("code_result", "验证食品编码并附原始检索证据", FINALIZE_CODE,
                           [_ref("evidence", "code_evidence.evidence_json"), _ref("selection", "llm_match.output")],
                           [("result", "str")], 3200, 0))
    nodes.append(_node("output_food", "output", "返回食品编码与热量检索结果", [
        _param("message", {"msg": "{{#code_result.result#}}", "files": []}, "var_textarea_file"),
        _param("output_result", {"type": "", "value": ""}, "output_form"),
    ], 3600, 0, version=2))
    nodes.append(_node("end_food", "end", "结束", [], 4000, 0))

    pairs = [("start_food", "input_meal"), ("input_meal", "llm_vision"), ("llm_vision", "code_foods"),
             ("code_foods", "code_retrieve"), ("code_retrieve", "code_evidence")]
    pairs.extend([("code_evidence", "llm_match"),
                  ("llm_match", "code_result"), ("code_result", "output_food"), ("output_food", "end_food")])
    edges = [{"id": f"{source}-{target}", "source": source, "target": target,
              "sourceHandle": "right_handle", "targetHandle": "left_handle", "type": "customEdge"}
             for source, target in pairs]
    return {"name": name.strip(), "description": "上传餐食图片，逐菜检索数据库食品知识库。食品编码和营养以H5实时数据库为准；AI估算未经核验。",
            "flow_type": 10, "status": 1, "data": {"nodes": nodes, "edges": edges,
                                                        "viewport": {"x": 0, "y": 0, "zoom": 0.5}}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-id", type=int, required=True)
    parser.add_argument("--vision-model-id", type=int, required=True)
    parser.add_argument("--text-model-id", type=int, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--max-items", type=int, default=8)
    parser.add_argument("--score-threshold", type=float, default=0.3)
    parser.add_argument("--name", default="食光餐食识别与食品热量检索")
    parser.add_argument("--output", type=Path, required=True,
                        help="Explicit local JSON path; keep generated platform IDs outside Git")
    args = parser.parse_args(argv)
    body = build_workflow(args.knowledge_id, args.vision_model_id, args.text_model_id,
                          snapshot_id=args.snapshot_id, max_items=args.max_items,
                          score_threshold=args.score_threshold, name=args.name)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(body, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output.resolve()), "nodes": len(body["data"]["nodes"]),
                      "max_foods": args.max_items, "retrieval_candidates_per_food": 8}, ensure_ascii=False))


if __name__ == "__main__":
    main()
