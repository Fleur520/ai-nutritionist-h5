"""BiSheng 1.3.1 protocol tests without any real BiSheng server."""
import asyncio
from types import SimpleNamespace
from app import reporting


def test_bisheng_131_input_roundtrip(monkeypatch):
    calls=[]
    class FakeResponse:
        def __init__(self,body):self.body=body
        def raise_for_status(self):pass
        def json(self):return self.body

    class FakeClient:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):return False
        async def post(self,url,json,headers):
            calls.append({'url':url,'data':json,'headers':headers})
            if len(calls)==1:
                return FakeResponse({'code':200,'data':{'session_id':'abc_async_task_id','events':[
                    {'event':'input','message_id':'123','input_schema':{'input_type':'dialog_input','value':[
                        {'key':'report_context','type':'text','required':True}]}}
                ]}})
            return FakeResponse({'code':200,'data':{'session_id':'abc_async_task_id','events':[
                {'event':'output_msg','output_schema':{'message':'本周记录相对完整，可继续均衡饮食。'}},
                {'event':'close'}
            ]}})

    monkeypatch.setattr(reporting.httpx, 'AsyncClient', FakeClient)
    monkeypatch.setattr(reporting,'get_settings',lambda:SimpleNamespace(
        demo_mode=False,
        bisheng_report_url='http://test-bisheng:7860/api/v2/workflow/invoke',
        bisheng_report_workflow_id='c4132001-7788-4001-a123-555566667777',
        bisheng_report_api_key='',bisheng_report_input_key='report_context'
    ))
    summary={'totals':{'kcal':500},'daily':[], 'recorded_days':1}
    result=asyncio.run(reporting.generate_report(summary,{'goal':'balanced'},7))
    assert '本周记录' in result
    assert len(calls)==2
    assert calls[0]['data']['stream'] is False
    assert calls[1]['data']['session_id']=='abc_async_task_id'
    assert calls[1]['data']['message_id']==123
    assert 'nutrition_summary' in calls[1]['data']['input']['report_context']
    assert calls[1]['url'].endswith('/api/v2/workflow/invoke')


def test_bisheng_input_field_mapping():
    context={'period_days':30,'profile':{'goal':'balanced'},'nutrition_summary':{'totals':{'kcal':3200}}}
    event={'input_schema':{'value':[{'key':'period_days'}, {'key':'summary'}, {'key':'profile'}]}}
    result=reporting._input_values(event,context)
    assert result['period_days']=='30'
    assert '3200' in result['summary']
    assert 'balanced' in result['profile']
