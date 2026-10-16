export interface Food {code:string;name:string;kcal:number;protein:number;fat:number;carbs:number;category?:string;preparation?:string;aliases?:string[];source_type?:string;source_model?:string;batch_id?:string;basis_g?:number;verified?:boolean}
export interface MealItem {id:string;food_code:string;grams:number;kcal:number;protein:number;fat:number;carbs:number;name:string}
export interface Meal {id:string;meal_type:string;eaten_at:string;image_id:string|null;items:MealItem[]}
export interface Summary {days:number;daily:{day:string;kcal:number;protein:number;fat:number;carbs:number}[];totals:{kcal:number;protein:number;fat:number;carbs:number}}
export interface Profile {user_id:string;name:string;age:number|null;height_cm:number|null;weight_kg:number|null;goal:string}
export interface NutritionReport {id:string;days:number;content:string;source:string;summary:Summary&{recorded_days:number}}
export interface ReportMeta {id:string;days:number;source:string;created_at:string}
export interface Recognized {name:string;estimated_grams:number;food_code:string|null}

export async function api<T>(path:string, init:RequestInit={}):Promise<T> {
  const response = await fetch('/api'+path,{credentials:'include',...init,headers:{...(init.body instanceof FormData?{}:{'Content-Type':'application/json'}),...(init.headers||{})}})
  if (!response.ok) {
    const data=await response.json().catch(()=>({}))
    throw new Error(data.detail || `请求失败 (${response.status})`)
  }
  return response.json() as Promise<T>
}
export const jsonBody=(v:unknown)=>JSON.stringify(v)

export async function streamMessage(message:string,threadId:string,onDelta:(s:string)=>void):Promise<void> {
  const response=await fetch('/api/chat/stream',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},body:jsonBody({message,thread_id:threadId})})
  if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.detail || 'AI 服务暂时不可用')}
  if(!response.body)throw new Error('浏览器不支持流式响应')
  const reader=response.body.getReader()
  const decoder=new TextDecoder()
  let pending=''
  let finished=false
  while(!finished) {
    const {value,done}=await reader.read()
    if(done)break
    pending+=decoder.decode(value,{stream:true});pending=pending.replace(/\r\n/g,'\n')
    let index=-1
    while((index=pending.indexOf('\n\n'))!==-1){
      const block=pending.slice(0,index);pending=pending.slice(index+2)
      let type='message',raw=''
      for(const line of block.split('\n')){
        if(line.startsWith('event:'))type=line.slice(6).trim()
        if(line.startsWith('data:'))raw+=line.slice(5).trim()
      }
      if(!raw)continue
      const data=JSON.parse(raw)
      if(type==='delta')onDelta(data.content||'')
      if(type==='error')throw new Error(data.message||'AI 响应失败')
      if(type==='done'){finished=true;break}
    }
  }
  if(!finished)throw new Error('AI 流式输出中断，请重试')
}
