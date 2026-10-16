<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Camera, Check, LoaderCircle, Plus, Trash2, ArrowRight } from 'lucide-vue-next'
import { api, jsonBody, type Food, type Recognized } from '../lib/api'
import FoodPicker from '../components/FoodPicker.vue'
const emit=defineEmits<{go:[value:string]}>()
const fileRef=ref<HTMLInputElement|null>(null), preview=ref(''),imageId=ref(''),busy=ref(false),saving=ref(false),error=ref(''),notice=ref(''),mealType=ref('lunch')
const foods=ref<Food[]>([])
const items=ref<(Recognized & {food_code:string})[]>([])
onMounted(async()=>{
 try{foods.value=await api<Food[]>('/foods')}
 catch{error.value='标准食物库加载失败，请刷新页面后重试'}
})
type ScanItem = (typeof items.value)[number]
function selectedFood(item:ScanItem){return foods.value.find(food=>food.code===item.food_code)}
function validWeight(item:ScanItem){
 const grams=Number(item.estimated_grams)
 return Number.isFinite(grams)&&grams>=5&&grams<=3000
}
function itemEnergy(item:ScanItem):number|null{
 const food=selectedFood(item)
 return food&&validWeight(item)?food.kcal*Number(item.estimated_grams)/100:null
}
function energyText(value:number){return Number(value.toFixed(1)).toString()}
const calculatedCount=computed(()=>items.value.filter(item=>itemEnergy(item)!==null).length)
const total=computed(()=>items.value.reduce((sum,item)=>sum+(itemEnergy(item)??0),0))
const complete=computed(()=>items.value.length>0&&calculatedCount.value===items.value.length)
function add(){items.value.push({name:'手动新增',estimated_grams:100,food_code:''})}
function upload(){fileRef.value?.click()}
async function onFile(e:Event){
 const input=e.target as HTMLInputElement
 const file=input.files?.[0];input.value='';if(!file)return
 if(file.size>5*1024*1024){error.value='图片不能超过 5MB';return}
 preview.value=URL.createObjectURL(file);busy.value=true;error.value='';notice.value='';items.value=[]
 try{
   const form=new FormData();form.append('file',file)
   const result=await api<{id:string}>('/images',{method:'POST',body:form})
   imageId.value=result.id
   const recognized=await api<{items:Recognized[];notice:string}>('/meals/recognize',{method:'POST',body:jsonBody({image_id:imageId.value})})
   items.value=recognized.items.map(x=>({...x,food_code:x.food_code||''}))
   notice.value=recognized.notice
 }catch(e){error.value=e instanceof Error?e.message:'识别失败'}finally{busy.value=false}
}
async function save(){
 if(!complete.value){error.value='请为每项选择食品库条目，并填写 5～3000 克的重量';return}
 saving.value=true;error.value=''
 try{await api('/meals',{method:'POST',body:jsonBody({meal_type:mealType.value,eaten_at:new Date().toISOString(),image_id:imageId.value||null,items:items.value.map(i=>({food_code:i.food_code,grams:i.estimated_grams}))})});emit('go','history')}
 catch(e){error.value=e instanceof Error?e.message:'保存失败'}finally{saving.value=false}
}
</script>
<template><section class="page scan-page"><div class="eyebrow">AI FOOD SCANNER</div><h1 class="page-title">认识你盘中的美好。</h1><p class="page-subtitle">上传食物照片，AI 识别菜品，确认分量后计算营养。</p>
<div class="upload-card" :class="{filled:preview}" @click="upload"><img v-if="preview" :src="preview" alt="餐食预览"/><template v-else><div class="upload-circle"><Camera :size="34"/></div><h3>记录这一餐</h3><p>拍照或从相册选择 · JPG/PNG/WebP</p></template><div class="upload-action">{{preview?'重新选择照片':'选择照片'}} <ArrowRight :size="16"/></div></div>
<input ref="fileRef" class="hidden" type="file" accept="image/png,image/jpeg,image/webp" capture="environment" @change="onFile"/>
<div v-if="busy" class="notice"><LoaderCircle :size="16" class="spinning"/> 正在理解食物，请稍候…</div>
<p v-if="notice" class="notice">{{notice}}</p><p v-if="error" class="error">{{error}}</p>
<div class="section-header"><h2>识别结果</h2><button class="text-action" @click="add"><Plus :size="16"/> 手动添加</button></div>
<div v-if="!items.length" class="empty-state">还没有食物记录，先拍照识别，或手动添加。</div>
<div v-for="(item,index) in items" :key="index" class="food-item">
 <div class="food-head"><strong>{{item.name}}</strong><button class="icon-button" title="删除" @click="items.splice(index,1)"><Trash2 :size="16"/></button></div>
 <FoodPicker v-model="item.food_code" :foods="foods"/>
 <div class="weight-row"><label>重量（克）<input type="number" v-model.number="item.estimated_grams" min="5" max="3000" step="5"/></label>
 </div>
 <p class="food-energy" :class="{pending:itemEnergy(item)===null}" aria-live="polite">
  <template v-if="!selectedFood(item)">尚未选择食品库条目，暂未计入能量。</template>
  <template v-else-if="!validWeight(item)">请填写 5～3000 克的重量，暂未计入能量。</template>
  <template v-else>{{selectedFood(item)?.kcal}} kcal/100g × {{item.estimated_grams}}g ÷ 100 = <strong>{{energyText(itemEnergy(item)??0)}} kcal</strong></template>
 </p>
 <p v-if="selectedFood(item)" class="food-source">{{selectedFood(item)?.source_type==='ai_estimate'?'AI 估算 · 未核验':'原有演示数据'}} · 每 100 克可食部<span v-if="selectedFood(item)?.preparation"> · {{selectedFood(item)?.preparation}}</span></p>
