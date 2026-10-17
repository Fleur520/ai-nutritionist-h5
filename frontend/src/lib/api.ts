export interface Food {code:string;name:string;kcal:number;protein:number;fat:number;carbs:number;category?:string;preparation?:string;aliases?:string[];source_type?:string;source_model?:string;batch_id?:string;basis_g?:number;verified?:boolean}
export interface MealItem {id:string;food_code:string;grams:number;kcal:number;protein:number;fat:number;carbs:number;name:string}
export interface Meal {id:string;meal_type:string;eaten_at:string;image_id:string|null;items:MealItem[]}
export interface Summary {days:number;daily:{day:string;kcal:number;protein:number;fat:number;carbs:number}[];totals:{kcal:number;protein:number;fat:number;carbs:number}}
export interface Profile {user_id:string;name:string;age:number|null;height_cm:number|null;weight_kg:number|null;goal:string}
export interface NutritionReport {id:string;days:number;content:string;source:string;summary:Summary&{recorded_days:number}}
export interface ReportMeta {id:string;days:number;source:string;created_at:string}
export interface Recognized {name:string;estimated_grams:number;food_code:string|null;preparation?:string;match_status?:string;matched_name?:string|null;match_note?:string;candidates?:Food[]}

const fieldNames:Record<string,string>={email:'邮箱',password:'密码',name:'昵称',age:'年龄',height_cm:'身高',weight_kg:'体重',goal:'健康目标',grams:'重量',food_code:'食物',message:'消息',items:'食物记录'}
function readableError(data:unknown,status:number):string {
  const detail=data&&typeof data==='object'?(data as {detail?:unknown}).detail:undefined
  if(typeof detail==='string'&&detail.trim())return detail
  if(Array.isArray(detail)){
    const messages=detail.slice(0,3).map(issue=>{
      const field=Array.isArray(issue?.loc)?issue.loc.at(-1):''
      const label=fieldNames[field]||'输入内容'
      const type=String(issue?.type||'')
      let message='请检查填写的内容'
      if(type.includes('parsing')||type.includes('type'))message='请填写有效的'+(['age','height_cm','weight_kg','grams'].includes(field)?'数字':'内容')
      else if(type==='greater_than_equal')message='不能小于 '+issue.ctx?.ge
      else if(type==='less_than_equal')message='不能大于 '+issue.ctx?.le
      else if(type==='string_too_long')message='最多填写 '+issue.ctx?.max_length+' 个字符'
      else if(type==='string_too_short')message='至少填写 '+issue.ctx?.min_length+' 个字符'
      else if(type==='missing')message='请补充填写'
      return label+'：'+message
    })
    if(messages.length)return [...new Set(messages)].join('；')
  }
  if(status===401)return '登录状态已过期，请重新登录'
  if(status===429)return '请求有些频繁，请稍后再试'
  if(status>=500)return '服务暂时没有响应，请稍后重试'
  return '请求没有完成，请检查填写内容后重试'
}
async function responseError(response:Response){return new Error(readableError(await response.json().catch(()=>null),response.status))}
export async function api<T>(path:string, init:RequestInit={}):Promise<T> {
  const headers=new Headers(init.headers)
  if(!(init.body instanceof FormData)&&!headers.has('Content-Type'))headers.set('Content-Type','application/json')
  const response=await fetch('/api'+path,{credentials:'include',...init,headers})
  if(!response.ok)throw await responseError(response)
  return response.json() as Promise<T>
}
export const jsonBody=(v:unknown)=>JSON.stringify(v)

export async function streamMessage(message:string,threadId:string,onDelta:(s:string)=>void,signal?:AbortSignal):Promise<void> {
  const response=await fetch('/api/chat/stream',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:jsonBody({message,thread_id:threadId}),signal})
  if(!response.ok)throw await responseError(response)
  if(!response.body)throw new Error('浏览器不支持流式响应')
  const reader=response.body.getReader()
  const decoder=new TextDecoder()
  let pending=''
  let finished=false,answer=''
  try{while(!finished) {
    const {value,done}=await reader.read()
    if(done)break
    pending+=decoder.decode(value,{stream:true});pending=pending.replace(/\r\n/g,'\n')
    let index=-1
    while((index=pending.indexOf('\n\n'))!==-1){
      const block=pending.slice(0,index);pending=pending.slice(index+2)
      let type='message'
      const lines:string[]=[]
      for(const line of block.split('\n')){
        if(line.startsWith('event:'))type=line.slice(6).trim()
        if(line.startsWith('data:'))lines.push(line.slice(5).trimStart())
      }
      const raw=lines.join('\n')
      if(!raw)continue
      let data
      try{data=JSON.parse(raw)}catch{throw new Error('AI 回复格式异常，请重试')}
      if(!data||typeof data!=='object'||Array.isArray(data))throw new Error('AI 回复格式异常，请重试')
      if(type==='delta'&&typeof data.content==='string'){answer+=data.content;onDelta(data.content)}
      if(type==='error')throw new Error(typeof data.message==='string'&&data.message.trim()?data.message:'AI 响应失败，请重试')
      if(type==='done'){finished=true;break}
    }
  }}finally{
    await reader.cancel().catch(()=>{})
    reader.releaseLock()
  }
  if(!finished)throw new Error('AI 流式输出中断，请重试')
  if(!answer.trim())throw new Error('AI 暂时没有返回内容，请重试')
}
