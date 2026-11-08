"""Add per-100g visual nutrition estimates without another model invocation."""

LEGACY_SCHEMA = '{"items":[{"name":"菜名","estimated_grams":150,"preparation":"蒸熟"}]}'
NUTRITION_SCHEMA = '{"items":[{"name":"菜名","estimated_grams":150,"preparation":"蒸熟","kcal":100,"protein":5,"fat":4,"carbs":11}]}'


def enable_model_nutrition(body, model_id):
    nodes = {node['id']: node for node in body['data']['nodes']}

    def params(node_id):
        return {p['key']: p for group in nodes[node_id]['data']['group_params'] for p in group['params']}

    vision = params('llm_vision')
    prompt = vision['system_prompt'] if nodes['llm_vision']['data']['type'] == 'llm' else next(
        field for field in vision['code_input']['value'] if field['key'] == 'system_prompt')
    if prompt['value'].count(LEGACY_SCHEMA) != 1:
        raise ValueError('Expected the original vision nutrition schema')
    prompt['value'] = prompt['value'].replace('不要输出热量或食品编码。',
        '结合可见份量、做法和用油估算营养，不输出食品编码。').replace(LEGACY_SCHEMA, NUTRITION_SCHEMA)
    prompt['value'] += ('kcal、protein、fat、carbs分别为每100克可食部的千卡、蛋白质克、脂肪克、碳水克，'
                        '不是整份营养；所有数值为有限非负数，热量不超过930，三大营养素合计不超过100克。'
                        '热量应与4×蛋白质+9×脂肪+4×碳水大致一致，均为未经核验的照片估算。')
    parser = params('code_foods')['code']
    anchor = '        result["items"].append(clean)'
    if parser['value'].count(anchor) != 1:
        raise ValueError('Expected original food parser')
    parser['value'] = parser['value'].replace(anchor, '''        nutrition = {"basis_g": 100}
        for key in ("kcal", "protein", "fat", "carbs"):
            number = item.get(key)
            if type(number) not in (int, float) or not math.isfinite(number) or not 0 <= number <= (930 if key == "kcal" else 100):
                raise ValueError("模型营养估算无效")
            nutrition[key] = round(number, 2)
        if nutrition["protein"] + nutrition["fat"] + nutrition["carbs"] > 103:
            raise ValueError("模型营养素超过100克")
        clean.update(nutrition=nutrition, source_type="ai_estimate", verified=False,
                     source_model="bisheng:model:''' + str(int(model_id)) + '''")
''' + anchor)
    finalizer = params('code_result')['code']
    anchor = '("name", "preparation", "estimated_grams")'
    if finalizer['value'].count(anchor) != 1:
        raise ValueError('Expected original finalizer')
    finalizer['value'] = finalizer['value'].replace(anchor,
        '("name", "preparation", "estimated_grams", "nutrition", "source_model", "source_type", "verified")')
    return body