</div>
<div class="result-bottom">
 <label class="form-label">餐别<select v-model="mealType"><option value="breakfast">早餐</option><option value="lunch">午餐</option><option value="dinner">晚餐</option><option value="snack">加餐</option></select></label>
 <div class="sum-line" aria-live="polite"><span>{{items.length&&!complete?'已匹配食物小计':'本餐估算能量'}}</span><strong>{{energyText(total)}} <small>kcal</small></strong></div>
 <p class="energy-rule">计算方式：每项所选食物每 100 克的能量 × 重量 ÷ 100，再相加。修改选项或重量后实时更新。</p>
 <p v-if="items.length&&!complete" class="energy-warning" role="status">已计入 {{calculatedCount}}/{{items.length}} 项，当前不是整餐能量。请补齐食品库条目和有效重量后保存。</p>
 <button class="primary-button" @click="save" :disabled="saving||busy||!complete"><Check :size="17"/>{{saving?'保存中…':'确认并保存饮食记录'}}</button>
</div>
<p class="microcopy">食品库含 AI 生成的营养估算，尚未经过实验核验。请选择对应的食物和生熟状态；复合菜的配料、用油会影响实际数值。</p></section></template>
<style scoped>
.food-energy{font-size:11px;line-height:1.8;color:#51765b;margin:12px 0 0;overflow-wrap:anywhere}
.food-energy.pending{color:#a27842}
.energy-rule{font-size:11px;line-height:1.8;color:#819285;margin:0 0 12px}
.energy-warning{font-size:12px;line-height:1.8;color:#8e6229;background:#fff7e9;border-radius:10px;padding:10px 12px;margin:0 0 14px}
.weight-row{margin-top:12px}.weight-row label{display:grid;gap:6px;font-size:11px;color:#647e6a}.weight-row input{width:100%;box-sizing:border-box;border:1px solid #dfe8df;border-radius:10px;padding:10px;color:#304e3a;background:#fafcf9;font-size:12px}
.food-source{font-size:10px;line-height:1.7;color:#9a854e;margin:5px 0 0}
</style>
