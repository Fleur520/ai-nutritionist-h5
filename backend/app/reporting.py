"""BiSheng 1.3.1 /api/v2/workflow/invoke adapter for text nutrition reports.

Reference: dataelement/bisheng tag v1.3.1, api/v2/workflow.py.
This API initially emits an `input` event for input nodes; send the data
back with the SAME session_id, then read output_msg / close events.
"""
import json
import logging
import uuid

import httpx
from fastapi import HTTPException

from .config import get_settings

log = logging.getLogger(__name__)


def build_report_context(summary: dict, profile: dict, days: int) -> dict:
    return {
        'period_days': days,
        'nutrition_summary': summary,
        'profile': {key: profile.get(key) for key in ('age', 'height_cm', 'weight_kg', 'goal')},
        'instructions': ('生成普通成年人饮食记录分析与可执行生活方式建议。'
                         '实际能量和营养素以 nutrition_summary 的结构化数据为准。'
                         '如果记录天数少或没有录入，请明确指出数据不足。'
                         '不要诊断疾病，不要编造记录或补全缺失数据。'),
    }


def _events(body: dict) -> tuple[str, list]:
    """Parse v1.3.1 stream=false response: {code,data:{session_id,events:[...]}}."""
    data = body.get('data')
    if not isinstance(data, dict) or not isinstance(data.get('events'), list):
        raise ValueError('BiSheng response has no data.events')
    return str(data.get('session_id') or ''), data['events']


def _input_values(event: dict, context: dict) -> dict:
    """Map the actual input node schema keys; unknown keys get serialized context."""
    schema = event.get('input_schema') or {}
    fields = schema.get('value') or []
    data_json = json.dumps(context, ensure_ascii=False)
    values = {
        'report_context': data_json, 'query': data_json, 'input': data_json,
        'summary': json.dumps(context['nutrition_summary'], ensure_ascii=False),
        'nutrition_summary': json.dumps(context['nutrition_summary'], ensure_ascii=False),
        'profile': json.dumps(context['profile'], ensure_ascii=False),
        'period_days': str(context['period_days']),
    }
    if fields:
        mapped = {}
        for field in fields:
            key = field.get('key')
            if not key:
                continue
            mapped[key] = values.get(key, data_json)
        return mapped
    # Certain workflow input nodes publish their `input_type` without fields.
    return {get_settings().bisheng_report_input_key: data_json}


def _output_text(event: dict) -> str:
    schema = event.get('output_schema') or {}
    value = schema.get('message')
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return str(value.get('text') or value.get('content') or '')
    return ''


async def generate_report(summary: dict, profile: dict, days: int) -> str:
    s = get_settings()
    if s.demo_mode:
        kcal = summary['totals']['kcal']
        return (f'【演示健康报告｜近{days}天】\n\n'
                f'已记录食物能量合计约 {kcal:.0f} kcal。当前为演示模式，'
                '正式环境将通过 BiSheng 1.3.1 工作流结合 RAG 生成报告。\n\n'
                '建议优先增加饮食记录完整度，并由可信数据库计算营养摄入。')
    if not s.bisheng_report_url or not s.bisheng_report_workflow_id:
        raise HTTPException(503, '请配置 BISHENG_REPORT_URL 和 BISHENG_REPORT_WORKFLOW_ID')
    try:
        workflow_id = str(uuid.UUID(s.bisheng_report_workflow_id))
    except ValueError as exc:
        raise HTTPException(503, 'BiSheng 工作流 ID 应为 UUID') from exc

    context = build_report_context(summary, profile, days)
    payload = {'workflow_id': workflow_id, 'stream': False}
    headers = {}
    if s.bisheng_report_api_key:
        headers['Authorization'] = f'Bearer {s.bisheng_report_api_key}'
    session_id = ''
    output = []
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=8)) as client:
            # Initial invoke: the workflow emits an input node request.
            for round_no in range(4):
                result = await client.post(s.bisheng_report_url, json=payload, headers=headers)
                result.raise_for_status()
                response = result.json()
                if response.get('code') not in (None, 0, 200):
                    raise ValueError('BiSheng returned non-success code')
                sid, events = _events(response)
                if sid:
                    session_id = sid
                pending_inputs = []
                for event in events:
                    if not isinstance(event, dict):
                        continue
                    kind = event.get('event')
                    if kind in ('output_msg', 'output_with_input_msg', 'output_with_choose_msg'):
                        value = _output_text(event)
                        if value:
                            output.append(value)
                    if kind == 'error':
                        raise ValueError('BiSheng workflow returned error event')
                    if kind == 'input':
                        pending_inputs.append(event)
                if not pending_inputs:
                    break
                if not session_id:
                    raise ValueError('BiSheng did not return session_id')
                current = pending_inputs[-1]
                payload = {
                    'workflow_id': workflow_id, 'stream': False,
                    'session_id': session_id, 'input': _input_values(current, context)
                }
                msg_id = current.get('message_id')
                if msg_id is not None and str(msg_id).isdigit():
                    payload['message_id'] = int(msg_id)
            else:
                raise ValueError('BiSheng requires too many input rounds')
    except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
        log.warning('BiSheng 1.3.1 report failed: %s', type(exc).__name__)
        raise HTTPException(502, 'BiSheng 报告工作流执行失败，请检查工作流 ID、输入节点和发布配置') from exc
    report = '\n\n'.join(output).strip()
    if not report:
        raise HTTPException(502, 'BiSheng 工作流未返回文字报告；请配置输出节点输出文字')
    return report[:30000]
