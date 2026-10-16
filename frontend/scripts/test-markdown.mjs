import assert from 'node:assert/strict'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
try {
  const { renderMarkdown } = await server.ssrLoadModule('/src/lib/markdown.ts')
  const fixtures = [
    ['headings and emphasis', '### 晚餐建议\n\n**均衡搭配**，少油少盐。', html => html.includes('<h3>晚餐建议</h3>') && html.includes('<strong>均衡搭配</strong>')],
    ['lists and quote', '- 蔬菜\n- 蛋白质\n\n1. 定时吃饭\n2. 适量运动\n\n> 循序渐进', html => ['<ul>', '<ol>', '<blockquote>'].every(tag => html.includes(tag))],
    ['table overflow wrapper', '| 食物 | 重量 |\n| --- | --- |\n| 米饭 | 100g |', html => html.includes('class="markdown-table-scroll"') && html.includes('<table>') && html.includes('<th>食物</th>')],
    ['code escaping', '```html\n<script>alert(1)</script>\n```', html => html.includes('<pre><code') && html.includes('&lt;script&gt;') && !html.includes('<script>')],
    ['raw HTML is inert', '<script>globalThis.pwned=true</script><img src=x onerror="alert(1)">', html => !/<script\b|<img\b/i.test(html) && html.includes('&lt;script&gt;')],
    ['unsafe protocols rejected', '[click](javascript:alert(1)) [data](data:text/html,bad) [vb](vbscript:bad)', html => !html.includes('<a ')],
    ['encoded unsafe protocols rejected', '[click](javascript&#58;alert(1)) [data](data&#58;text/html,bad)', html => !html.includes('<a ')],
    ['remote images stay text', '![远程图片](https://example.com/tracker.png)', html => !html.includes('<img') && !html.includes('tracker.png') && html.includes('远程图片')],
    ['image labels escaped', '![<img src=x onerror=alert(1)>](https://example.com/tracker.png)', html => !html.includes('<img') && html.includes('&lt;img')],
    ['safe links protected', '[来源](https://example.com/foods)', html => html.includes('href="https://example.com/foods"') && html.includes('rel="noopener noreferrer"') && html.includes('target="_blank"')],
    ['protocol relative links rejected', '[relative](//example.com/x)', html => !html.includes('<a ')],
    ['unfinished streamed markdown remains safe', '**正在生成\n\n<script>alert(1)</script>\n\n![x](javascript:alert(1)', html => !/<script\b|<img\b/i.test(html)],
  ]
  for (const [name, input, validate] of fixtures) {
    assert.ok(validate(renderMarkdown(input)), name)
    console.log(`PASS ${name}`)
  }
  console.log(`${fixtures.length} Markdown rendering and safety checks passed`)
} finally {
  await server.close()
}
