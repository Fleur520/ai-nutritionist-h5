<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { Camera, Check, LoaderCircle, Plus, Trash2, ArrowRight, Utensils, RefreshCw } from 'lucide-vue-next'
import { api, jsonBody, type Food, type Recognized } from '../lib/api'
import FoodPicker from '../components/FoodPicker.vue'

const emit = defineEmits<{ go: [value: string] }>()
const fileRef = ref<HTMLInputElement | null>(null), preview = ref(''), imageId = ref(''), busy = ref(false), saving = ref(false), error = ref(''), notice = ref(''), mealType = ref('lunch')
const foods = ref<Food[]>([]), foodsLoading = ref(true), foodsError = ref('')
const items = ref<(Recognized & { food_code: string; originalFoodCode?: string; manualSelection?: boolean })[]>([])
const foodsByCode = computed(() => new Map(foods.value.map(food => [food.code, food])))
const uploadRequest = new AbortController()
let disposed = false
async function loadFoods() {
  foodsLoading.value = true; foodsError.value = ''
  try { foods.value = await api<Food[]>('/foods') }
  catch { foodsError.value = '食品库暂时没有加载出来，请重试。' }
  finally { foodsLoading.value = false }
}
onMounted(loadFoods)
onBeforeUnmount(() => { disposed = true; uploadRequest.abort(); if (preview.value) URL.revokeObjectURL(preview.value) })
type ScanItem = (typeof items.value)[number]
function selectedFood(item: ScanItem) { return foodsByCode.value.get(item.food_code) }
function hasMatchingInfo(item: ScanItem) { return typeof item.match_status === 'string' }
function chooseFood(item: ScanItem, code: string) {
  if (saving.value || foodsLoading.value || code && !foodsByCode.value.has(code)) return
  item.food_code = code
  item.manualSelection = true
}
function matchingLabel(item: ScanItem) {
  return item.match_status === 'matched' && item.food_code === item.originalFoodCode && !item.manualSelection
    ? '已匹配食品库' : '已手动选择食物'
}
function usesLegacyReference(item: ScanItem) {
  return item.match_note === 'legacy_cooked_reference' && item.food_code === item.originalFoodCode
}
function matchingReason(item: ScanItem) {
  switch (item.match_status) {
    case 'ambiguous': return '有几种相近的食物，名称或做法还不能确定，请你选一下。'
    case 'preparation_conflict': return '照片中的做法与食品库记录不同，请核对生熟和烹调方式后选择。'
    case 'name_mismatch': return '找到的食物与照片名称不完全一致，请核对后选择。'
    case 'stale_candidate': return '食品库记录已有更新，请重新选择对应食物。'
    case 'no_evidence':
    case 'not_found': return '暂时没有找到合适的食品库记录，可以换个名称搜索。'
    default: return '还不能确定对应食物，请你从食品库中选一下。'
  }
}
const cleanFoodName = (value: string) => value.normalize('NFKC').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
function suggestionScore(name: string, food: Food) {
  const target = cleanFoodName(name)
  if (!target) return 0
  const parts = new Set(Array.from({ length: Math.max(0, target.length - 1) }, (_, index) => target.slice(index, index + 2)))
  return Math.max(0, ...[food.name, ...(food.aliases || [])].map(label => {
    const candidate = cleanFoodName(label)
    if (candidate === target) return 4
    if (target.length >= 2 && candidate.includes(target) || candidate.length >= 2 && target.includes(candidate)) return 3
    return [...parts].some(part => candidate.includes(part)) ? 1 : 0
  }))
}
function relevantCandidates(item: ScanItem) {
  const unique = new Set<string>()
  return (item.candidates || []).flatMap(candidate => {
    // Names, preparation and nutrition always come from the current /foods data.
    const food = foodsByCode.value.get(candidate.code)
    if (!food || unique.has(food.code)) return []
    unique.add(food.code)
    const score = suggestionScore(item.name, food)
    return score ? [{ food, score }] : []
  }).sort((left, right) => right.score - left.score).slice(0, 3).map(entry => entry.food)
}
function validWeight(item: ScanItem) {
  const grams = Number(item.estimated_grams)
  return Number.isFinite(grams) && grams >= 5 && grams <= 3000
}
function itemEnergy(item: ScanItem): number | null {
  const food = selectedFood(item)
  return food && validWeight(item) ? food.kcal * Number(item.estimated_grams) / 100 : null
}
function energyText(value: number) { return Number(value.toFixed(1)).toString() }
const calculatedCount = computed(() => items.value.filter(item => itemEnergy(item) !== null).length)
const total = computed(() => items.value.reduce((sum, item) => sum + (itemEnergy(item) ?? 0), 0))
const complete = computed(() => items.value.length > 0 && calculatedCount.value === items.value.length)
function add() {
  if (busy.value || saving.value) return
  if (items.value.length >= 30) { error.value = '一餐最多记录 30 项食物。'; return }
  items.value.push({ name: '手动添加的食物', estimated_grams: 100, food_code: '' })
}
function upload() { if (!busy.value && !saving.value) fileRef.value?.click() }
async function onFile(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]; input.value = ''
  if (!file || busy.value || saving.value) return
  if (file.size > 5 * 1024 * 1024) { error.value = '这张照片超过 5MB，请选择小一点的照片。'; return }
  if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) { error.value = '请选择 JPG、PNG 或 WebP 格式的照片。'; return }
  if (preview.value) URL.revokeObjectURL(preview.value)
  preview.value = URL.createObjectURL(file)
  imageId.value = ''
  items.value = []
  busy.value = true; error.value = ''; notice.value = ''
  try {
    const form = new FormData(); form.append('file', file)
    const result = await api<{ id: string }>('/images', { method: 'POST', body: form, signal: uploadRequest.signal })
    imageId.value = result.id
    const recognized = await api<{ items: Recognized[]; notice: string }>('/meals/recognize', { method: 'POST', body: jsonBody({ image_id: result.id }), signal: uploadRequest.signal })
    items.value = recognized.items.map(item => ({ ...item, food_code: item.food_code || '', originalFoodCode: item.food_code || '', manualSelection: false }))
    notice.value = recognized.notice
  } catch (failure) {
    if (!uploadRequest.signal.aborted) error.value = failure instanceof Error ? failure.message : '照片识别失败，请重试或手动添加食物。'
  } finally { busy.value = false }
}
async function save() {
  if (saving.value || busy.value) return
  if (!complete.value) { error.value = '请为每项选择对应食物，并填写 5～3000 克的重量。'; return }
  saving.value = true; error.value = ''
  try {
    await api('/meals', { method: 'POST', body: jsonBody({ meal_type: mealType.value, eaten_at: new Date().toISOString(), image_id: imageId.value || null, items: items.value.map(item => ({ food_code: item.food_code, grams: item.estimated_grams })) }) })
    if (!disposed) emit('go', 'history')
  } catch (failure) { error.value = failure instanceof Error ? failure.message : '保存失败，请稍后重试' }
  finally { saving.value = false }
}
</script>

