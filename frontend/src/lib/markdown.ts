import MarkdownIt from 'markdown-it'

// Model output is untrusted: disable raw HTML, restrict links and keep remote
// images as text so rendering a reply never requests third-party resources.
const markdown = new MarkdownIt({ html: false, breaks: true, linkify: true, typographer: false })
markdown.validateLink = (href: string) => {
  try { return ['http:', 'https:', 'mailto:'].includes(new URL(href).protocol) }
  catch { return false }
}
const defaultLinkOpen = markdown.renderer.rules.link_open
markdown.renderer.rules.link_open = (tokens, index, options, env, self) => {
  tokens[index].attrSet('target', '_blank')
  tokens[index].attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen?.(tokens, index, options, env, self) ?? self.renderToken(tokens, index, options)
}
markdown.renderer.rules.image = (tokens, index) => `<span class="markdown-image-note">[${markdown.utils.escapeHtml(tokens[index].content.trim() || '图片')}]</span>`
markdown.renderer.rules.table_open = () => '<div class="markdown-table-scroll" tabindex="0" aria-label="可横向滚动的表格"><table>\n'
markdown.renderer.rules.table_close = () => '</table></div>\n'
export function renderMarkdown(content: string): string { return markdown.render(content) }
