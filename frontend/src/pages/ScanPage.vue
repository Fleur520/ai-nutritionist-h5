<script setup lang="ts">
import { ref, computed, onBeforeUnmount, onDeactivated } from 'vue'
import { Camera, Images, Expand, Check, LoaderCircle, Plus, Trash2, Utensils, RefreshCw } from 'lucide-vue-next'
import { api, jsonBody, type Food, type Recognized } from '../lib/api'
import FoodPicker from '../components/FoodPicker.vue'
import ImageViewer from '../components/ImageViewer.vue'

const emit = defineEmits<{ go: [value: string] }>()
type ScanItem = Recognized & { rowId: number; recognitionIndex?: number; nutritionSource: 'model' | 'catalog' }
const albumRef = ref<HTMLInputElement | null>(null), cameraRef = ref<HTMLInputElement | null>(null)
const preview = ref(''), viewingPhoto = ref(false), imageId = ref(''), recognitionId = ref('')
const busy = ref(false), saving = ref(false), error = ref(''), notice = ref(''), stage = ref('')
const chinaHour = Number(new Intl.DateTimeFormat('en-US', { timeZone: 'Asia/Shanghai', hour: '2-digit', hourCycle: 'h23' }).format(new Date()))
const mealType = ref(chinaHour < 10 ? 'breakfast' : chinaHour < 15 ? 'lunch' : chinaHour < 21 ? 'dinner' : 'snack')
const foods = ref<Food[]>([]), foodsLoading = ref(false), foodsError = ref('')
const items = ref<ScanItem[]>([]), saved = ref(false)
let nextRowId = 0, disposed = false
let selectedFile: File | null = null
let uploadFile: File | null = null
const request = new AbortController()
const foodsByCode = computed(() => new Map(foods.value.map(food => [food.code, food])))
async function loadFoods() {
  foodsLoading.value = true; foodsError.value = ''
  try { foods.value = await api<Food[]>('/foods', { signal: request.signal }) }
  catch { if (!disposed) foodsError.value = '手动记餐的数据暂时无法加载，请重试。' }
  finally { foodsLoading.value = false }
}
onBeforeUnmount(() => { disposed = true; request.abort(); if (preview.value) URL.revokeObjectURL(preview.value) })
onDeactivated(() => { viewingPhoto.value = false })
function reference(item: ScanItem) { return item.nutritionSource === 'model' ? item.nutrition : foodsByCode.value.get(item.food_code || '') }
function validWeight(item: ScanItem) { return Number.isFinite(item.estimated_grams) && item.estimated_grams >= 5 && item.estimated_grams <= 3000 }
function amount(item: ScanItem, key: 'kcal' | 'protein' | 'fat' | 'carbs') { return reference(item) && validWeight(item) ? reference(item)![key] * item.estimated_grams / 100 : null }
function display(value: number | null) { return value === null ? '—' : Number(value.toFixed(1)).toString() }
const totals = computed(() => items.value.reduce((sum, item) => {
  for (const key of ['kcal', 'protein', 'fat', 'carbs'] as const) sum[key] += amount(item, key) ?? 0
  return sum
}, { kcal: 0, protein: 0, fat: 0, carbs: 0 }))
const calculatedCount = computed(() => items.value.filter(item => amount(item, 'kcal') !== null).length)
const complete = computed(() => items.value.length > 0 && calculatedCount.value === items.value.length)
function add() {
  if (busy.value || saving.value || items.value.length >= 30) return
  items.value.push({ name: '手动记录', estimated_grams: 100, food_code: '', rowId: ++nextRowId, nutritionSource: 'catalog' })
  if (!foods.value.length && !foodsLoading.value) void loadFoods()
}
function chooseFood(item: ScanItem, code: string) {
  item.food_code = code
  item.name = foodsByCode.value.get(code)?.name || '手动记录'
}
function pick(source: 'camera' | 'album') { if (!busy.value && !saving.value) (source === 'camera' ? cameraRef : albumRef).value?.click() }
async function onFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]
  input.value = ''
  if (!file || busy.value || saving.value) return
  if (file.size > 25 * 1024 * 1024) { error.value = '照片超过 25MB，请在相册中选择较小的照片。'; return }
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type) && !(file.type === '' && /\.(jpe?g|png|webp)$/i.test(file.name))) { error.value = '请使用 JPG、PNG 或 WebP 照片；HEIC 照片请先转为 JPG。'; return }
  if (items.value.length && !window.confirm('更换照片会清除这一餐尚未保存的食物，确定更换吗？')) return
  if (preview.value) URL.revokeObjectURL(preview.value)
  selectedFile = file; uploadFile = null; preview.value = URL.createObjectURL(file); viewingPhoto.value = false
  imageId.value = ''; recognitionId.value = ''; items.value = []; saved.value = false
  await recognize()
}
async function prepareUpload(file: File): Promise<File> {
  const image = new Image()
  const loaded = new Promise<void>((resolve, reject) => {
    image.onload = () => resolve()
    image.onerror = () => reject(new Error('无法打开这张照片，请换一张 JPG、PNG 或 WebP 图片。'))
  })
  image.src = preview.value
  await loaded
  const scale = Math.min(1, 2048 / Math.max(image.naturalWidth, image.naturalHeight))
  if (scale === 1 && file.size <= 5 * 1024 * 1024) return file
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(image.naturalWidth * scale))
  canvas.height = Math.max(1, Math.round(image.naturalHeight * scale))
  const context = canvas.getContext('2d')
  if (!context) throw new Error('当前浏览器无法处理大照片，请选择 5MB 以内的图片。')
  context.fillStyle = '#ffffff'; context.fillRect(0, 0, canvas.width, canvas.height)
  context.drawImage(image, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.85))
  if (!blob || blob.size > 5 * 1024 * 1024) throw new Error('照片处理失败，请选择较小的图片重试。')
  return new File([blob], 'meal.jpg', { type: 'image/jpeg' })
}
async function recognize() {
  if (!selectedFile || busy.value || saving.value) return
  if (items.value.length && !window.confirm('重新识别会替换当前食物和已调整的分量，继续吗？')) return
  busy.value = true; error.value = ''; notice.value = ''
  try {
    if (!imageId.value) {
      stage.value = '正在准备照片…'
      uploadFile ||= await prepareUpload(selectedFile)
      if (disposed) return
      stage.value = '正在上传照片…'
      const form = new FormData(); form.append('file', uploadFile)
      const uploaded = await api<{ id: string }>('/images', { method: 'POST', body: form, signal: request.signal })
      imageId.value = uploaded.id
    }
    stage.value = 'AI 正在识别食物与营养…'
    const result = await api<{ items: Recognized[]; recognition_id: string; elapsed_ms?: number }>('/meals/recognize', { method: 'POST', body: jsonBody({ image_id: imageId.value }), signal: request.signal })
    recognitionId.value = result.recognition_id
    items.value = result.items.map((item, index) => ({ ...item, food_code: null, rowId: ++nextRowId, recognitionIndex: index, nutritionSource: 'model' }))
    notice.value = result.items.length ? `AI 已识别 ${result.items.length} 项食物${result.elapsed_ms ? ` · ${(result.elapsed_ms / 1000).toFixed(1)} 秒` : ''}，请确认分量。` : '这张照片没有识别出食物，请换一张清晰的餐图，或手动记餐。'
  } catch (failure) {
    if (!disposed) error.value = failure instanceof Error ? failure.message : '识别失败，请重试。'
  } finally { busy.value = false }
}
async function save() {
  if (saving.value || busy.value || !complete.value) return
  saving.value = true; error.value = ''
  try {
    await api('/meals', { method: 'POST', body: jsonBody({ meal_type: mealType.value, eaten_at: new Date().toISOString(), image_id: imageId.value || null, recognition_id: recognitionId.value || null,
      items: items.value.map(item => ({ food_code: item.nutritionSource === 'model' ? null : item.food_code || null, grams: item.estimated_grams, nutrition_source: item.nutritionSource, recognition_index: item.recognitionIndex })) }), signal: request.signal })
    if (disposed) return
    viewingPhoto.value = false
    items.value = []; imageId.value = ''; recognitionId.value = ''; selectedFile = null; uploadFile = null
    if (preview.value) URL.revokeObjectURL(preview.value)
    preview.value = ''; notice.value = ''; saved.value = true
    emit('go', 'history')
  } catch (failure) { if (!disposed) error.value = failure instanceof Error ? failure.message : '保存失败，请稍后重试。' }
  finally { saving.value = false }
}
</script>

