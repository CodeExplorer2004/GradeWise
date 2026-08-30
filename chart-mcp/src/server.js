import { createServer } from 'node:http'
import { createMcpHandler, McpServer } from '@modelcontextprotocol/server'
import { toNodeHandler } from '@modelcontextprotocol/node'
import * as echarts from 'echarts'
import { z } from 'zod'

const port = Number(process.env.PORT || 3030)
const serviceToken = process.env.MCP_SERVICE_TOKEN || 'development-mcp-token'
const maxBodyBytes = 150_000
const allowedTopKeys = new Set(['dataset', 'grid', 'legend', 'radar', 'series', 'title', 'tooltip', 'xAxis', 'yAxis'])
const allowedSeries = new Set(['bar', 'line', 'pie', 'radar'])
const forbiddenKeys = new Set(['formatter', 'graphic', 'renderItem', 'toolbox'])

function safeValue(value) {
  if (value === null || ['boolean', 'number'].includes(typeof value)) return true
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase()
    return !['data:', 'file:', 'http:', 'https:', 'javascript:'].some((prefix) => normalized.startsWith(prefix)) && !value.includes('<')
  }
  if (Array.isArray(value)) return value.length <= 1000 && value.every(safeValue)
  if (typeof value === 'object') {
    return Object.entries(value).every(([key, item]) => !forbiddenKeys.has(key) && safeValue(item))
  }
  return false
}

function validateOption(option) {
  if (!option || typeof option !== 'object' || Array.isArray(option)) throw new Error('option 必须是对象')
  if (Object.keys(option).some((key) => !allowedTopKeys.has(key))) throw new Error('包含不允许的顶层配置')
  if (!safeValue(option)) throw new Error('图表配置包含不安全内容')
  const series = option.series
  if (!Array.isArray(series) || !series.length || series.length > 20) throw new Error('series 数量无效')
  if (series.some((item) => !item || !allowedSeries.has(item.type))) throw new Error('图表类型不受支持')
}

function renderSvg(option, width = 1200, height = 700) {
  validateOption(option)
  const safeWidth = Math.max(320, Math.min(2400, Number(width)))
  const safeHeight = Math.max(240, Math.min(1600, Number(height)))
  const chart = echarts.init(null, null, { renderer: 'svg', ssr: true, width: safeWidth, height: safeHeight })
  try {
    chart.setOption(option)
    return chart.renderToSVGString()
  } finally {
    chart.dispose()
  }
}

function buildMcpServer() {
  const server = new McpServer({ name: 'gradewise-chart-mcp', version: '0.1.0' })
  server.registerTool(
    'render_echarts_svg',
    {
      description: '将经过白名单校验的 ECharts option 渲染为 SVG',
      inputSchema: z.object({
        option: z.record(z.string(), z.unknown()),
        width: z.number().min(320).max(2400).default(1200),
        height: z.number().min(240).max(1600).default(700),
      }),
      annotations: { readOnlyHint: true, idempotentHint: true, openWorldHint: false },
    },
    async ({ option, width, height }) => {
      const svg = renderSvg(option, width, height)
      return {
        content: [{ type: 'text', text: JSON.stringify({ mimeType: 'image/svg+xml', svg }) }],
        structuredContent: { mimeType: 'image/svg+xml', svg },
      }
    },
  )
  return server
}

const mcpHandler = toNodeHandler(createMcpHandler(buildMcpServer))

function authorized(request) {
  return request.headers.authorization === `Bearer ${serviceToken}`
}

async function readJson(request) {
  let body = ''
  for await (const chunk of request) {
    body += chunk
    if (Buffer.byteLength(body) > maxBodyBytes) throw new Error('请求体过大')
  }
  return JSON.parse(body || '{}')
}

const httpServer = createServer(async (request, response) => {
  const url = new URL(request.url || '/', `http://${request.headers.host || 'localhost'}`)
  if (url.pathname === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' }).end('{"status":"ok"}')
    return
  }
  if (!authorized(request)) {
    response.writeHead(401, { 'content-type': 'application/json' }).end('{"detail":"unauthorized"}')
    return
  }
  if (url.pathname === '/mcp') {
    await mcpHandler(request, response)
    return
  }
  if (url.pathname === '/render' && request.method === 'POST') {
    try {
      const payload = await readJson(request)
      const svg = renderSvg(payload.option, payload.width, payload.height)
      response.writeHead(200, {
        'content-type': 'image/svg+xml; charset=utf-8',
        'cache-control': 'no-store',
        'x-content-type-options': 'nosniff',
      }).end(svg)
    } catch (error) {
      response.writeHead(422, { 'content-type': 'application/json' }).end(JSON.stringify({ detail: String(error.message || error) }))
    }
    return
  }
  response.writeHead(404, { 'content-type': 'application/json' }).end('{"detail":"not found"}')
})

httpServer.listen(port, '0.0.0.0', () => {
  console.log(`GradeWise chart MCP listening on ${port}`)
})
