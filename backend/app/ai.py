"""Qwen OpenAI-compatible chat streaming and multimodal food recognition.

General consultations intentionally do NOT use the BiSheng Workflow.
"""
import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import AsyncIterator

import httpx
from fastapi import HTTPException

from .config import get_settings

log = logging.getLogger(__name__)
DEMO_FOODS = [
    {'name': '米饭', 'estimated_grams': 150, 'food_code': 'rice'},
    {'name': '鸡胸肉', 'estimated_grams': 120, 'food_code': 'chicken'},
    {'name': '西兰花', 'estimated_grams': 100, 'food_code': 'broccoli'},
]

SYSTEM_PROMPT = """你是“食光”AI营养健康助手，主要服务普通成年人。
提供饮食结构、日常营养与健康生活方式的一般科普。根据用户提供的事实给出可执行、不过度承诺的建议。
不能虚构用户饮食记录、食物热量或个体营养目标。食物能量与营养素需以用户确认后的数据库计算结果为准。
不提供疾病诊断、治疗建议或药物剂量调整。面对严重不适、孕期/儿童、饮食失调或其他高风险情形，应建议咨询专业医务人员。
简洁、自然地用中文回答，必要时明确不确定性。"""


def _auth_headers(key: str) -> dict:
    return {'Authorization': f'Bearer {key or "EMPTY"}'}


async def chat_chunks(message: str, history: list[dict], profile: dict) -> AsyncIterator[str]:
    """Proxy OpenAI-style SSE. Caller stores the finished answer."""
    s = get_settings()
    if s.demo_mode:
        reply = '【演示模式】均衡饮食可以优先关注食材多样化、蛋白质来源和蔬菜摄入。这里尚未连接真实大模型。'
        for i in range(0, len(reply), 12):
            yield reply[i:i+12]
            await asyncio.sleep(0.02)
        return
    if not s.vllm_chat_completions_url:
        raise HTTPException(503, '尚未配置 VLLM_CHAT_COMPLETIONS_URL')
    profile_safe = {k: profile.get(k) for k in ('age', 'height_cm', 'weight_kg', 'goal')}
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT + '\n用户档案（可为空）：' + json.dumps(profile_safe, ensure_ascii=False)}]
    messages.extend({'role': x['role'], 'content': x['content']} for x in history[-12:] if x['role'] in ('user', 'assistant'))
    messages.append({'role': 'user', 'content': message})
    payload = {'model': s.vllm_model, 'messages': messages, 'stream': True,
               'temperature': 0.5, 'max_tokens': s.vllm_max_tokens}
    async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=8, read=160)) as client:
        async with client.stream('POST', s.vllm_chat_completions_url, json=payload,
                                 headers=_auth_headers(s.vllm_api_key)) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.startswith('data:'):
                    continue
                value = line[5:].strip()
                if value == '[DONE]':
                    return
                if not value:
                    continue
                try:
                    event = json.loads(value)
                    if event.get('error'):
                        raise ValueError('model stream error')
                    delta = event.get('choices', [{}])[0].get('delta', {}).get('content')
                    if isinstance(delta, str) and delta:
                        yield delta
                except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
                    log.warning('Unexpected vLLM stream frame: %s', type(exc).__name__)


async def recognize_image(path: Path, mime: str) -> list[dict]:
    s = get_settings()
    if s.demo_mode:
        return DEMO_FOODS
    url = s.vllm_vision_url or s.vllm_chat_completions_url
    if not url:
        raise HTTPException(503, '尚未配置多模态模型 VLLM_VISION_URL')
    img = base64.b64encode(path.read_bytes()).decode('ascii')
    prompt = ('识别图中的食物。只输出有效JSON对象：'
              '{"items":[{"name":"食物名称","estimated_grams":120}]}。'
              '最多8项；无法确定食物时 items 为空数组。重量只是粗略估计，'
              '用户必须人工确认。不要生成热量或营养素。')
    payload = {'model': s.vllm_vision_model or s.vllm_model,
               'messages': [{'role': 'user', 'content': [
                   {'type': 'text', 'text': prompt},
                   {'type': 'image_url', 'image_url': {'url': f'data:{mime};base64,{img}'}}
               ]}], 'temperature': 0, 'max_tokens': s.vllm_vision_max_tokens,
               'chat_template_kwargs': {'enable_thinking': s.vllm_vision_enable_thinking},
               'response_format': {'type': 'json_object'}}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(100, connect=8)) as client:
            response = await client.post(url, headers=_auth_headers(s.vllm_vision_api_key or s.vllm_api_key), json=payload)
            response.raise_for_status()
            body = response.json()
            choice = body['choices'][0]
            if choice.get('finish_reason') == 'length':
                log.warning('Multimodal output truncated at max_tokens=%s', s.vllm_vision_max_tokens)
                raise HTTPException(502, '识别结果未完整返回，请重试或手动记录')
            content = choice['message'].get('content')
        if isinstance(content, list):
            content = ''.join(x.get('text', '') for x in content if isinstance(x, dict))
        if not isinstance(content, str) or not content.strip():
            log.warning('Multimodal response has no text content; finish_reason=%s', choice.get('finish_reason'))
            raise HTTPException(502, '模型未返回有效识别结果，请重试或手动记录')
        result = json.loads(content)
        items = result['items']
        if not isinstance(items, list):
            raise ValueError('items should be a list')
        return [{'name': str(x.get('name', '未知食物'))[:80],
                 'estimated_grams': max(5, min(3000, float(x.get('estimated_grams') or 100))),
                 'food_code': None} for x in items[:8] if isinstance(x, dict)]
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        log.warning('Multimodal request failed: %s', type(exc).__name__)
        raise HTTPException(502, '多模态识别失败，请重试或手动记录') from exc