<template>
  <section class="page scan-page">
    <header class="page-header"><div class="eyebrow">CAPTURE YOUR MEAL</div><h1 class="page-title">好好吃饭，从这一餐开始。</h1><p class="page-subtitle">拍下餐盘，AI 识别食物与营养，确认分量后保存。</p></header>
    <button v-if="preview" type="button" class="upload-card filled photo-preview" @click="viewingPhoto = true" aria-label="查看餐食原图"><img :src="preview" alt="已选择的餐食照片" /><span class="upload-action"><Expand :size="16" />查看原图</span></button>
    <button v-else type="button" class="upload-card photo-empty" :disabled="busy || saving" @click="pick('album')" aria-label="拍照或选择餐食照片"><span class="upload-circle"><Camera :size="32" /></span><span class="photo-empty-title">拍照或选择照片</span><span class="photo-empty-hint">JPG、PNG、WebP · 最大 25MB，大照片自动压缩上传</span></button>
    <div class="photo-actions"><button type="button" :disabled="busy || saving" @click="pick('camera')"><Camera :size="19" />{{ preview ? '重新拍照' : '拍照' }}</button><button type="button" :disabled="busy || saving" @click="pick('album')"><Images :size="19" />{{ preview ? '更换照片' : '从相册选择' }}</button></div>
    <input ref="cameraRef" class="hidden" type="file" accept="image/jpeg,image/png,image/webp" capture="environment" aria-label="拍摄餐食照片" @change="onFile" />
    <input ref="albumRef" class="hidden" type="file" accept="image/jpeg,image/png,image/webp" aria-label="从相册选择餐食照片" @change="onFile" />
    <div v-if="busy" class="notice scan-progress" role="status"><LoaderCircle :size="19" class="spinning" /><span>{{ stage }}<small>通常需要几秒，请稍候；可以先查看原图</small></span></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p>
    <div v-if="error" class="error" role="alert">{{ error }}</div>
    <button v-if="preview && !busy" type="button" class="text-action retry-recognition" :disabled="saving" @click="recognize"><RefreshCw :size="16" />{{ error || !items.length ? '重试识别' : '重新识别这张照片' }}</button>
    <p v-if="saved && !preview && !items.length" class="notice success" role="status">上一餐已保存，可以开始记录新的一餐。</p>
    <div class="section-header"><div><h2>{{ items.length ? '确认食物与分量' : '这一餐吃了什么' }}</h2><p class="section-copy">{{ items.length ? '以 AI 识别为依据，修改重量会同步更新营养' : '拍照识别，也可以单独手动记餐' }}</p></div><button type="button" class="text-action" @click="add" :disabled="busy || saving || items.length >= 30"><Plus :size="17" />手动记餐</button></div>
    <div v-if="!items.length && !busy" class="empty-state scan-empty"><Utensils :size="28" /><strong>{{ preview ? '暂时没有可保存的食物' : '记录自己的饮食节奏' }}</strong><p>{{ preview ? '重试识别、换张照片，或手动记餐。' : '拍照或选择相册照片，食物会出现在这里。' }}</p></div>
    <article v-for="(item, index) in items" :key="item.rowId" class="food-item">
      <div class="food-head"><div><span class="food-index">{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ item.name }}</strong></div><button type="button" class="icon-button" :aria-label="'删除' + item.name" :disabled="saving || busy" @click="items.splice(index, 1)"><Trash2 :size="18" /></button></div>
      <template v-if="item.nutritionSource === 'catalog'"><FoodPicker :model-value="item.food_code || ''" :foods="foods" :disabled="saving || busy || foodsLoading" @update:model-value="value => chooseFood(item, value)" /><p v-if="foodsError" class="error">{{ foodsError }}<button type="button" class="text-action" @click="loadFoods">重试加载</button></p></template>
      <p v-else class="ai-source">AI 识别 · 营养估算<span v-if="item.preparation"> · {{ item.preparation }}</span></p>
      <div class="weight-row"><label :for="'weight-' + item.rowId">{{ item.nutritionSource === 'model' ? '确认重量（克）' : '食物重量（克）' }}<input :id="'weight-' + item.rowId" type="number" v-model.number="item.estimated_grams" min="5" max="3000" step="any" inputmode="decimal" :disabled="saving || busy" :aria-invalid="!validWeight(item)" :aria-describedby="'weight-help-' + item.rowId" /></label><div class="item-calories"><span>这份食物</span><strong>{{ display(amount(item, 'kcal')) }}<small> kcal</small></strong></div></div>
      <p :id="'weight-help-' + item.rowId" class="food-energy" :class="{ pending: amount(item, 'kcal') === null }"><template v-if="!validWeight(item)">请填写 5～3000 克，不能留空。</template><template v-else-if="!reference(item)">{{ item.nutritionSource === 'model' ? 'AI 未返回这项营养数据，请重试识别或删除此项后保存。' : '请选择手动记录的食物。' }}</template><template v-else>{{ reference(item)?.kcal }} kcal / 100 克 · 按确认重量换算</template></p>
      <div v-if="reference(item)" class="item-macros"><span>蛋白质 <b>{{ display(amount(item, 'protein')) }}</b> g</span><span>碳水 <b>{{ display(amount(item, 'carbs')) }}</b> g</span><span>脂肪 <b>{{ display(amount(item, 'fat')) }}</b> g</span></div>
    </article>
    <div v-if="items.length" class="result-bottom">
      <label class="form-label">记在哪一餐<select v-model="mealType" :disabled="saving || busy"><option value="breakfast">早餐</option><option value="lunch">午餐</option><option value="dinner">晚餐</option><option value="snack">加餐</option></select></label>
      <div class="sum-line" aria-live="polite"><span>{{ complete ? '本餐估算能量' : '已计算食物小计' }}</span><strong>{{ display(totals.kcal) }} <small>kcal</small></strong></div>
      <div class="item-macros total-macros"><span>蛋白质 <b>{{ display(totals.protein) }}</b> g</span><span>碳水 <b>{{ display(totals.carbs) }}</b> g</span><span>脂肪 <b>{{ display(totals.fat) }}</b> g</span></div>
      <p v-if="!complete" class="energy-warning" role="status">已计入 {{ calculatedCount }}/{{ items.length }} 项，请检查上方重量和营养数据。缺少数据的项目不会按 0 保存。</p>
      <button type="button" class="primary-button" @click="save" :disabled="saving || busy || !complete"><LoaderCircle v-if="saving" :size="19" class="spinning" /><Check v-else :size="19" />{{ saving ? '正在保存这一餐…' : '确认并保存这一餐' }}</button>
    </div>
    <p class="microcopy">AI 识别和营养数据为估算，未经实验核验。请确认食物、做法和实际分量。</p>
    <ImageViewer v-if="viewingPhoto && preview" :src="preview" title="餐食原图" @close="viewingPhoto = false" />
  </section>
