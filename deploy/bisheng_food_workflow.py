"""Generate a BiSheng 1.3.1 food workflow without contacting the platform.

An explicit Code node retrieves up to eight actual document chunks per food
using BiSheng's document vector store. Original food records and chunk hashes
are checked before the matching LLM can select a food code. The native RAG node
only exposes generated answers downstream, so it cannot supply this evidence.
Requires a working default embedding model, Milvus/ES and image parser in BiSheng.
"""
from __future__ import annotations

import argparse
import ast
import json
import math
from pathlib import Path
import re
import textwrap


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


RETRIEVE_DOCUMENT_CODE = '''import json
import math
import hashlib
from bisheng.database.models.knowledge import KnowledgeDao
from concurrent.futures import ThreadPoolExecutor
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
        return {"documents": []}
    knowledge = KnowledgeDao.query_by_id(knowledge_id)
    if knowledge is None or knowledge.type != 0:
        raise ValueError("必须配置食品文档知识库，不能使用QA知识库")
    params = {"collection_name": [{"key": knowledge_id, "label": "food"}], "user_name": "admin",
              "_is_check_auth": True, "search_kwargs": {"k": top_k}}
    retriever = instantiate_vectorstore(node_type="MilvusWithPermissionCheck", class_object=MilvusWithPermissionCheck, params=params)
    store = retriever.vectorstore
    queries = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str) or not item["name"].strip():
            raise ValueError("逐菜检索问题不能为空")
        preparation = item.get("preparation") or ""
        if not isinstance(preparation, str):
            raise ValueError("逐菜检索制作状态无效")
        query = item["name"].strip() + ("，" + preparation.strip() if preparation.strip() else "")
        queries.append(query)
    # The v1.3.1 string-search wrapper embeds each query twice. Its vector
    # entrypoint already embeds with the selected collection model and applies
    # the same permission/partition filters. Avoid that duplicate call, bound
    # concurrency, and keep map order aligned with the visual food list.
    def search(query):
        return store.similarity_search_with_score_by_vector([], query=query, k=top_k, timeout=20)
    unique = list(dict.fromkeys(queries))
    with ThreadPoolExecutor(max_workers=min(4, len(unique))) as executor:
        results = dict(zip(unique, executor.map(search, unique)))
    documents = []
    for query in queries:
        rows = []
        for doc, distance in results[query]:
            if isinstance(distance, bool) or not math.isfinite(float(distance)) or float(distance) < -0.000001:
                raise ValueError("知识库返回的检索距离无效")
            score = 1.0 - float(distance)
            if score < score_threshold:
                continue
            metadata = doc.metadata
            if not isinstance(metadata, dict) or str(metadata.get("knowledge_id")) != str(knowledge_id):
                raise ValueError("知识库候选不属于指定食品知识库")
            extra = json.loads(metadata.get("extra", ""))
            if not isinstance(extra, dict) or extra.get("document_format") != "nutritionist_food_document_v1" or not isinstance(extra.get("record_json"), str):
                raise ValueError("文档候选缺少原始食品记录元数据")
            record = json.loads(extra["record_json"])
            if not isinstance(record, dict):
                raise ValueError("食品文档原始记录格式无效")
            text = doc.page_content
            if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != extra.get("content_sha256"):
                raise ValueError("食品文档内容与元数据校验不一致")
            if ("数据库唯一食品代码 food_code：" + str(record.get("code"))) not in text.splitlines():
                raise ValueError("食品文档编码与原始记录不一致")
            if type(metadata.get("file_id")) is not int or metadata["file_id"] <= 0 or type(metadata.get("chunk_index")) is not int or metadata["chunk_index"] < 0:
                raise ValueError("食品文档缺少文件或分块标识")
            raw = json.dumps({"record": record, "snapshot_id": extra.get("snapshot_id"), "record_sha256": extra.get("record_sha256")}, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            rows.append({"raw_record": raw, "score": score, "file_id": metadata["file_id"],
                         "chunk_index": metadata["chunk_index"], "document_name": metadata.get("source", ""),
                         "content_sha256": extra["content_sha256"]})
        rows.sort(key=lambda row: row["score"], reverse=True)
        documents.append(rows[:top_k])
    return {"documents": documents}
'''


