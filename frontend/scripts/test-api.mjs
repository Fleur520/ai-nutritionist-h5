import assert from 'node:assert/strict'
import { createServer } from 'vite'

const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' })
const originalFetch = globalThis.fetch
const encoder = new TextEncoder()
const event = (type, data) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`
try {
  const { streamMessage, api } = await server.ssrLoadModule('/src/lib/api.ts')
  const fixtures = []
  const check = async (name, test) => { await test(); fixtures.push(name); console.log(`PASS ${name}`) }
  const mockStream = text => {
    const bytes = encoder.encode(text)
    let offset = 0
    globalThis.fetch = async () => new Response(new ReadableStream({
      pull(controller) {
        // Split every byte, including Chinese UTF-8 characters and SSE boundaries.
        if (offset < bytes.length) controller.enqueue(bytes.slice(offset, ++offset))
        else controller.close()
      },
    }), { headers: { 'Content-Type': 'text/event-stream' } })
  }
  await check('streamed UTF-8 and event boundaries', async () => {
    mockStream(event('delta', { content: '晚餐' }) + event('delta', { content: '建议' }) + event('done', {}))
    let result = ''
    await streamMessage('晚餐怎么吃', 'test', value => { result += value })
    assert.equal(result, '晚餐建议')
  })
  await check('CRLF and multiline SSE data', async () => {
    mockStream('event: delta\r\ndata: {\r\ndata: "content":"你好"}\r\n\r\n' + event('done', {}))
    let result = ''
    await streamMessage('test', 'test', value => { result += value })
    assert.equal(result, '你好')
  })
  await check('interrupted reply keeps readable error', async () => {
    mockStream(event('delta', { content: '部分回复' }))
    await assert.rejects(streamMessage('test', 'test', () => {}), /流式输出中断/)
  })
  await check('empty completed reply is rejected', async () => {
    mockStream(event('done', {}))
    await assert.rejects(streamMessage('test', 'test', () => {}), /没有返回内容/)
  })
  for (const malformed of ['null', '[]', '"text"', '{bad json']) {
    await check(`invalid event payload ${malformed}`, async () => {
      mockStream(`event: delta\ndata: ${malformed}\n\n`)
      await assert.rejects(streamMessage('test', 'test', () => {}), /回复格式异常/)
    })
  }
  await check('server stream error is shown', async () => {
    mockStream(event('error', { message: '模型暂时不可用' }))
    await assert.rejects(streamMessage('test', 'test', () => {}), /模型暂时不可用/)
  })
  await check('unstructured stream error stays readable', async () => {
    mockStream(event('error', { message: { detail: 'upstream failed' } }))
    await assert.rejects(streamMessage('test', 'test', () => {}), /AI 响应失败，请重试/)
  })
  await check('abort signal reaches the request', async () => {
    const controller = new AbortController()
    controller.abort()
    globalThis.fetch = async (_url, init) => {
      assert.equal(init.signal, controller.signal)
      init.signal.throwIfAborted()
    }
    await assert.rejects(streamMessage('test', 'test', () => {}, controller.signal), { name: 'AbortError' })
  })
  await check('field validation errors use readable Chinese', async () => {
    globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'age'], type: 'greater_than_equal', ctx: { ge: 18 } }] }), { status: 422 })
    await assert.rejects(api('/profile'), /年龄：不能小于 18/)
  })
  await check('unstructured service errors stay readable', async () => {
    globalThis.fetch = async () => new Response('unavailable', { status: 503 })
    await assert.rejects(api('/profile'), /服务暂时没有响应/)
  })
  console.log(`${fixtures.length} API and streaming checks passed`)
} finally {
  globalThis.fetch = originalFetch
  await server.close()
}