<template>
  <section class="page scan-page">
    <header class="page-header"><div class="eyebrow">CAPTURE YOUR MEAL</div><h1 class="page-title">好好吃饭，从这一餐开始。</h1><p class="page-subtitle">拍下餐盘，认识食物。确认一下分量，就能留下一份饮食日记。</p></header>
    <button type="button" class="upload-card" :class="{ filled: preview }" :disabled="busy || saving" @click="upload" :aria-label="preview ? '重新选择餐食照片' : '拍照或从相册选择食物照片'">
      <img v-if="preview" :src="preview" alt="餐食预览" />
      <template v-else><span class="upload-circle"><Camera :size="32" /></span><h3>拍下你的美味</h3><p>拍照或从相册选择 · 5MB 以内</p></template>
      <span class="upload-action">{{ preview ? '重新选择照片' : '选择餐食照片' }}<ArrowRight :size="16" /></span>
    </button>
    <input ref="fileRef" class="hidden" type="file" accept="image/png,image/jpeg,image/webp" @change="onFile" />
    <div v-if="busy" class="notice scan-progress" role="status"><LoaderCircle :size="19" class="spinning" /><span>正在认识盘中的食物…<small>分量是初步估算，稍后可以自己调整</small></span></div>
    <p v-if="notice" class="notice" role="status">{{ notice }}</p><p v-if="error" class="error" role="alert">{{ error }}</p>
    <div v-if="foodsError" class="error food-load-error" role="alert"><span>{{ foodsError }}</span><button type="button" class="text-action" @click="loadFoods"><RefreshCw :size="16" />重试</button></div>
    <div class="section-header"><div><h2>{{ items.length ? '确认食物与分量' : '这一餐吃了什么' }}</h2><p class="section-copy">估算会有偏差，你可以随时调整</p></div><button type="button" class="text-action" @click="add" :disabled="busy || saving || items.length >= 30"><Plus :size="17" />手动添加</button></div>
    <div v-if="!items.length && !busy" class="empty-state scan-empty"><Utensils :size="28" /><strong>记录自己的饮食节奏</strong><p>拍照后，食物会出现在这里。<br />也可以直接手动添加。</p></div>
    <article v-for="(item, index) in items" :key="index" class="food-item">
      <div class="food-head"><div><span class="food-index">{{ String(index + 1).padStart(2, '0') }}</span><strong>{{ item.name }}</strong></div><button type="button" class="icon-button" :aria-label="'删除' + item.name" :disabled="saving" @click="items.splice(index, 1)"><Trash2 :size="18" /></button></div>
      <div v-if="hasMatchingInfo(item)" class="matching-info" aria-live="polite">
        <template v-if="selectedFood(item)">
          <span class="matching-tag"><Check :size="14" aria-hidden="true" />{{ matchingLabel(item) }}</span>
          <p v-if="usesLegacyReference(item)" class="matching-reference">这条参考记录只标注了“熟”，没有具体做法，请确认是否适合这一餐。</p>
        </template>
        <template v-else>
          <p class="matching-reason">{{ matchingReason(item) }}</p>
          <p v-if="item.preparation" class="matching-preparation">照片参考做法：{{ item.preparation }}</p>
          <div v-if="relevantCandidates(item).length" class="matching-candidates">
            <span class="matching-candidates-label">可能相近的食物 · 点选后才计入能量</span>
            <button v-for="food in relevantCandidates(item)" :key="food.code" type="button" class="candidate-button" :disabled="saving || foodsLoading" :aria-label="'选择食品库食物：' + food.name + '，' + (food.preparation || '做法未注明')" @click="chooseFood(item, food.code)">
              <span><strong>{{ food.name }}</strong><small>{{ food.preparation || '做法未注明' }}</small></span><ArrowRight :size="16" aria-hidden="true" />
            </button>
          </div>
        </template>
      </div>
      <FoodPicker :model-value="item.food_code" :foods="foods" :disabled="saving || foodsLoading" @update:model-value="value => chooseFood(item, value)" />
      <div class="weight-row"><label>估计重量（克）<input type="number" v-model.number="item.estimated_grams" min="5" max="3000" step="5" inputmode="decimal" :disabled="saving" :aria-invalid="!validWeight(item)" /></label><div class="item-calories"><span>这份食物</span><strong>{{ itemEnergy(item) === null ? '—' : energyText(itemEnergy(item) || 0) }}<small> kcal</small></strong></div></div>
      <p class="food-energy" :class="{ pending: itemEnergy(item) === null }" aria-live="polite">
        <template v-if="!selectedFood(item)">请选择对应食物，再计算这一份的能量。</template>
        <template v-else-if="!validWeight(item)">重量请填写 5～3000 克。</template>
        <template v-else>{{ selectedFood(item)?.kcal }} kcal/100g × {{ item.estimated_grams }}g ÷ 100</template>
      </p>
      <p v-if="selectedFood(item)" class="food-source">{{ selectedFood(item)?.source_type === 'ai_estimate' ? 'AI 估算 · 未核验' : '原有演示数据' }} · 每 100 克可食部<span v-if="selectedFood(item)?.preparation"> · {{ selectedFood(item)?.preparation }}</span></p>
    </article>
    <div v-if="items.length" class="result-bottom">
      <label class="form-label">记在哪一餐<select v-model="mealType" :disabled="saving"><option value="breakfast">早餐</option><option value="lunch">午餐</option><option value="dinner">晚餐</option><option value="snack">加餐</option></select></label>
      <div class="sum-line" aria-live="polite"><span>{{ !complete ? '已匹配食物小计' : '本餐估算能量' }}</span><strong>{{ energyText(total) }} <small>kcal</small></strong></div>
      <p class="energy-rule">按每 100 克食物能量 × 实际重量计算，再相加。调整食物或重量，估算会实时更新。</p>
      <p v-if="!complete" class="energy-warning" role="status">已计入 {{ calculatedCount }}/{{ items.length }} 项。补齐食物与重量后，就可以保存整餐记录。</p>
      <button type="button" class="primary-button" @click="save" :disabled="saving || busy || !complete"><Check :size="19" />{{ saving ? '正在保存这一餐…' : '保存这一餐' }}</button>
    </div>
    <p class="microcopy">食品库包含未经实验核验的 AI 营养估算。请选择相应的食物与生熟状态；配料、烹调方式和用油会影响实际营养。</p>
  </section>