COLLECT_EVIDENCE_CODE = '''import json
import hashlib
import re
import math

def main(items, documents, knowledge_id, snapshot_id):
    if not isinstance(items, list) or not isinstance(documents, list) or len(items) != len(documents) or len(items) > 8:
        raise ValueError("检索结果数量无效")
    evidence_items = []
    for index, item in enumerate(items):
        retrieved = documents[index]
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
            raw = match.get("raw_record")
            score = match.get("score")
            if not isinstance(raw, str) or len(raw) > 100000:
                raise ValueError("知识库食品记录格式无效")
            try:
                answer = json.loads(raw)
            except (TypeError, ValueError):
                raise ValueError("知识库元数据必须为食品记录JSON")
            if not isinstance(answer, dict) or not isinstance(answer.get("record"), dict):
                raise ValueError("知识库元数据缺少record")
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
                             "record_sha256": record_hash, "source": "bisheng_document", "raw_record": raw,
                             "retrieval_score": score,
                             **{key: match[key] for key in ("file_id", "chunk_index", "document_name", "content_sha256") if key in match}})
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
        # BiSheng 1.3.1 persists the output event in a MySQL TEXT column.
        # Full document records stay in the knowledge/evidence step. The H5 reads
        # nutrition and provenance from its live DB, so return only identities
        # and evidence fingerprints rather than duplicating complete records.
        row = {key: original[key] for key in ("name", "preparation", "estimated_grams") if key in original}
        row["food_code"] = code
        row["candidates"] = [
            {key: candidate[key] for key in ("food_code", "name", "preparation", "basis_g") if key in candidate}
            for candidate in original["candidates"]
        ]
        row["retrieval_evidence"] = [
            {key: entry[key] for key in ("food_code", "knowledge_id", "snapshot_id", "record_sha256", "source", "file_id", "chunk_index", "document_name", "content_sha256") if key in entry}
            for entry in original["retrieval_evidence"]
        ]
        result["items"].append(row)
    message = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    if len(json.dumps({"msg": message}, ensure_ascii=True).encode("utf-8")) > 60000:
        raise ValueError("识别结果超过工作流输出容量，请减少单张图片中的食品数量")
    return {"result": message}
'''


def _fast_finalize_code():
    """Embed the same pure matcher used by the API in a native Code node.

    BiSheng executes top-level functions with separate global/local maps. Nest
    the pure module inside main so its helpers share a real Python closure.
    No model is needed to choose between names/aliases/preparations already
    checked again by the API. Keep the old finalizer for explicit rollback.
    """
    root = Path(__file__).resolve().parents[1] / 'backend' / 'app'
    source = (root / 'recognition_matching.py').read_text(encoding='utf-8')
    parts = [ast.get_source_segment(source, node) for node in ast.parse(source).body
             if isinstance(node, (ast.Assign, ast.FunctionDef))]
    food = (root / 'food_catalog.py').read_text(encoding='utf-8')
    normalize = next(ast.get_source_segment(food, node) for node in ast.parse(food).body
                     if isinstance(node, ast.FunctionDef) and node.name == 'normalize_name')
    finalizer = FINALIZE_CODE.replace('import json\n', '', 1).replace('def main(evidence, selection):', 'def finish(evidence, selection):', 1)
    body = '\n\n'.join([normalize, *parts, finalizer])
    return ('def main(evidence):\n'
            '    import json\n    import re\n    import unicodedata\n    from copy import deepcopy\n'
            + textwrap.indent(body, '    ') + '\n'
            '    original = json.loads(evidence)\n'
            '    catalog = {c["food_code"]: c for row in original["items"] for c in row["candidates"]}\n'
            '    resolved = resolve_recognized_items(original["items"], list(catalog.values()))\n'
            '    selected = {"items": [{"index": i, "food_code": row["food_code"]} for i, row in enumerate(resolved)]}\n'
            '    return finish(evidence, json.dumps(selected, ensure_ascii=False))\n')


FAST_FINALIZE_CODE = _fast_finalize_code()


