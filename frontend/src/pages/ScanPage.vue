<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { Camera, WandSparkles, Check, LoaderCircle, Plus, Trash2, ArrowRight } from 'lucide-vue-next'
import { api, jsonBody, type Food, type Recognized } from '../lib/api'
const emit=defineEmits<{go:[value:string]}>()
const fileRef=ref<HTMLInputElement|null>(null), preview=ref(''),imageId=ref(''),busy=ref(false),saving=ref(false),error=ref(''),notice=ref(''),mealType=ref('lunch')
const foods=ref<Food[]>([])
const items=ref<(Recognized & {food_code:string})[]>([])
onMounted(async()=>{foods.value=await api('/foods').catch(()=>[])})
const total=computed(()=>items.value.reduce((sum,i)=>sum+(foods.value.find(f=>f.code===i.food_code)?.kcal||0)*(i.estimated_grams||0)/100,0))
function add(){items.value.push({name:'手动新增',estimated_grams:100,food_code:foods.value[0]?.code||''})}
function upload(){fileRef.value?.click()}
async function onFile(e:Event){
 const file=(e.target as HTMLInputElement).files?.[0];if(!file)return
 if(file.size>5*1024*1024){error.value='图片不能超过 5MB';return}
 preview.value=URL.createObjectURL(file);busy.value=true;error.value='';notice.value='';items.value=[]
 try{
   const form=new FormData();form.append('file',file)
   const result=await api<{id:string}>('/images',{method:'POST',body:form})
   imageId.value=result.id
   const recognized=await api<{items:Recognized[];notice:string}>('/meals/recognize',{method:'POST',body:jsonBody({image_id:imageId.value})})
   items.value=recognized.items.map(x=>({...x,food_code:x.food_code||foods.value.find(f=>f.name.includes(x.name)||x.name.includes(f.name.replace(/（.*?）/g,'')))?.code||''}))
   notice.value=recognized.notice
 }catch(e){error.value=e instanceof Error?e.message:'识别失败'}finally{busy.value=false}
}
async function save(){
 if(!items.value.length||items.value.some(x=>!x.food_code||x.estimated_grams<5)){error.value='请确认食物名称和重量';return}
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
<div v-for="(item,index) in items" :key="index" class="food-item"><div class="food-head"><strong>{{item.name}}</strong><button class="icon-button" title="删除" @click="items.splice(index,1)"><Trash2 :size="16"/></button></div><div class="form-grid"><label>对应标准食物<select v-model="item.food_code"><option value="">请选择标准食物</option><option v-for="f in foods" :value="f.code" :key="f.code">{{f.name}}</option></select></label><label>重量（克）<input type="number" v-model.number="item.estimated_grams" min="5" max="3000" step="5"/></label></div></div>
<div class="result-bottom"><label class="form-label">餐别<select v-model="mealType"><option value="breakfast">早餐</option><option value="lunch">午餐</option><option value="dinner">晚餐</option><option value="snack">加餐</option></select></label><div class="sum-line"><span>本餐估算能量</span><strong>{{Math.round(total)}} <small>kcal</small></strong></div><button class="primary-button" @click="save" :disabled="saving||!items.length"><Check :size="17"/>{{saving?'保存中…':'确认并保存饮食记录'}}</button></div>
<p class="microcopy">演示数据仅供功能测试。真实数值应核对经授权的食物成分数据库，且与生熟、烹调方式保持一致。</p></section></template>