</template>

<style scoped>
.photo-empty{width:100%;padding:20px;color:inherit}.photo-empty-title{font-size:18px;font-weight:700;margin-bottom:7px}.photo-empty-hint{font-size:12px;line-height:1.7;color:#7d907a}.photo-preview{width:100%;padding:0;font:inherit}.photo-preview img{object-fit:contain}.photo-actions{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:12px 0 18px}.photo-actions button{display:flex;align-items:center;justify-content:center;gap:8px;min-height:48px;border:1px solid #d9e5d9;border-radius:14px;background:white;color:#285f46;font-size:14px;font-weight:600}.photo-actions button:first-child{background:#e9f2e5}.section-copy{margin:5px 0 0;font-size:12px;line-height:1.7;color:#7b8d81}.section-header{align-items:center;gap:12px}.scan-page .text-action{min-height:44px;padding-left:0}.retry-recognition{margin-bottom:6px}.scan-empty{display:flex;flex-direction:column;align-items:center;gap:12px}.scan-empty p{margin:0}.scan-progress>svg{flex-shrink:0}.scan-progress small{display:block;font-size:12px;margin-top:3px}.food-head>div{display:flex;align-items:center;gap:9px;min-width:0}.food-head strong{overflow-wrap:anywhere}.food-index{font-size:12px;color:#839a85;background:#f0f5ed;padding:5px 7px;border-radius:8px}.food-head .icon-button{min-width:44px;min-height:44px;flex-shrink:0}.ai-source{font-size:12px;color:#72866e;line-height:1.7;margin:-4px 0 14px}.weight-row{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:end;margin-top:14px}.weight-row label{display:grid;gap:8px;font-size:13px;color:#5e7565}.weight-row input{width:100%;min-width:0;min-height:48px;border:1px solid #dfe8df;border-radius:12px;padding:11px 12px;color:#304e3a;background:#fafcf9}.weight-row input[aria-invalid=true]{border-color:#ce875d}.item-calories{text-align:right;padding-bottom:8px}.item-calories>span{display:block;font-size:12px;color:#8a9a8e;margin-bottom:7px}.item-calories strong{font-size:23px;color:#245b43}.item-calories small{font-size:12px;color:#819487;font-weight:400}.food-energy{font-size:12px;line-height:1.7;color:#7b8d81;margin:10px 0}.food-energy.pending{color:#9e713f}.item-macros{display:flex;flex-wrap:wrap;gap:8px 15px;font-size:12px;color:#72836e;line-height:1.8}.item-macros b{font-weight:600;color:#496c4f}.total-macros{margin-bottom:20px}.result-bottom{padding:20px;border-radius:22px;border:1px solid #e5ebe5;background:white}.sum-line{margin:18px 0 12px}.energy-warning{font-size:13px;line-height:1.8;color:#8c622d;background:#fff5e9;padding:12px;border-radius:12px;margin:0 0 16px}
</style>

