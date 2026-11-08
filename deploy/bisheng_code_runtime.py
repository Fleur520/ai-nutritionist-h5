"""Opt-in smaller vision output and deferred compilation for food workflows.

BiSheng 1.3.1 CodeParser walks nested function/class definitions and compiles
them again while constructing every graph. A small main wrapper lets Python
compile the trusted generator source once when its node actually runs. No
platform modules, GC settings, shared caches or model settings are modified.
"""
import ast
import hashlib
import json
import keyword


def _params(node):
    return {p['key']: p for group in node['data']['group_params'] for p in group['params']}


def enable_compact_vision_output(body):
    """Keep all three fields; normalize positional output before old validation."""
    nodes = {node['id']: node for node in body['data']['nodes']}
    vision = _params(nodes['llm_vision'])
    if nodes['llm_vision']['data']['type'] == 'llm':
        prompt = vision['system_prompt']
    else:
        prompt = next(p for p in vision['code_input']['value'] if p['key'] == 'system_prompt')
    from bisheng_model_nutrition import LEGACY_SCHEMA, NUTRITION_SCHEMA
    with_nutrition = NUTRITION_SCHEMA in prompt['value']
    old = NUTRITION_SCHEMA if with_nutrition else LEGACY_SCHEMA
    new = ('{"items":[["菜名",150,"蒸熟",100,5,4,11]]}；每个七元素数组依次是名称、克重、preparation、每100克kcal、protein、fat、carbs，顺序固定'
           if with_nutrition else '{"items":[["菜名",150,"蒸熟"]]}；每个三元素数组依次是名称、克重、preparation，顺序固定')
    if prompt['value'].count(old) != 1:
        raise ValueError('Expected the original generated vision schema')
    prompt['value'] = prompt['value'].replace(old, new)
    params = _params(nodes['code_foods'])
    source = params['code']['value']
    arguments = _arguments(params)
    normalize = '''    import json
    text = vision.strip()
    if text.startswith("```"):
        text = text.split("\\n", 1)[1].rsplit("```", 1)[0].strip()
    value = json.loads(text)
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise ValueError("视觉输出items格式无效")
    rows = value["items"]
    if any(not isinstance(row, list) or len(row) != 3 for row in rows):
        raise ValueError("视觉输出必须是名称、克重、做法三元组")
    value["items"] = [dict(zip(("name", "estimated_grams", "preparation"), row)) for row in rows]
    vision = json.dumps(value, ensure_ascii=False)
'''
    if with_nutrition:
        normalize = normalize.replace('len(row) != 3', 'len(row) != 7').replace(
            '名称、克重、做法三元组', '名称、克重、做法与四项每100克营养七元组').replace(
            '("name", "estimated_grams", "preparation")',
            '("name", "estimated_grams", "preparation", "kcal", "protein", "fat", "carbs")')
    params['code']['value'] = ('def main(' + ', '.join(arguments) + '):\n' + normalize
                               + '    namespace = {}\n    exec(' + repr(source) + ', namespace, namespace)\n'
                               + '    return namespace["main"](' + ', '.join(arguments) + ')\n')
    return body


def _arguments(params):
    arguments = [field['key'] for field in params['code_input']['value']]
    if (len(arguments) != len(set(arguments)) or any(
            not isinstance(key, str) or not key.isidentifier() or keyword.iskeyword(key)
            or key == 'namespace' for key in arguments)):
        raise ValueError('Invalid generated code input arguments')
    return arguments


def defer_code_compilation(body):
    """Wrap authored code, preserving IO and source in the workflow JSON.

The source is an immutable Python string literal in generated code. It never
comes from an upload or a request, and the namespace is fresh for every call.
Only large nodes benefit; simple timer nodes retain their readable code.
"""
    for node in body['data']['nodes']:
        if node['data']['type'] != 'code':
            continue
        params = _params(node)
        source = params['code']['value']
        if len(source) < 1500:
            continue
        tree = ast.parse(source)
        if not any(isinstance(n, ast.FunctionDef) and n.name == 'main' for n in tree.body):
            raise ValueError('Generated code must define main')
        arguments = _arguments(params)
        digest = hashlib.sha256(source.encode('utf-8')).hexdigest()
        params['code']['value'] = ('def main(' + ', '.join(arguments) + '):\n'
            + '    # Trusted generator source SHA256: ' + digest + '\n'
            + '    namespace = {}\n    exec(' + repr(source) + ', namespace, namespace)\n'
            + '    return namespace["main"](' + ', '.join(arguments) + ')\n')
    return body