def _param(key, value, kind="var", **extra):
    # These are editor fields, even though the execution API only needs values.
    # v1.3.1's OutputForm reads options.map unconditionally; its slider also
    # requires bounds. Omitting them produces a runnable but unopenable flow.
    labels = {
        "guide_word": "开场白", "guide_question": "引导问题", "chat_history": "历史消息条数",
        "preset_question": "预置问题列表", "form_input": "上传餐食照片",
        "model_id": "模型", "temperature": "温度", "system_prompt": "系统提示词",
        "user_prompt": "用户提示词", "image_prompt": "图片变量",
        "output_user": "将输出结果展示在会话中", "output": "输出变量",
        "code_input": "输入参数", "code": "执行代码", "code_output": "输出参数",
        "message": "消息内容", "output_result": "交互类型",
    }
    metadata = {"label": labels.get(key, key)}
    if kind == "output_form":
        metadata.update(options=[], **{"global": "value.type=input"})
    elif kind == "slide":
        metadata.update(scope=[0, 2], step=0.1)
    elif kind == "var" and key == "output":
        metadata["global"] = "code:value.map(el => ({ label: el.label, value: el.key }))"
    return {"key": key, "value": value, "type": kind, **metadata, **extra}


def _node(node_id, kind, name, params, x, y, *, version=1, tab=None):
    data = {"id": node_id, "type": kind, "name": name, "description": name,
            "v": str(version), "group_params": [{"name": "配置", "params": params}]}
    if tab:
        label = {"single": "单次运行", "form_input": "表单输入"}.get(tab, tab)
        data["tab"] = {"value": tab, "options": [{"label": label, "key": tab}]}
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
                   *, snapshot_id: str, max_items: int = 8, score_threshold: float = 0.1,
                   name: str = "食光餐食识别与食品热量检索") -> dict:
    """Return the POST /api/v1/workflow/create body, initially offline.

    Import document batches from backend.app.knowledge_export into a type=0
    document KB first. The workflow does not create/import a KB.
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
        _param("output_user", False, "switch"),
        _param("output", [{"key": "output", "label": "模型输出"}], "var"),
    ], 800, 0, version=2, tab="single")
    parse = _code_node("code_foods", "校验视觉输出并逐菜检索", PARSE_VISION_CODE,
                       [_ref("vision", "llm_vision.output"), _literal("max_items", max_items)],
                       [("items", "list")], 1200, 0)
    nodes = [start, input_node, vision, parse]
    nodes.append(_code_node("code_retrieve", "检索食品文档库（前8候选）", RETRIEVE_DOCUMENT_CODE,
                           [_ref("items", "code_foods.items"), _literal("knowledge_id", knowledge_id),
                            _literal("score_threshold", score_threshold), _literal("top_k", 8)],
                           [("documents", "list")], 1600, 0))
    nodes[-1]["data"]["description"] = f"文档知识库 ID：{knowledge_id}；每道菜按名称和做法向量检索；阈值 {score_threshold}；最多8条；校验食品编码、原文和快照。"
    nodes.append(_code_node("code_evidence", "校验目录并保留检索证据", COLLECT_EVIDENCE_CODE,
                           [_ref("items", "code_foods.items"), _ref("documents", "code_retrieve.documents"),
                            _literal("knowledge_id", knowledge_id), _literal("snapshot_id", snapshot_id)],
                           [("evidence_json", "str"), ("matching_json", "str")], 2400, 0))
    # Retain the legacy model definition only in source history. Candidate
    # matching now uses the same deterministic identity rules as the API.
    nodes.append(_code_node("code_result", "匹配食品编码（名称、别名与做法）", FAST_FINALIZE_CODE,
                           [_ref("evidence", "code_evidence.evidence_json")],
                           [("result", "str")], 2800, 0))
    nodes.append(_node("output_food", "output", "返回食品编码与热量检索结果", [
        _param("message", {"msg": "{{#code_result.result#}}", "files": []}, "var_textarea_file"),
        _param("output_result", {"type": "", "value": ""}, "output_form"),
    ], 3600, 0, version=2))
    nodes.append(_node("end_food", "end", "结束", [], 4000, 0))

    # The native code-input widget displays label independently of value. Keep
    # the runtime reference intact while making its source visible to editors.
    names = {node["id"]: node["data"]["name"] for node in nodes}
    for node in nodes:
        for group in node["data"]["group_params"]:
            for param in group["params"]:
                if param["type"] == "code_input":
                    for field in param["value"]:
                        if field["type"] == "ref":
                            source, _, variable = field["value"].partition(".")
                            field["label"] = names[source] + "/" + variable

    pairs = [("start_food", "input_meal"), ("input_meal", "llm_vision"), ("llm_vision", "code_foods"),
             ("code_foods", "code_retrieve"), ("code_retrieve", "code_evidence")]
    pairs.extend([("code_evidence", "code_result"), ("code_result", "output_food"), ("output_food", "end_food")])
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
    parser.add_argument("--score-threshold", type=float, default=0.1)
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
