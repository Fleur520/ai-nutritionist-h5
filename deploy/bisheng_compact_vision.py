"""Opt-in workflow invocation that keeps photo bytes out of DEBUG node logs.

Only configured ChatOpenAI models are supported. The platform's model loader,
online checks, quota check and status updates remain in use; global platform
logging and model configuration are not modified.
"""


COMPACT_VISION_CODE = '''def main(files, model_id, system_prompt, user_prompt):
    import base64
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    from urllib.request import Request, build_opener, ProxyHandler, HTTPRedirectHandler
    from PIL import Image
    from bisheng.api.services.llm import LLMService
    from bisheng.interface.utils import bisheng_model_limit_check

    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], str):
        raise ValueError("需要一张餐食图片")
    if type(model_id) is not int or model_id <= 0:
        raise ValueError("模型编号无效")
    if not isinstance(system_prompt, str) or not 1 <= len(system_prompt) <= 10000 or not isinstance(user_prompt, str) or not 1 <= len(user_prompt) <= 4000:
        raise ValueError("视觉提示词无效")
    path = Path(files[0])
    with path.open("rb") as image_file:
        raw = image_file.read(5 * 1024 * 1024 + 1)
    if not raw or len(raw) > 5 * 1024 * 1024:
        raise ValueError("图片大小无效")
    with Image.open(path) as image:
        if image.format not in {"JPEG", "PNG", "WEBP", "BMP"} or image.width * image.height > 16000000:
            raise ValueError("图片格式无效")
        mime = Image.MIME[image.format]
        image.verify()

    model = LLMService.get_bisheng_llm(model_id=model_id, temperature=0.1,
                                      params={"stream": False}, cache=False)
    native = model.llm
    if type(native).__name__ != "ChatOpenAI" or getattr(native, "openai_proxy", None) or getattr(native, "default_query", None):
        raise ValueError("此路径需要无代理的OpenAI兼容模型")
    params = dict(native._default_params)
    extra = params.pop("extra_body", {}) or {}
    if not isinstance(extra, dict):
        raise ValueError("模型附加参数无效")
    params.update(extra)
    params["stream"] = False
    # These messages stay local to this call. They are not node parameters,
    # node outputs or arguments passed through SDK DEBUG request logging.
    params["messages"] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt},
            {"type": "image_url", "image_url": {"url": "data:" + mime + ";base64," + base64.b64encode(raw).decode("ascii")}},
        ]},
    ]
    base = native.openai_api_base.rstrip("/")
    location = urlsplit(base)
    if location.scheme not in {"http", "https"} or not location.hostname or location.username or location.password or location.query or location.fragment:
        raise ValueError("模型地址无效")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + native.openai_api_key.get_secret_value()}
    if native.default_headers:
        headers.update(native.default_headers)
    if any(not isinstance(value, str) or "\\r" in value or "\\n" in value for value in headers.values()):
        raise ValueError("模型请求头无效")

    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            raise ValueError("不允许模型重定向")

    request = Request(base + "/chat/completions", data=json.dumps(params, ensure_ascii=False).encode("utf-8"),
                      headers=headers, method="POST")
    # Keep the platform's per-provider call count/limit and online status rules.
    bisheng_model_limit_check(model)
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=12) as response:
            body = response.read(2 * 1024 * 1024 + 1)
        if len(body) > 2 * 1024 * 1024:
            raise ValueError("模型输出过大")
        content = json.loads(body)["choices"][0]["message"]["content"]
        if not isinstance(content, str) or not content.strip():
            raise ValueError("模型输出为空")
        model._update_model_status(0)
    except Exception as error:
        model._update_model_status(1, type(error).__name__)
        raise ValueError("视觉模型调用失败") from None
    return {"output": content}
'''


def enable_compact_vision(body):
    from bisheng_food_workflow import _code_node, _literal, _ref
    nodes = body["data"]["nodes"]
    original = next(node for node in nodes if node["id"] == "llm_vision")
    if original["data"]["type"] != "llm":
        raise ValueError("Expected the generator's original vision node")
    values = {p["key"]: p["value"] for group in original["data"]["group_params"] for p in group["params"]}
    if not isinstance(values["image_prompt"], list) or len(values["image_prompt"]) != 1:
        raise ValueError("Compact vision requires exactly one image reference")
    node = _code_node("llm_vision", "按平台模型配置识别餐图（图片不写入调试日志）", COMPACT_VISION_CODE,
                      [_ref("files", values["image_prompt"][0]), _literal("model_id", values["model_id"]),
                       _literal("system_prompt", values["system_prompt"]), _literal("user_prompt", values["user_prompt"])],
                      [("output", "str")], original["position"]["x"], original["position"]["y"])
    node["data"]["description"] = (f"使用平台模型{values['model_id']}配置、上线检查、调用次数配额及状态更新；"
                                      "仅本流程以非流式HTTP提交图片，图片Base64不进入节点输入输出及SDK调试日志。平台日志与模型配置不变。")
    nodes[nodes.index(original)] = node
    names = {row["id"]: row["data"]["name"] for row in nodes}
    for row in nodes:
        for group in row["data"]["group_params"]:
            for param in group["params"]:
                if param["type"] == "code_input":
                    for field in param["value"]:
                        if field["type"] == "ref":
                            source, _, variable = field["value"].partition(".")
                            field["label"] = names[source] + "/" + variable
    return body
