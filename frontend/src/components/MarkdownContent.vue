<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../lib/markdown'
const props = defineProps<{ content: string }>()
const rendered = computed(() => renderMarkdown(props.content))
</script>
<template><div class="markdown-content" v-html="rendered"></div></template>
<style scoped>
.markdown-content{color:inherit;font-size:15px;line-height:1.85;overflow-wrap:anywhere;word-break:normal;white-space:normal}
.markdown-content :deep(> :first-child){margin-top:0}.markdown-content :deep(> :last-child){margin-bottom:0}
.markdown-content :deep(p){margin:0 0 12px}
.markdown-content :deep(h1),.markdown-content :deep(h2),.markdown-content :deep(h3),.markdown-content :deep(h4),.markdown-content :deep(h5),.markdown-content :deep(h6){color:#234f3c;font-weight:750;line-height:1.5;margin:22px 0 10px;letter-spacing:-.25px}
.markdown-content :deep(h1){font-size:21px}.markdown-content :deep(h2){font-size:19px}.markdown-content :deep(h3){font-size:17px}.markdown-content :deep(h4),.markdown-content :deep(h5),.markdown-content :deep(h6){font-size:15px}
.markdown-content :deep(strong){font-weight:750;color:#264f3c}
.markdown-content :deep(ul),.markdown-content :deep(ol){padding-left:23px;margin:10px 0 15px}.markdown-content :deep(ul){list-style:disc}.markdown-content :deep(ol){list-style:decimal}.markdown-content :deep(li){margin:6px 0;padding-left:2px}.markdown-content :deep(li::marker){color:#54866c;font-weight:650}.markdown-content :deep(li > p){margin:0 0 6px}.markdown-content :deep(li ul),.markdown-content :deep(li ol){margin:5px 0}
.markdown-content :deep(blockquote){margin:16px 0;padding:10px 13px;border-left:3px solid #a4c3aa;border-radius:0 10px 10px 0;background:#f0f5ef;color:#607769}.markdown-content :deep(blockquote > :last-child){margin-bottom:0}
.markdown-content :deep(a){color:#276a4c;text-decoration:underline;text-decoration-color:#9bc5a7;text-underline-offset:3px}
.markdown-content :deep(code){background:#f0f3ed;color:#526a55;padding:2px 5px;border-radius:5px;font-size:.88em;font-family:ui-monospace,SFMono-Regular,Consolas,monospace}
.markdown-content :deep(pre){overflow-x:auto;max-width:100%;padding:14px;border:1px solid #e4e9e0;border-radius:12px;background:#f6f7f2;margin:14px 0;white-space:pre;line-height:1.65}.markdown-content :deep(pre code){padding:0;background:transparent;font-size:12px}
.markdown-content :deep(.markdown-table-scroll){width:100%;overflow-x:auto;margin:16px 0;border:1px solid #e1e8de;border-radius:11px;-webkit-overflow-scrolling:touch}.markdown-content :deep(table){border-collapse:collapse;width:100%;min-width:280px;font-size:13px;line-height:1.65}.markdown-content :deep(th),.markdown-content :deep(td){padding:10px 11px;border-bottom:1px solid #e5ebe1;text-align:left;min-width:82px}.markdown-content :deep(th){background:#edf4ea;color:#3e644b;font-weight:700}.markdown-content :deep(tr:last-child td){border-bottom:0}
.markdown-content :deep(hr){border:0;border-top:1px solid #e3e9df;margin:22px 0}.markdown-content :deep(.markdown-image-note){color:#849186;font-size:13px}
@media(max-width:359px){.markdown-content{font-size:14px}}
</style>
