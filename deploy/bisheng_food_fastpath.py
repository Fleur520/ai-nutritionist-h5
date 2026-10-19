"""Opt-in image-reference input and server-side timings for BiSheng 1.3.1.

The platform upload API still owns the image. Only this workflow's H5 input
avoids OCR/temporary indexing; document retrieval and the native LLM remain.
"""
import re
import textwrap
from urllib.parse import urlsplit


PREPARE_IMAGE_CODE = '''def main(files, image_ref, stamp, allowed_origin, path_prefix):
    import io
    import os
    import time
    import warnings
    from urllib.parse import urlsplit, unquote
    from urllib.request import build_opener, HTTPRedirectHandler, ProxyHandler
    from PIL import Image
    from bisheng.cache.utils import save_download_file

    started = int(time.monotonic() * 1000)
    if files:
        # Native BiSheng file uploads have already been handled by InputNode.
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], str) or not os.path.isfile(files[0]):
            raise ValueError("需要一张餐食图片")
        paths = files
    else:
        if not isinstance(image_ref, str) or not 1 <= len(image_ref) <= 4096:
            raise ValueError("缺少已上传的图片引用")
        parsed = urlsplit(image_ref)
        expected = urlsplit(allowed_origin)
        path = unquote(parsed.path)
        if ((parsed.scheme, parsed.netloc) != (expected.scheme, expected.netloc)
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or not path.startswith(path_prefix) or path.endswith("/")
            or any(part in {".", ".."} for part in path.split("/"))
            or any(c in path for c in ("\\\\", "%", "\\x00", "\\r", "\\n"))
            or not path.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))):
            raise ValueError("图片引用不属于配置的上传存储")

        class NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                raise ValueError("不允许图片下载重定向")

        # Do not inherit worker proxy settings or follow a storage redirect.
        opener = build_opener(ProxyHandler({}), NoRedirect())
        limit = 5 * 1024 * 1024
        with opener.open(image_ref, timeout=8) as response:
            raw = response.read(limit + 1)
        if not raw or len(raw) > limit:
            raise ValueError("图片文件过大或为空")
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"} or image.width * image.height > 16000000:
                    raise ValueError("图片格式或分辨率不支持")
                image.verify()
        # Use the same platform-managed download cache as InputNode. No second
        # temporary file, retention service or platform installation change.
        paths = [save_download_file(raw, "bisheng", path.rsplit("/", 1)[-1])]
    now = int(time.monotonic() * 1000)
    return {"files": paths, "input_ms": started - stamp,
            "image_ms": now - started, "vision_start": now}
'''


def enable_image_reference(body, origin, path_prefix="/tmp-dir/"):
    """Modify a fresh generator body; caller must pin the actual upload origin."""
    from bisheng_food_workflow import _code_node, _literal, _ref

    parsed = urlsplit(origin)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment
            or not origin.isascii() or any(c.isspace() for c in origin)):
        raise ValueError("image reference origin must be one explicit HTTP(S) origin")
    # Keep the configured scope a directory, never an arbitrary URL or root.
    if not isinstance(path_prefix, str) or not re.fullmatch(r"/(?:[A-Za-z0-9_-]+/)+", path_prefix):
        raise ValueError("image reference prefix must be an explicit storage directory")
    graph = body["data"]
    nodes = graph["nodes"]
    by_id = {node["id"]: node for node in nodes}

    def params(node_id):
        return {p["key"]: p for group in by_id[node_id]["data"]["group_params"] for p in group["params"]}

    form = params("input_meal")["form_input"]["value"]
    form[0]["required"] = False
    form.append({"key": "meal_image_ref", "type": "text", "value": "H5已上传图片引用（手动上传时留空）",
                 "required": False, "multiple": False})
    nodes.append(_code_node("clock_start", "开始阶段计时", 'def main():\n    import time\n    return {"stamp": int(time.monotonic() * 1000)}\n',
                            [], [("stamp", "int")], 200, 220))
    nodes.append(_code_node("prepare_image", "读取已上传餐图（免OCR和临时索引）", PREPARE_IMAGE_CODE,
                            [_ref("files", "input_meal.meal_image_files"),
                             _ref("image_ref", "input_meal.meal_image_ref"), _ref("stamp", "clock_start.stamp"),
                             _literal("allowed_origin", origin), _literal("path_prefix", path_prefix)],
                            [("files", "list"), ("input_ms", "int"), ("image_ms", "int"), ("vision_start", "int")], 600, 220))
    nodes[-1]["data"]["description"] = "H5使用平台上传引用，限定存储来源、目录、图片格式与大小；手动上传仍走原文件输入。"
    params("llm_vision")["image_prompt"]["value"] = ["prepare_image.files"]

    def timed(node_id, args, outputs, after):
        p = params(node_id)
        original_args = [i["key"] for i in p["code_input"]["value"]]
        source = p["code"]["value"].replace("def main(", "def original(", 1)
        p["code_input"]["value"].extend(args)
        signature = ", ".join(original_args + [arg["key"] for arg in args])
        p["code"]["value"] = ("def main(" + signature + "):\n    import time, json\n"
                               "    started = int(time.monotonic() * 1000)\n"
                               + textwrap.indent(source, "    ") + "\n    result = original("
                               + ", ".join(original_args) + ")\n" + textwrap.indent(after, "    ")
                               + "\n    return result\n")
        p["code_output"]["value"].extend({"key": key, "type": kind} for key, kind in outputs)

    timed("code_foods", [_ref("vision_start", "prepare_image.vision_start")], [("vision_ms", "int")],
          'result["vision_ms"] = started - vision_start')
    for node_id, key in (("code_retrieve", "retrieval_ms"), ("code_evidence", "evidence_ms")):
        timed(node_id, [], [(key, "int")], f'result["{key}"] = int(time.monotonic() * 1000) - started')
    args = [_ref("stamp", "clock_start.stamp"), _ref("input_ms", "prepare_image.input_ms"),
            _ref("image_ms", "prepare_image.image_ms"), _ref("vision_ms", "code_foods.vision_ms"),
            _ref("retrieval_ms", "code_retrieve.retrieval_ms"), _ref("evidence_ms", "code_evidence.evidence_ms")]
    timed("code_result", args, [], '''value = json.loads(result["result"])
value["timings_ms"] = {"input_and_resume": input_ms, "image": image_ms, "vision": vision_ms,
                      "retrieval": retrieval_ms, "evidence": evidence_ms,
                      "matching": int(time.monotonic() * 1000) - started,
                      "pipeline_total": int(time.monotonic() * 1000) - stamp}
result["result"] = json.dumps(value, ensure_ascii=False, separators=(",", ":"))''')

    graph["edges"] = [edge for edge in graph["edges"] if (edge["source"], edge["target"]) not in {
        ("start_food", "input_meal"), ("input_meal", "llm_vision")}]
    for source, target in (("start_food", "clock_start"), ("clock_start", "input_meal"),
                           ("input_meal", "prepare_image"), ("prepare_image", "llm_vision")):
        graph["edges"].append({"id": source + "-" + target, "source": source, "target": target,
                               "sourceHandle": "right_handle", "targetHandle": "left_handle", "type": "customEdge"})
    names = {node["id"]: node["data"]["name"] for node in nodes}
    for node in nodes:
        for group in node["data"]["group_params"]:
            for param in group["params"]:
                if param["type"] == "code_input":
                    for field in param["value"]:
                        if field["type"] == "ref":
                            source, _, variable = field["value"].partition(".")
                            field["label"] = names[source] + "/" + variable
    return body