</template>

<style scoped>
.upload-card{width:100%;font:inherit;color:inherit;padding:0}.upload-card:disabled{opacity:1}.section-copy{margin:5px 0 0;font-size:12px;line-height:1.5;color:#7b8d81}.scan-empty{display:flex;flex-direction:column;align-items:center;gap:12px;background:white;border:1px solid #e5ebe5;padding:28px 18px}.scan-empty>svg{color:#8eac8c}.scan-empty strong{font-size:16px;color:#496b50}.scan-empty p{margin:0;font-size:14px;line-height:1.8;color:#7b8e80}.scan-progress small{display:block;font-size:12px;color:#7b8e80;margin-top:3px}.scan-progress>svg{flex-shrink:0}.food-head>div{display:flex;align-items:center;gap:9px;min-width:0}.food-head strong{overflow-wrap:anywhere}.food-index{font-size:12px;color:#839a85;border-radius:8px;background:#f0f5ed;padding:5px 7px;font-weight:600}.food-head .icon-button{min-width:44px;min-height:44px;flex-shrink:0}.food-energy{font-size:12px;line-height:1.7;color:#6d8773;margin:10px 0 0;overflow-wrap:anywhere}.food-energy.pending{color:#9e713f}.energy-rule{font-size:12px;line-height:1.8;color:#77897d;margin:0 0 16px}.energy-warning{font-size:13px;line-height:1.8;color:#8c622d;background:#fff5e9;border-radius:13px;padding:12px 14px;margin:0 0 16px}.weight-row{margin-top:16px;display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;align-items:end}.weight-row label{display:grid;gap:8px;font-size:13px;font-weight:500;color:#5e7565}.weight-row input{width:100%;min-width:0;box-sizing:border-box;border:1px solid #dfe8df;border-radius:12px;padding:11px 12px;color:#304e3a;background:#fafcf9;font-size:16px;min-height:48px}.weight-row input[aria-invalid=true]{border-color:#d9ad7a}.item-calories{padding:0 5px 8px;text-align:right}.item-calories>span{display:block;font-size:12px;color:#8a9a8e;margin-bottom:7px}.item-calories strong{font-size:23px;font-weight:700;color:#245b43;letter-spacing:-.5px}.item-calories small{font-size:12px;color:#819487;letter-spacing:0;font-weight:400}.food-source{font-size:11px;line-height:1.8;color:#8d805b;margin:5px 0 0}.result-bottom{background:white;border:1px solid #e5ebe5;border-radius:22px;padding:20px}.food-load-error{display:flex;gap:8px;align-items:center;justify-content:space-between}.food-load-error .text-action{min-width:60px;min-height:44px}.sum-line{margin:19px 0 12px}.scan-page .text-action{min-height:44px;padding:4px 0;flex-shrink:0;font-size:13px}.scan-page .section-header{align-items:center}
.matching-info{margin:-2px 0 16px}.matching-tag{display:inline-flex;align-items:center;gap:5px;padding:6px 9px;border-radius:9px;background:#edf5ee;color:#32644a;font-size:12px;font-weight:500}.matching-reference,.matching-reason{margin:9px 0 0;padding:11px 13px;border:1px solid #f0e3cf;border-radius:12px;background:#fff9ef;color:#88683e;font-size:13px;line-height:1.75;overflow-wrap:anywhere}.matching-reason{margin:0}.matching-preparation{margin:7px 0 0;color:#7b8d81;font-size:12px;line-height:1.6}.matching-candidates{display:grid;gap:7px;margin-top:12px}.matching-candidates-label{font-size:12px;color:#7b8d81;line-height:1.6}.candidate-button{display:flex;align-items:center;justify-content:space-between;gap:10px;width:100%;min-height:48px;padding:10px 12px;border:1px solid #dfe8df;border-radius:12px;background:#fafcf9;color:#315b42;text-align:left;cursor:pointer;font:inherit}.candidate-button>span{display:grid;gap:3px;min-width:0}.candidate-button strong{font-size:13px;font-weight:500;line-height:1.5;overflow-wrap:anywhere}.candidate-button small{font-size:11px;line-height:1.5;color:#7b8d81}.candidate-button>svg{flex-shrink:0;color:#819c87}.candidate-button:hover{border-color:#9abb9d;background:#f1f7ee}.candidate-button:focus-visible{outline:2px solid #72a37b;outline-offset:2px}.candidate-button:disabled{opacity:.55;cursor:default}
</style>
