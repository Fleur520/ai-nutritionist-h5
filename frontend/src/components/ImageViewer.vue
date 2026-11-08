<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { X, ZoomIn, Minimize2 } from 'lucide-vue-next'
defineProps<{ src: string; title: string }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement | null>(null), zoomed = ref(false), failed = ref(false)
let previousOverflow = ''
onMounted(() => {
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  dialog.value?.showModal()
})
onBeforeUnmount(() => { dialog.value?.close(); document.body.style.overflow = previousOverflow })
</script>

<template>
  <Teleport to="body">
    <dialog ref="dialog" class="image-viewer" :aria-label="title" @close="emit('close')" @click="event => { if (event.target === dialog) dialog?.close() }">
      <header><strong>{{ title }}</strong><button type="button" autofocus aria-label="关闭照片预览" @click="dialog?.close()"><X :size="23" /></button></header>
      <div class="image-stage" :class="{ zoomed }">
        <p v-if="failed" role="alert">照片暂时无法加载，请关闭后重新打开。</p>
        <img v-else :src="src" :alt="title" @error="failed = true" />
      </div>
      <footer><span>可放大查看，手机支持双指缩放</span><button type="button" :disabled="failed" :aria-pressed="zoomed" @click="zoomed = !zoomed"><Minimize2 v-if="zoomed" :size="18" /><ZoomIn v-else :size="18" />{{ zoomed ? '适应屏幕' : '放大照片' }}</button></footer>
    </dialog>
  </Teleport>
</template>

<style scoped>
.image-viewer{position:fixed;inset:0;width:min(100vw,1100px);height:100dvh;max-width:100vw;max-height:100dvh;margin:auto;padding:0;border:0;background:#14251e;color:white;overflow:hidden}.image-viewer[open]{display:flex;flex-direction:column}.image-viewer::backdrop{background:#08140ded}.image-viewer header,.image-viewer footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-shrink:0;padding:12px 16px}.image-viewer header{padding-top:max(12px,env(safe-area-inset-top))}.image-viewer strong{font-size:15px}.image-viewer button{display:inline-flex;align-items:center;justify-content:center;gap:7px;min-height:44px;min-width:44px;padding:8px 12px;border-radius:12px;background:#ffffff1c;color:white;font-size:13px}.image-stage{flex:1;min-height:0;overflow:auto;display:flex;align-items:safe center;justify-content:safe center;overscroll-behavior:contain}.image-stage img{display:block;max-width:100%;max-height:100%;object-fit:contain;flex-shrink:0}.image-stage.zoomed{display:block}.image-stage.zoomed img{width:200%;max-width:none;max-height:none;object-fit:initial}.image-stage p{padding:24px;font-size:14px;line-height:1.8}.image-viewer footer{padding-bottom:max(12px,env(safe-area-inset-bottom));font-size:11px;color:#c4d0c5}.image-viewer footer button{white-space:nowrap}@media(max-width:360px){.image-viewer footer{padding-inline:10px;gap:8px}.image-viewer footer span{max-width:130px;line-height:1.7}}
</style>
