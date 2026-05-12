import { useEffect, useMemo, useRef, useState } from 'react'
import { Copy, RotateCcw, Quote, Pencil, GitBranch, ShieldCheck, FileText, FileCode, FileSpreadsheet, FileImage, ChevronDown, ChevronUp, Cpu, Zap, Timer, ThumbsUp, ThumbsDown, GitFork } from 'lucide-react'
import { Message, useChatStore, type ExecutionGraphData, type ToolCallBlock } from '../store/chat'
import { getTraceVisibility } from '../store/theme'
import { apiBranchConversation, apiGetMessages, apiPatchMessage, apiSubmitFeedback, apiGetMessageVersions, type ReasoningStep } from '../api/client'
import { useAuthStore } from '../store/auth'
import MarkdownMessage from './MarkdownMessage'
import MultiQuestionCards from './MultiQuestionCards'
import { parseMultiQuestionCards } from '../utils/parseMultiQuestion'
import ReasoningChain from './ReasoningChain'
import ExecutionGraphPanel from './ExecutionGraphPanel'
import DagTimeline, { type DagTimelineItem } from './DagTimeline'
import MessageVersionTree from './MessageVersionTree'
import { CardShell } from './CardShell'
import { DarkPanel } from './ui/DarkPanel'
import { t } from '../i18n'
import DataTableChart from './DataTableChart'

function stripJsonBlocks(content: string): string {
  let result = content
  // Remove fenced JSON code blocks
  result = result.replace(/```json\s*[\s\S]*?```/gi, '')
  // Remove fenced code blocks that look like JSON
  result = result.replace(/```\s*(\{[\s\S]*?\}|\[[\s\S]*?\])\s*```/g, '')
  // Remove leading standalone JSON object/array
  const trimmed = result.trim()
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    let depth = 0
    let end = 0
    for (let i = 0; i < trimmed.length; i++) {
      const ch = trimmed[i]
      if (ch === '{' || ch === '[') depth++
      else if (ch === '}' || ch === ']') {
        depth--
        if (depth === 0) { end = i + 1; break }
      }
    }
    if (end > 0) {
      result = trimmed.substring(end).trim()
    }
  }
  // Remove trailing JSON array of objects (e.g. [{"col":"val"}])
  result = _stripTrailingJsonArray(result)
  // Remove inline standalone JSON objects mid-text (e.g. {"type":"turn",...})
  result = _stripInlineJsonObjects(result)
  return result.trim()
}

function _isStandaloneJson(s: string): boolean {
  const t = s.trim()
  if (!(t.startsWith('{') || t.startsWith('['))) return false
  try {
    JSON.parse(t)
    return true
  } catch {
    return false
  }
}

function _stripInlineJsonObjects(content: string): string {
  // Find balanced JSON objects/arrays that appear mid-text on their own lines
  // and remove them if they parse as valid JSON
  let result = content
  // Pattern: a line (or multi-line block bounded by balanced braces/brackets) that is valid JSON
  const lines = result.split('\n')
  const out: string[] = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i].trim()
    if ((line.startsWith('{') || line.startsWith('[')) && _isStandaloneJson(line)) {
      // Check if it's a single-line JSON value
      try {
        const parsed = JSON.parse(line)
        if (parsed && typeof parsed === 'object') {
          // It's a standalone JSON object/array — skip it
          i++
          continue
        }
      } catch {}
    }
    // Check for multi-line JSON block starting on this line
    if (line.startsWith('{') || line.startsWith('[')) {
      let depth = 0
      let j = i
      let found = false
      const blockLines: string[] = []
      for (; j < lines.length; j++) {
        blockLines.push(lines[j])
        for (let k = 0; k < lines[j].length; k++) {
          const ch = lines[j][k]
          if (ch === '{' || ch === '[') depth++
          else if (ch === '}' || ch === ']') {
            depth--
            if (depth === 0 && j > i) { found = true; break }
          }
        }
        if (found) break
      }
      if (found) {
        const candidate = blockLines.join('\n')
        try {
          JSON.parse(candidate)
          // Valid JSON block — skip all these lines
          i = j + 1
          continue
        } catch {}
      }
    }
    out.push(lines[i])
    i++
  }
  return out.join('\n')
}

function _stripTrailingJsonArray(content: string): string {
  const trimmed = content.trimEnd()
  if (!trimmed.endsWith(']')) return trimmed
  let depth = 0
  let start = -1
  for (let i = trimmed.length - 1; i >= 0; i--) {
    if (trimmed[i] === ']') depth++
    else if (trimmed[i] === '[') {
      depth--
      if (depth === 0) { start = i; break }
    }
  }
  if (start >= 0) {
    const candidate = trimmed.substring(start)
    try {
      const parsed = JSON.parse(candidate)
      if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((item: any) => typeof item === 'object' && item !== null && !Array.isArray(item))) {
        return trimmed.substring(0, start).trim()
      }
    } catch { /* not valid JSON */ }
  }
  return trimmed
}

function _extractBalancedJsonArray(content: string): string | null {
  const trimmed = content.trim()
  // Walk backward from end to find a balanced [...] pair
  if (!trimmed.endsWith(']')) return null
  let depth = 0
  let start = -1
  for (let i = trimmed.length - 1; i >= 0; i--) {
    if (trimmed[i] === ']') depth++
    else if (trimmed[i] === '[') {
      depth--
      if (depth === 0) { start = i; break }
    }
  }
  if (start >= 0) {
    const candidate = trimmed.substring(start)
    try {
      JSON.parse(candidate)
      return candidate
    } catch { /* skip */ }
  }
  return null
}

function parseEpistemicMeta(messageText: string): { level?: string; issues: string[] } {
  const match = messageText.match(/^([📊📄🔗🧠💡⚠️])\s+/)
  const emoji = match?.[1]
  const level = emoji === '📊'
    ? 'FACT'
    : emoji === '📄'
      ? 'DOCUMENT'
      : emoji === '🔗'
        ? 'SEARCH'
        : emoji === '🧠'
          ? 'MEMORY'
          : emoji === '💡'
            ? 'INFERENCE'
            : emoji === '⚠️'
              ? 'SPECULATION'
              : undefined

  const issues: string[] = []
  const issueSection = messageText.match(/epistemic_issues[:：]\s*([\s\S]{0,300})/i)
  if (issueSection?.[1]) {
    issues.push(issueSection[1].trim())
  }
  return { level, issues }
}

function levelBadge(level?: string) {
  if (!level) return null
  const cls = level === 'FACT'
    ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
    : level === 'DOCUMENT'
      ? 'bg-sky-100 text-sky-700 border-sky-200'
      : level === 'SEARCH'
        ? 'bg-indigo-100 text-indigo-700 border-indigo-200'
        : level === 'INFERENCE'
          ? 'bg-amber-100 text-amber-700 border-amber-200'
          : 'bg-zinc-100 text-zinc-700 border-zinc-200'
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold ${cls}`}>{level}</span>
}

function tryParseToolCard(content: string): { type: 'time' | 'weather' | 'table' | 'data' | 'agent'; data: any } | null {
  const candidates = [content.trim()]

  const fenceMatch = content.match(/```(?:json)?\s*([\s\S]*?)```/i)
  if (fenceMatch?.[1]) candidates.unshift(fenceMatch[1].trim())

  const objectMatch = content.match(/\{[\s\S]*\}/)
  if (objectMatch?.[0]) candidates.unshift(objectMatch[0].trim())

  // Extract the first balanced JSON object — robust against brace chars
  // appearing later in natural-language text.
  const trimmed = content.trim()
  if (trimmed.startsWith('{')) {
    let depth = 0
    let end = 0
    for (let i = 0; i < trimmed.length; i++) {
      if (trimmed[i] === '{') depth++
      else if (trimmed[i] === '}') {
        depth--
        if (depth === 0) { end = i + 1; break }
      }
    }
    if (end > 0) {
      const balanced = trimmed.substring(0, end)
      if (balanced !== candidates[0] && balanced !== candidates[1]) {
        candidates.unshift(balanced)
      }
    }
  }

  const normalizeWeather = (parsed: any) => {
    const current = parsed?.current && typeof parsed.current === 'object' ? parsed.current : {}
    const forecast = Array.isArray(parsed?.forecast) ? parsed.forecast : []
    const humidity = current.humidity ?? parsed?.humidity
    const windSpeed = current.wind_speed ?? parsed?.wind_speed
    const windDirection = current.wind_direction ?? parsed?.wind_direction
    const temperature = current.temperature ?? parsed?.temperature
    const weather = current.condition ?? parsed?.weather
    const feelsLike = current.feels_like ?? parsed?.feels_like
    const pressure = current.pressure ?? parsed?.pressure
    const cloudiness = current.cloudiness ?? parsed?.cloudiness
    const visibility = current.visibility ?? parsed?.visibility
    const sunrise = current.sunrise ?? parsed?.sunrise
    const sunset = current.sunset ?? parsed?.sunset
    return {
      type: 'weather',
      city: parsed?.location || parsed?.city || '天气',
      summary: parsed?.summary || parsed?.overview || parsed?.description || '',
      overview: parsed?.overview || '',
      feels_like_text: parsed?.feels_like_text || '',
      outfit_advice: parsed?.outfit_advice || '',
      travel_advice: parsed?.travel_advice || '',
      risk_alert: parsed?.risk_alert || '',
      activity_suggestion: parsed?.activity_suggestion || '',
      keep_suggestion: parsed?.keep_suggestion || '',
      temperature,
      feels_like: feelsLike,
      weather,
      humidity,
      pressure,
      wind_speed: windSpeed,
      wind_direction: windDirection,
      cloudiness,
      visibility,
      sunrise,
      sunset,
      forecast,
      raw: parsed,
    }
  }

  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate)
      // Detect raw result arrays of plain objects → table
      if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((item: any) => typeof item === 'object' && item !== null && !Array.isArray(item))) {
        const columns = Object.keys(parsed[0])
        return { type: 'table', data: { type: 'table', columns, rows: parsed } }
      }
      if (parsed && typeof parsed === 'object') {
        if (parsed.type === 'time' || parsed.time || parsed.timestamp || parsed.displayTime) return { type: 'time', data: parsed }
        if ((parsed.city || parsed.location || parsed.current) && (parsed.temperature !== undefined || parsed.weather || parsed.current)) return { type: 'weather', data: normalizeWeather(parsed) }
        if (parsed.type === 'table' && Array.isArray(parsed.rows)) return { type: 'table', data: parsed }
        // Data query results: objects with sql field
        if (typeof parsed.sql === 'string' && parsed.sql.trim()) {
          const rows = Array.isArray(parsed.rows) ? parsed.rows : []
          return { type: 'data', data: { sql: parsed.sql, rows, row_count: parsed.row_count ?? rows.length } }
        }
        // Tool/agent results: objects with agent_type or tool_name
        if (typeof parsed.agent_type === 'string') return { type: 'agent', data: parsed }
        if (typeof parsed.tool_name === 'string') return { type: 'agent', data: parsed }
        if (parsed.type === 'turn' || parsed.type === 'agent_result') return { type: 'agent', data: parsed }
      }
    } catch {
      // ignore non-json content
    }
  }

  // Detect raw JSON array of objects as table (e.g. [{"col":"val"}, ...])
  const arrayCandidate = _extractBalancedJsonArray(content)
  if (arrayCandidate) {
    try {
      const parsed = JSON.parse(arrayCandidate)
      if (Array.isArray(parsed) && parsed.length > 0 && parsed.every((item: any) => typeof item === 'object' && item !== null && !Array.isArray(item))) {
        const columns = Object.keys(parsed[0])
        return { type: 'table', data: { type: 'table', columns, rows: parsed } }
      }
    } catch { /* skip */ }
  }

  const looseTimeMatch = content.match(/(?:current\s+time|\btime\b|当前时间|现在时间)[:：\s\-]*([0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?)/i)
  if (looseTimeMatch?.[1]) {
    return {
      type: 'time',
      data: {
        type: 'time',
        displayTime: looseTimeMatch[1],
        time: looseTimeMatch[1],
      },
    }
  }

  return null
}

function parseTimeFromData(data: any): Date | null {
  const candidates = [data?.timestamp, data?.iso, data?.dateTime, data?.datetime, data?.time].filter(Boolean)
  for (const candidate of candidates) {
    if (candidate instanceof Date && !Number.isNaN(candidate.getTime())) return candidate
    const parsed = new Date(String(candidate))
    if (!Number.isNaN(parsed.getTime())) return parsed
  }
  return null
}

function formatClockTime(date: Date | null, fallback: string) {
  if (!date) return fallback || '—'
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

function formatTimeLabel(data: any, fallback: string) {
  return String(data?.displayTime || data?.formattedTime || data?.time || fallback || '')
}

function formatTimeLocation(data: any) {
  const pieces = [data?.location, data?.city, data?.timezoneLabel, data?.timezone].filter(Boolean)
  return pieces.length ? String(pieces[0]) : ''
}

function formatBeijingLabel(value: any) {
  const normalized = normalizeTimezoneLabel(value)
  if (!normalized) return ''
  return normalized === 'Beijing' ? 'Beijing' : normalized
}

function formatTimeSubtitle(data: any) {
  return String(data?.subtitle || data?.description || data?.detail || data?.summary || '')
}

function formatOffset(data: any) {
  const raw = data?.offset ?? data?.utcOffset ?? data?.timezoneOffset ?? data?.relativeOffset
  if (raw === undefined || raw === null || raw === '') return ''
  const text = String(raw)
  if (/^[+-]?\d+$/.test(text)) {
    const hours = Number(text)
    const sign = hours >= 0 ? '+' : ''
    return `UTC${sign}${hours}`
  }
  return text
}

function normalizeTimezoneLabel(value: any) {
  const text = String(value ?? '').trim()
  if (!text) return ''

  const normalized = text
    .replace(/^Asia\/Shanghai$/i, 'Beijing')
    .replace(/^Shanghai(?:,?\s*China)?$/i, 'Beijing')
    .replace(/^UTC\s*\+?8(?:[:：]00)?$/i, 'Beijing')

  return normalized
}

function formatCountLabel(label: string, value: any) {
  if (value === undefined || value === null || value === '') return null
  return `${label} ${value}`
}

function formatWindDirection(value: any) {
  if (value === undefined || value === null || value === '') return ''
  const text = String(value).trim()
  if (/^\d+(?:\.\d+)?°?$/.test(text)) return `${text.replace(/°?$/, '')}°`
  return text
}

function formatUnixTime(value: any) {
  if (value === undefined || value === null || value === '') return ''
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  return new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(n * 1000))
}

function WeatherCard({ data }: { data: any }) {
  const windDirection = formatWindDirection(data?.wind_direction)
  const temperature = data?.temperature
  const feelsLike = data?.feels_like
  const humidity = data?.humidity
  const pressure = data?.pressure
  const windSpeed = data?.wind_speed
  const cloudiness = data?.cloudiness
  const visibility = data?.visibility
  const sunrise = formatUnixTime(data?.sunrise)
  const sunset = formatUnixTime(data?.sunset)
  const condition = String(data?.weather || data?.current?.condition || '天气情况未知')
  const summary = String(data?.summary || data?.overview || `${data?.city || '该地区'}天气信息如下。`)

  const weatherEmoji = (() => {
    const text = `${condition} ${summary}`.toLowerCase()
    if (/(雷|暴雨|storm|thunder)/.test(text)) return '⛈️'
    if (/(雪|冰|霜|hail|sleet)/.test(text)) return '🌨️'
    if (/(雨|阵雨|drizzle|rain)/.test(text)) return '🌧️'
    if (/(雾|霾|haze|fog|smog)/.test(text)) return '🌫️'
    if (/(云|阴|overcast|cloud)/.test(text)) return '☁️'
    if (/(晴|clear|sunny|sun)/.test(text)) return '☀️'
    return '🌤️'
  })()

  const llmHighlights = [
    data?.overview && { label: '总体概述', value: data.overview },
    data?.feels_like_text && { label: '体感', value: data.feels_like_text },
    data?.outfit_advice && { label: '穿衣建议', value: data.outfit_advice },
    data?.travel_advice && { label: '出行建议', value: data.travel_advice },
    data?.activity_suggestion && { label: '活动建议', value: data.activity_suggestion },
    data?.risk_alert && { label: '提醒', value: data.risk_alert },
  ].filter(Boolean) as Array<{ label: string; value: string }>

  const recommendation = data?.keep_suggestion
    || data?.llm_recommendation
    || [
      temperature !== undefined && temperature !== null ? `当前气温 ${temperature}°C` : '当前气温暂未获取',
      feelsLike !== undefined && feelsLike !== null ? `体感约 ${feelsLike}°C` : null,
      humidity !== undefined && humidity !== null ? `湿度 ${humidity}%` : null,
      windSpeed !== undefined && windSpeed !== null ? `风速 ${windSpeed} m/s` : null,
    ].filter(Boolean).join('，')

  return (
    <CardShell
      eyebrow="WEATHER"
      title={String(data?.city || '天气')}
      meta={summary}
      accent="from-sky-500/45 via-cyan-400/25 to-emerald-300/20"
    >
      <div className="space-y-4">
        <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-4">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="inline-flex items-center rounded-full border border-[var(--border)] bg-[var(--surface)] px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.22em] text-[var(--text-secondary)]">
                当前天气
              </div>
              <div className="mt-2 flex items-center gap-2 text-[22px] font-semibold leading-tight text-[var(--text)]">
                <span aria-hidden="true">{weatherEmoji}</span>
                <span className="truncate">{condition}</span>
              </div>
              <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{summary}</p>
            </div>
            <div className="flex-shrink-0 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-right">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">气温</div>
              <div className="mt-1 text-4xl font-semibold leading-none text-[var(--text)]">
                {temperature ?? '—'}
                <span className="text-xl">{temperature !== undefined && temperature !== null ? '°C' : ''}</span>
              </div>
              {feelsLike !== undefined && feelsLike !== null ? <div className="mt-1 text-xs text-[var(--text-secondary)]">体感 {feelsLike}°C</div> : null}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          {[
            ['湿度', humidity, '%'],
            ['气压', pressure, ' hPa'],
            ['风速', windSpeed, ' m/s'],
            ['风向', windDirection || '-', ''],
            ['云量', cloudiness, '%'],
            ['可见度', visibility, ' m'],
            ['日出', sunrise || '-', ''],
            ['日落', sunset || '-', ''],
          ].map(([label, value, unit]) => (
            <div key={String(label)} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">
              <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">{label}</div>
              <div className="mt-1 text-[var(--text)]">{value ?? '-'}{value !== undefined && value !== null && value !== '-' ? unit : ''}</div>
            </div>
          ))}
        </div>

        {llmHighlights.length > 0 ? (
          <div className="grid gap-3 md:grid-cols-2">
            {llmHighlights.map((item) => (
              <div key={item.label} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm leading-6 text-[var(--text)]">
                <span className="text-[var(--text-secondary)]">{item.label}：</span>
                <span>{item.value}</span>
              </div>
            ))}
          </div>
        ) : null}

        <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-sm leading-6 text-[var(--text)]">
          <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">推荐补充</div>
          <div className="mt-1">{recommendation}</div>
        </div>

        {Array.isArray(data?.forecast) && data.forecast.length > 0 ? (
          <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
            <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">未来预报</div>
            <div className="mt-2 space-y-2 text-sm">
              {data.forecast.slice(0, 3).map((item: any, idx: number) => (
                <div key={`${item.date || idx}`} className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2">
                  <span className="whitespace-nowrap text-[var(--text-secondary)]">{String(item.date || `第${idx + 1}天`)}</span>
                  <span className="text-right text-[var(--text)]">{[item.condition, item.low !== undefined || item.high !== undefined ? `${item.low ?? '-'}℃ ~ ${item.high ?? '-'}℃` : ''].filter(Boolean).join('，')}</span>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </CardShell>
  )
}

export default function ChatMessage({ message }: { message: Message }) {
  const activeId = useChatStore((s) => s.activeId)
  const showReasoning = getTraceVisibility('reasoning')
  const showDag = getTraceVisibility('dag')
  const showExecutionGraph = getTraceVisibility('executionGraph')
  const showDecisionTrace = getTraceVisibility('decisionTrace')
  const showFlowCards = getTraceVisibility('flowCards')
  const messages = useChatStore((s) => (activeId ? s.messages[activeId] ?? [] : []))
  const steps = useChatStore((s) => {
    if (!activeId || message.role !== 'assistant') return message.reasoning_steps ?? []
    return s.getReasoningStepsForMessage(activeId, message.id)
  })
  const executionGraph = useChatStore((s) => {
    if (!activeId || message.role !== 'assistant') return message.execution_graph ?? null
    return s.getExecutionGraphForMessage(activeId, message.id) ?? message.execution_graph ?? null
  })

  const isLastAssistant = useMemo(() => {
    if (message.role !== 'assistant') return false
    const assistants = messages.filter((m) => m.role === 'assistant')
    return assistants.length > 0 && assistants[assistants.length - 1].id === message.id
  }, [messages, message.id, message.role])

  if (message.role === 'user') {
    return <UserMessage message={message} />
  }

  if (message.status === 'streaming') {
    return <StreamingMessage text={message.streamText} />
  }

  return (
    <FinalMessage
      message={message}
      steps={steps}
      executionGraph={executionGraph}
      showRegenerate={isLastAssistant}
    />
  )
}

function fileIcon(ext: string | undefined) {
  if (!ext) return <FileText size={16} />
  const e = ext.toLowerCase()
  if (['pdf'].includes(e)) return <FileText size={16} className="text-red-500" />
  if (['doc', 'docx'].includes(e)) return <FileText size={16} className="text-blue-500" />
  if (['xls', 'xlsx', 'csv', 'tsv'].includes(e)) return <FileSpreadsheet size={16} className="text-green-600" />
  if (['py', 'js', 'ts', 'tsx', 'jsx', 'go', 'rs', 'java', 'c', 'cpp', 'sh', 'sql', 'yaml', 'yml', 'json', 'toml'].includes(e)) return <FileCode size={16} className="text-purple-500" />
  if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp'].includes(e)) return <FileImage size={16} className="text-orange-500" />
  return <FileText size={16} />
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function UserMessage({ message }: { message: Message }) {
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(message.finalText)

  const quote = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:prefill', {
        detail: { text: `> ${message.finalText}\n`, autoSend: false },
      })
    )
  }

  const copy = async () => {
    await navigator.clipboard.writeText(message.finalText)
  }

  const save = () => {
    const text = value.trim()
    if (!text || text === message.finalText) {
      setEditing(false)
      return
    }
    setEditing(false)
    window.dispatchEvent(
      new CustomEvent('opentrace:regen', {
        detail: {
          mode: 'edit-regenerate',
          messageId: message.id,
          newContent: text,
        },
      })
    )
  }

  return (
    <div className="flex flex-col items-end gap-2">
      {/* File attachment cards — above the question bubble */}
      {message.attachments && message.attachments.length > 0 && (
        <div className="flex flex-col gap-1.5 w-full max-w-[85%]">
          {message.attachments.map((att) => (
            <div
              key={att.id}
              className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface)] px-4 py-2.5 shadow-sm"
            >
              <div className="shrink-0">
                {fileIcon(att.file_extension)}
              </div>
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium text-[var(--text)] truncate">
                  {att.filename}
                </div>
                <div className="text-[11px] text-[var(--text-secondary)] mt-0.5">
                  {formatSize(att.file_size)}
                  {att.content_summary ? ` · ${att.content_summary}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Text bubble */}
      <div className="max-w-[85%] rounded-3xl border border-[var(--border)] bg-[var(--surface)] px-5 py-3 text-[15px] leading-relaxed text-[var(--text)] shadow-[0_10px_30px_rgba(0,0,0,0.08)]">
        {editing ? (
          <div className="space-y-2">
            <textarea
              value={value}
              onChange={(e) => setValue(e.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2 text-sm text-[var(--text)]"
              rows={3}
            />
            <div className="flex gap-2 justify-end text-xs">
              <button onClick={() => setEditing(false)} className="rounded px-2 py-1 bg-[var(--bg-secondary)] text-[var(--text-secondary)]">
                取消
              </button>
              <button onClick={save} className="rounded px-2 py-1 bg-[var(--accent)] text-white">
                保存并重生成
              </button>
            </div>
          </div>
        ) : (
          <>
            <div>{message.finalText}</div>
            <div className="mt-2 flex items-center gap-2 opacity-80">
              <button onClick={copy} className="p-1 hover:opacity-100" title="复制">
                <Copy size={14} />
              </button>
              <button onClick={quote} className="p-1 hover:opacity-100" title="引用到输入框">
                <Quote size={14} />
              </button>
              <button onClick={() => setEditing(true)} className="p-1 hover:opacity-100" title="编辑并重生成">
                <Pencil size={14} />
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function DecisionTraceCard({ executionGraph, annotations }: { executionGraph: ExecutionGraphData | null; annotations?: Array<any> }) {
  const [expanded, setExpanded] = useState(false)
  const state = (executionGraph?.state || {}) as any
  const taskModel = state?.task_model || {}
  const confirmedFacts = Number(taskModel?.confirmed_facts_count || 0)
  const hypotheses = Number(taskModel?.hypotheses_count || 0)
  const replan = Boolean(taskModel?.replan_triggered)
  const avgConfidence = (() => {
    const arr = (annotations || [])
      .map((a: any) => Number(a?.annotation?.confidence))
      .filter((v: number) => Number.isFinite(v))
    if (!arr.length) return null
    return Math.round((arr.reduce((x: number, y: number) => x + y, 0) / arr.length) * 100)
  })()
  const sourceRatio = (() => {
    const arr = (annotations || []).map((a: any) => String(a?.annotation?.source_type || '')).filter(Boolean)
    if (!arr.length) return { db: 0, doc: 0, web: 0 }
    const total = arr.length
    const db = arr.filter((x: string) => x === 'database').length
    const doc = arr.filter((x: string) => x === 'document').length
    const web = arr.filter((x: string) => x === 'web_search').length
    return {
      db: Math.round((db / total) * 100),
      doc: Math.round((doc / total) * 100),
      web: Math.round((web / total) * 100),
    }
  })()
  const topCitations = (annotations || [])
    .flatMap((a: any) => a?.annotation?.citations || [])
    .slice(0, 5)

  return (
    <CardShell
      eyebrow="TRACE"
      title="决策追溯"
      meta="系统依据、证据与重规划状态"
      accent="from-slate-400/60 via-zinc-300/40 to-stone-200/30"
      className="mb-3 overflow-hidden"
    >
      <div className="grid grid-cols-2 gap-2 text-xs text-[var(--text-secondary)] md:grid-cols-3">
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">已确认事实</span><div className="mt-1 text-sm text-[var(--text)]">{confirmedFacts}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">假设数量</span><div className="mt-1 text-sm text-[var(--text)]">{hypotheses}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">重规划</span><div className="mt-1 text-sm text-[var(--text)]">{replan ? '是' : '否'}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">综合置信度</span><div className="mt-1 text-sm text-[var(--text)]">{avgConfidence !== null ? `${avgConfidence}%` : '—'}</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">DB 证据</span><div className="mt-1 text-sm text-[var(--text)]">{sourceRatio.db}%</div></div>
        <div className="rounded-2xl bg-[var(--bg-secondary)] px-3 py-2"><span className="text-[var(--text-secondary)]">Doc / Web</span><div className="mt-1 text-sm text-[var(--text)]">{sourceRatio.doc}% / {sourceRatio.web}%</div></div>
      </div>
      {topCitations.length > 0 ? (
        <div className="mt-4">
          <button
            type="button"
            className="text-xs text-[var(--text-secondary)] underline decoration-[var(--border)] underline-offset-2 hover:text-[var(--text)]"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? '收起证据明细' : '展开证据明细'}
          </button>
          {expanded ? (
            <div className="mt-2 space-y-2 text-xs text-white/78">
              {topCitations.map((c: any, idx: number) => (
                <div key={`${c.id || idx}`} className="rounded-2xl border border-white/10 bg-white/5 px-3 py-2">
                  <div className="font-medium text-white">{idx + 1}. {c.source_name || '来源'}</div>
                  {c.snippet ? <div className="mt-1 text-white/58">{String(c.snippet).slice(0, 120)}</div> : null}
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </CardShell>
  )
}

function StreamingMessage({ text }: { text: string }) {
  const stripped = useMemo(() => {
    try { return stripJsonBlocks(text) } catch { return text }
  }, [text])
  const visibleText = stripped || ' '
  return (
    <div className="flex items-start gap-3">
      <span className="mt-2 inline-block h-2.5 w-2.5 flex-shrink-0 rounded-full bg-black/90 animate-pulse shadow-[0_0_0_1px_rgba(0,0,0,0.08)]" aria-hidden="true" />
      <div className="min-w-0 flex-1 text-[15px] leading-relaxed text-[var(--text)]">
        <span className="whitespace-pre-wrap break-words">
          {visibleText}
          <span className="ml-0.5 inline-block h-[1.05em] w-[1px] translate-y-[2px] bg-black/90 animate-pulse" aria-hidden="true" />
        </span>
      </div>
    </div>
  )
}

function TimeCard({ data }: { data: any }) {
  const parsedDate = parseTimeFromData(data)
  const [now, setNow] = useState(() => parsedDate ?? new Date())

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const currentDate = now
  const timeText = formatClockTime(currentDate, '—')
  const dateText = currentDate.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).replaceAll('/', '-')
  const timezoneText = formatBeijingLabel(data?.timezoneLabel || data?.timezone || data?.location || data?.city)
  const subtitle = formatTimeSubtitle(data)
  const offset = formatOffset(data)
  const hour = currentDate.getHours() % 12
  const minute = currentDate.getMinutes()
  const second = currentDate.getSeconds()
  const hourAngle = hour * 30 + minute * 0.5 + second * (0.5 / 60)
  const minuteAngle = minute * 6 + second * 0.1
  const secondAngle = second * 6

  return (
    <DarkPanel accent="from-zinc-200/80 via-zinc-100/60 to-transparent" className="overflow-hidden rounded-[28px]">
      <div className="bg-[var(--time-card-bg,var(--surface))] px-6 py-5 text-[var(--time-card-text,var(--text))] md:px-7 md:py-6">
        <div className="grid items-center gap-5 md:grid-cols-[minmax(0,1fr)_160px]">
          <div className="min-w-0">
            <div className="inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.22em]" style={{ borderColor: 'var(--time-card-border, var(--border))', color: 'var(--time-card-faint, var(--text-secondary))' }}>
              现在
            </div>
            <div className="mt-2 text-[46px] font-semibold leading-none tracking-[-0.075em] md:text-[52px]" style={{ color: 'var(--time-card-text, var(--text))' }}>
              {timeText}
            </div>
            <div className="mt-2 flex items-center gap-2 text-[12px]" style={{ color: 'var(--time-card-muted, var(--text-secondary))' }}>
              {timezoneText ? <span>{timezoneText}</span> : null}
              <span style={{ color: 'var(--time-card-faint, var(--text-secondary))' }}>{dateText}</span>
            </div>
          </div>
          <div className="flex items-center justify-end">
            <div className="relative h-[138px] w-[138px] rounded-full bg-transparent">
              {[...Array(12)].map((_, idx) => {
                const angle = (idx * 30 - 60) * (Math.PI / 180)
                const x = 50 + 40 * Math.cos(angle)
                const y = 50 + 40 * Math.sin(angle)
                const mark = idx === 0 ? 12 : idx
                return (
                  <span
                    key={mark}
                    className="absolute -translate-x-1/2 -translate-y-1/2 text-[10px] font-medium"
                    style={{ left: `${x}%`, top: `${y}%`, color: 'var(--time-card-text,var(--text))' }}
                  >
                    {mark}
                  </span>
                )
              })}
              <div className="absolute left-1/2 top-1/2 h-[2px] w-[42px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-text,var(--text))', transform: `translateY(-50%) rotate(${hourAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-[2px] w-[52px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-text,var(--text))', transform: `translateY(-50%) rotate(${minuteAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-[1px] w-[54px] origin-left rounded-full" style={{ backgroundColor: 'var(--time-card-accent,var(--accent))', transform: `translateY(-50%) rotate(${secondAngle - 90}deg)` }} />
              <div className="absolute left-1/2 top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full" style={{ backgroundColor: 'var(--time-card-accent,var(--accent))' }} />
            </div>
          </div>
        </div>
      </div>
    </DarkPanel>
  )
}

function FinalMessage({
  message,
  steps,
  executionGraph,
  showRegenerate,
}: {
  message: Message
  steps: ReasoningStep[]
  executionGraph: ExecutionGraphData | null
  showRegenerate: boolean
}) {
  const { id: messageId, finalText: content, citations, annotations, tool_calls, prompt_tokens, completion_tokens, model, decision_type } = message
  const showReasoning = getTraceVisibility('reasoning')
  const showDag = getTraceVisibility('dag')
  const showExecutionGraph = getTraceVisibility('executionGraph')
  const showDecisionTrace = getTraceVisibility('decisionTrace')
  const showFlowCards = getTraceVisibility('flowCards')
  const token = useAuthStore((s) => s.token)!
  const activeId = useChatStore((s) => s.activeId)
  const setMessages = useChatStore((s) => s.setMessages)
  const [editing, setEditing] = useState(false)
  const [value, setValue] = useState(content)
  const [showMetadata, setShowMetadata] = useState(false)
  const [feedback, setFeedback] = useState<'like' | 'dislike' | 'none'>('none')
  const [showVersionTree, setShowVersionTree] = useState(false)
  const [versionData, setVersionData] = useState<any>(null)

  const handleFeedback = async (type: 'like' | 'dislike') => {
    if (!activeId) return
    const newType = feedback === type ? 'none' : type
    setFeedback(newType)
    try {
      await apiSubmitFeedback(token, activeId, messageId, newType)
    } catch { /* silent */ }
  }

  const copy = async () => {
    await navigator.clipboard.writeText(content)
  }

  const quote = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:prefill', {
        detail: { text: `> ${content}\n`, autoSend: false },
      })
    )
  }

  const regenerate = () => {
    window.dispatchEvent(
      new CustomEvent('opentrace:regen', {
        detail: { mode: 'regenerate' },
      })
    )
  }

  const saveAssistantEdit = async () => {
    if (!activeId) return
    const text = value.trim()
    if (!text || text === content) {
      setEditing(false)
      return
    }
    await apiPatchMessage(token, messageId, text)
    const msgs = await apiGetMessages(token, activeId)
    setMessages(activeId, msgs)
    setEditing(false)
  }

  const branchHere = async () => {
    if (!activeId) return
    const result = await apiBranchConversation(token, activeId, messageId)
    window.dispatchEvent(
      new CustomEvent('opentrace:switch-conversation', {
        detail: { conversationId: result.conversation_id },
      })
    )
  }

  const streamingDoneEvent = typeof window !== 'undefined' ? `opentrace:assistant-stream-done:${messageId}` : ''
  const toolCard = useMemo(() => {
    try { return tryParseToolCard(content) } catch { return null }
  }, [content])
  const multiQuestionCards = useMemo(() => {
    try { return parseMultiQuestionCards(content) } catch { return null }
  }, [content])
  const displayContent = useMemo(() => stripJsonBlocks(content), [content])
  const hasTokenInfo = (prompt_tokens ?? 0) > 0 || (completion_tokens ?? 0) > 0

  const dagTimeline = useMemo<DagTimelineItem[]>(() => {
    const nodes = Array.isArray(executionGraph?.nodes) ? executionGraph.nodes : []
    return nodes
      .filter((n) => String(n.type) === 'agent_call')
      .map((n) => ({
        node_id: n.id,
        agent_type: String((n.metadata as any)?.agent_type || 'agent'),
        status: String(n.status || 'SUCCESS'),
        preview: String((n.output as any)?.preview || (n.metadata as any)?.query || ''),
        depends_on: Array.isArray((n.metadata as any)?.depends_on) ? (n.metadata as any).depends_on : undefined,
      }))
  }, [executionGraph])

  return (
    <div>
      {showReasoning ? <ReasoningChain steps={steps} collapseOnEvent={streamingDoneEvent} /> : null}
      {showDag ? <DagTimeline items={dagTimeline} /> : null}
      {showExecutionGraph ? <ExecutionGraphPanel graph={executionGraph} collapseOnEvent={streamingDoneEvent} /> : null}
      {showDecisionTrace ? <DecisionTraceCard executionGraph={executionGraph} annotations={annotations} /> : null}
      {showFlowCards ? (
        <div className="space-y-2">
          {toolCard?.type === 'time' ? <TimeCard data={toolCard.data} /> : null}
          {toolCard?.type === 'weather' ? <WeatherCard data={toolCard.data} /> : null}
          {toolCard?.type === 'table' ? <DataTableChart data={toolCard.data} /> : null}
          {toolCard?.type === 'data' ? (
            <CardShell
              eyebrow="DATA QUERY"
              title="查询结果"
              meta={toolCard.data.row_count !== undefined ? `${toolCard.data.row_count} 行` : undefined}
              accent="from-blue-500/55 via-cyan-400/35 to-indigo-300/25"
            >
              {toolCard.data.sql ? (
                <div className="mb-3">
                  <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)] mb-1">SQL</div>
                  <pre className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs overflow-x-auto"><code>{toolCard.data.sql}</code></pre>
                </div>
              ) : null}
              {Array.isArray(toolCard.data.rows) && toolCard.data.rows.length > 0 ? (
                <DataTableChart data={{ columns: Object.keys(toolCard.data.rows[0] || {}), rows: toolCard.data.rows }} />
              ) : null}
            </CardShell>
          ) : null}
          {toolCard?.type === 'agent' ? (
            <CardShell
              eyebrow={String(toolCard.data.agent_type || toolCard.data.type || 'AGENT')}
              title={String(toolCard.data.title || toolCard.data.agent_type || '执行结果')}
              meta={typeof toolCard.data.confidence === 'number' ? `置信度 ${Math.round(toolCard.data.confidence * 100)}%` : undefined}
              accent="from-purple-500/55 via-violet-400/35 to-fuchsia-300/25"
            >
              {typeof toolCard.data.content === 'string' && toolCard.data.content ? (
                <MarkdownMessage content={toolCard.data.content} />
              ) : toolCard.data.summary ? (
                <p className="text-sm text-[var(--text-secondary)]">{String(toolCard.data.summary)}</p>
              ) : toolCard.data.output ? (
                <pre className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs overflow-x-auto"><code>{typeof toolCard.data.output === 'string' ? toolCard.data.output : JSON.stringify(toolCard.data.output, null, 2)}</code></pre>
              ) : null}
            </CardShell>
          ) : null}
          {displayContent ? (
            <MarkdownMessage content={displayContent} />
          ) : null}
        </div>
      ) : null}
      {editing ? (
        <div className="space-y-2 my-2">
          <textarea
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm"
            rows={5}
          />
          <div className="flex gap-2 text-xs">
            <button onClick={() => setEditing(false)} className="px-2 py-1 rounded border border-[var(--border)]">取消</button>
            <button onClick={() => void saveAssistantEdit()} className="px-2 py-1 rounded bg-[var(--accent)] text-white">保存答案</button>
          </div>
        </div>
      ) : showFlowCards && toolCard ? (
        displayContent ? <MarkdownMessage content={displayContent} /> : null
      ) : multiQuestionCards ? (
        <MultiQuestionCards cards={multiQuestionCards} />
      ) : toolCard?.type === 'time' ? (
        <div className="space-y-2">
          <TimeCard data={toolCard.data} />
          {displayContent ? <MarkdownMessage content={displayContent} /> : null}
        </div>
      ) : toolCard?.type === 'weather' ? (
        <div className="space-y-2">
          <CardShell
            eyebrow="WEATHER"
            title={String(toolCard.data.city || '天气')}
            meta={toolCard.data.summary ? String(toolCard.data.summary) : formatCountLabel('温度', `${toolCard.data.temperature ?? '-'}°C`) || undefined}
            accent="from-sky-500/55 via-cyan-400/35 to-emerald-300/25"
          >
          <div className="space-y-4">
            <div className="rounded-2xl border border-[var(--border)] bg-[var(--bg-secondary)] px-4 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="text-[11px] uppercase tracking-[0.22em] text-[var(--text-secondary)]">实时天气</div>
                  <div className="mt-2 flex items-center gap-2 text-[22px] font-semibold leading-tight text-[var(--text)]">
                    <span aria-hidden="true">{(() => {
                      const text = `${String(toolCard.data.weather || '')} ${String(toolCard.data.summary || '')}`.toLowerCase()
                      if (/(雷|暴雨|storm|thunder)/.test(text)) return '⛈️'
                      if (/(雪|冰|霜|hail|sleet)/.test(text)) return '🌨️'
                      if (/(雨|阵雨|drizzle|rain)/.test(text)) return '🌧️'
                      if (/(雾|霾|haze|fog|smog)/.test(text)) return '🌫️'
                      if (/(云|阴|overcast|cloud)/.test(text)) return '☁️'
                      if (/(晴|clear|sunny|sun)/.test(text)) return '☀️'
                      return '🌤️'
                    })()}</span>
                    <span className="truncate">{toolCard.data.weather || '天气情况未知'}</span>
                  </div>
                  <p className="mt-1 text-sm leading-6 text-[var(--text-secondary)]">{toolCard.data.summary || `${toolCard.data.city || '该地区'}天气信息如下。`}</p>
                </div>
                <div className="flex-shrink-0 rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-4 py-3 text-right shadow-[0_1px_0_rgba(255,255,255,0.04)_inset]">
                  <div className="text-[11px] uppercase tracking-[0.2em] text-[var(--text-secondary)]">温度</div>
                  <div className="mt-1 text-4xl font-semibold leading-none text-[var(--text)]">{toolCard.data.temperature ?? '—'}<span className="text-xl">{toolCard.data.temperature !== undefined && toolCard.data.temperature !== null ? '°C' : ''}</span></div>
                  {toolCard.data.feels_like !== undefined && toolCard.data.feels_like !== null ? <div className="mt-1 text-xs text-[var(--text-secondary)]">体感 {toolCard.data.feels_like}°C</div> : null}
                </div>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
              {[
                ['天气', toolCard.data.weather, ''],
                ['湿度', toolCard.data.humidity, '%'],
                ['风速', toolCard.data.wind_speed, ' m/s'],
                ['风向', formatWindDirection(toolCard.data.wind_direction) || '-', ''],
                ['体感', toolCard.data.feels_like, '°C'],
                ['气压', toolCard.data.pressure, ' hPa'],
              ].map(([label, value, unit]) => (
                <div key={String(label)} className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] px-3 py-2.5">
                  <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">{label}</div>
                  <div className="mt-1 text-[var(--text)]">{value ?? '-'}{value !== undefined && value !== null && value !== '-' ? unit : ''}</div>
                </div>
              ))}
            </div>
            {Array.isArray(toolCard.data.forecast) && toolCard.data.forecast.length > 0 ? (
              <div className="rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-3">
                <div className="text-[11px] uppercase tracking-[0.18em] text-[var(--text-secondary)]">未来预报</div>
                <div className="mt-2 space-y-2 text-sm">
                  {toolCard.data.forecast.slice(0, 3).map((item: any, idx: number) => (
                    <div key={`${item.date || idx}`} className="flex items-center justify-between gap-3 rounded-xl border border-[var(--border)] bg-[var(--bg-secondary)] px-3 py-2">
                      <span className="whitespace-nowrap text-[var(--text-secondary)]">{String(item.date || `第${idx + 1}天`)}</span>
                      <span className="text-right text-[var(--text)]">{[item.condition, item.low !== undefined || item.high !== undefined ? `${item.low ?? '-'}℃ ~ ${item.high ?? '-'}℃` : ''].filter(Boolean).join('，')}</span>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        </CardShell>
        {displayContent ? <MarkdownMessage content={displayContent} /> : null}
        </div>
      ) : toolCard?.type === 'table' ? (
        <div className="space-y-2">
          <DataTableChart data={toolCard.data} />
          {displayContent ? <MarkdownMessage content={displayContent} /> : null}
        </div>
      ) : toolCard?.type === 'data' ? (
        <div className="space-y-2">
          <CardShell
            eyebrow="DATA QUERY"
            title="查询结果"
            meta={toolCard.data.row_count !== undefined ? `${toolCard.data.row_count} 行` : undefined}
            accent="from-blue-500/55 via-cyan-400/35 to-indigo-300/25"
          >
            {toolCard.data.sql ? (
              <div className="mb-3">
                <div className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-secondary)] mb-1">SQL</div>
                <pre className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs overflow-x-auto"><code>{toolCard.data.sql}</code></pre>
              </div>
            ) : null}
            {Array.isArray(toolCard.data.rows) && toolCard.data.rows.length > 0 ? (
              <DataTableChart data={{ columns: Object.keys(toolCard.data.rows[0] || {}), rows: toolCard.data.rows }} />
            ) : null}
          </CardShell>
          {displayContent ? <MarkdownMessage content={displayContent} /> : null}
        </div>
      ) : toolCard?.type === 'agent' ? (
        <div className="space-y-2">
          <CardShell
            eyebrow={String(toolCard.data.agent_type || toolCard.data.type || 'AGENT')}
            title={String(toolCard.data.title || toolCard.data.agent_type || '执行结果')}
            meta={typeof toolCard.data.confidence === 'number' ? `置信度 ${Math.round(toolCard.data.confidence * 100)}%` : undefined}
            accent="from-purple-500/55 via-violet-400/35 to-fuchsia-300/25"
          >
            {typeof toolCard.data.content === 'string' && toolCard.data.content ? (
              <MarkdownMessage content={toolCard.data.content} />
            ) : toolCard.data.summary ? (
              <p className="text-sm text-[var(--text-secondary)]">{String(toolCard.data.summary)}</p>
            ) : toolCard.data.output ? (
              <pre className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3 text-xs overflow-x-auto"><code>{typeof toolCard.data.output === 'string' ? toolCard.data.output : JSON.stringify(toolCard.data.output, null, 2)}</code></pre>
            ) : null}
          </CardShell>
          {displayContent ? <MarkdownMessage content={displayContent} /> : null}
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            {levelBadge(annotations?.[0]?.annotation?.level || parseEpistemicMeta(content).level)}
            {annotations?.[0]?.annotation?.confidence !== undefined ? (
              <span className="text-[10px] text-[var(--text-secondary)]">置信度 {Math.round((annotations[0].annotation!.confidence || 0) * 100)}%</span>
            ) : null}
          </div>
          <MarkdownMessage content={displayContent} />
          {(annotations?.[0]?.annotation?.caveats?.length || 0) > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {(annotations?.[0]?.annotation?.caveats || []).join('\n')}
            </div>
          ) : parseEpistemicMeta(content).issues.length > 0 ? (
            <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
              {parseEpistemicMeta(content).issues.join('\n')}
            </div>
          ) : null}
        </div>
      )}

      {Array.isArray(citations) && citations.length > 0 ? (
        <div className="mt-3 rounded-xl border border-[#e5e7eb] bg-[#f7f7f8] px-4 py-3">
          <div className="text-xs uppercase tracking-[0.2em] text-[#6b7280]">Sources</div>
          <div className="mt-2 space-y-2 text-sm text-[#111827]">
            {citations.map((c) => (
              <div key={c.id} className="flex flex-col gap-1">
                <a href={c.url || '#'} target="_blank" rel="noreferrer" className="text-[#111827] underline">
                  {c.id}. {c.title || c.url || 'Source'}
                </a>
                {c.snippet ? <div className="text-xs text-[#6b7280]">{c.snippet}</div> : null}
              </div>
            ))}
          </div>
        </div>
      ) : null}

      {/* Tool call cards */}
      {Array.isArray(tool_calls) && tool_calls.length > 0 && (
        <div className="mt-3 space-y-2">
          {tool_calls.map((tc) => <ToolCallCard key={tc.id} toolCall={tc} />)}
        </div>
      )}

      {/* Interrupted status */}
      {decision_type === 'interrupted' || message.status === 'interrupted' ? (
        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-700">
          回答中断 — 部分内容已保存
        </div>
      ) : null}

      {/* Token metadata footer */}
      {hasTokenInfo && (
        <div className="mt-2 border-t border-[var(--border)] pt-1.5">
          <button
            type="button"
            onClick={() => setShowMetadata((v) => !v)}
            className="flex items-center gap-1.5 text-[10px] text-[var(--text-secondary)] hover:text-[var(--text)] transition-colors"
          >
            <Cpu size={11} />
            <span>{(prompt_tokens ?? 0) + (completion_tokens ?? 0)} tokens</span>
            {model ? <span className="opacity-60">· {model}</span> : null}
            {showMetadata ? <ChevronUp size={11} /> : <ChevronDown size={11} />}
          </button>
          {showMetadata && (
            <div className="mt-1.5 grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-[var(--text-secondary)]">
              <div>Prompt: {prompt_tokens ?? 0}</div>
              <div>Completion: {completion_tokens ?? 0}</div>
              {model ? <div className="col-span-2">Model: {model}</div> : null}
            </div>
          )}
        </div>
      )}

      <div className="mt-2 flex items-center gap-2 text-[var(--text-secondary)]">
        <button onClick={copy} className="p-1 hover:text-[var(--text)]" title={t('chat.copy')}>
          <Copy size={14} />
        </button>
        <button onClick={quote} className="p-1 hover:text-[var(--text)]" title={t('chat.quote')}>
          <Quote size={14} />
        </button>
        <button onClick={() => setEditing((v) => !v)} className="p-1 hover:text-[var(--text)]" title={t('chat.editAnswer')}>
          <Pencil size={14} />
        </button>
        <button onClick={() => void branchHere()} className="p-1 hover:text-[var(--text)]" title={t('chat.branch')}>
          <GitBranch size={14} />
        </button>
        <button
          onClick={() => { void handleFeedback('like') }}
          className={`p-1 hover:text-[var(--text)] ${feedback === 'like' ? 'text-emerald-500' : ''}`}
          title="有帮助"
        >
          <ThumbsUp size={14} />
        </button>
        <button
          onClick={() => { void handleFeedback('dislike') }}
          className={`p-1 hover:text-[var(--text)] ${feedback === 'dislike' ? 'text-red-500' : ''}`}
          title="无帮助"
        >
          <ThumbsDown size={14} />
        </button>
        <button
          onClick={async () => {
            if (showVersionTree) { setShowVersionTree(false); return }
            try {
              const data = await apiGetMessageVersions(token, messageId)
              setVersionData(data)
              setShowVersionTree(true)
            } catch { setShowVersionTree(false) }
          }}
          className={`p-1 hover:text-[var(--text)] ${showVersionTree ? 'text-violet-500' : ''}`}
          title="版本历史"
        >
          <GitFork size={14} />
        </button>
        {showRegenerate ? (
          <button onClick={regenerate} className="p-1 hover:text-[var(--text)]" title={t('chat.regenerate')}>
            <RotateCcw size={14} />
          </button>
        ) : null}
      </div>
      {showVersionTree && versionData?.versions?.length > 1 ? (
        <MessageVersionTree versions={versionData.versions} currentId={messageId} />
      ) : null}
    </div>
  )
}


function ToolCallCard({ toolCall }: { toolCall: ToolCallBlock }) {
  const [expanded, setExpanded] = useState(false)
  const statusColor = toolCall.status === 'error' ? 'border-red-300 bg-red-50'
    : toolCall.status === 'interrupted' ? 'border-amber-300 bg-amber-50'
    : toolCall.status === 'retrying' ? 'border-blue-300 bg-blue-50'
    : toolCall.status === 'running' ? 'border-amber-300 bg-amber-50 animate-pulse'
    : toolCall.status === 'success' ? 'border-emerald-300 bg-emerald-50'
    : 'border-slate-300 bg-slate-50'

  const statusLabel = toolCall.status === 'running' ? '执行中...'
    : toolCall.status === 'error' ? '失败'
    : toolCall.status === 'interrupted' ? '已中断'
    : toolCall.status === 'retrying' ? '重试中...'
    : toolCall.status === 'success' ? '完成'
    : '等待中'

  let argsPreview = ''
  try {
    if (toolCall.function?.arguments) {
      const parsed = JSON.parse(toolCall.function.arguments)
      argsPreview = Object.entries(parsed).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`).join(', ')
    }
  } catch {
    argsPreview = String(toolCall.function?.arguments || '').slice(0, 80)
  }

  return (
    <div className={`rounded-lg border ${statusColor} px-3 py-2 text-xs`}>
      <button
        type="button"
        className="flex items-center justify-between w-full gap-2"
        onClick={() => setExpanded((v) => !v)}
      >
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-medium text-[var(--text)]">{toolCall.function?.name || 'tool_call'}</span>
          <span className="text-[var(--text-secondary)] truncate">{argsPreview}</span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-[var(--text-secondary)]">{statusLabel}</span>
          {toolCall.duration_ms ? <span className="text-[var(--text-secondary)]">{toolCall.duration_ms}ms</span> : null}
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </div>
      </button>
      {expanded && (
        <div className="mt-2 space-y-1.5">
          <pre className="whitespace-pre-wrap break-all text-[var(--text-secondary)]">
            {(() => {
              try {
                return JSON.stringify(JSON.parse(toolCall.function?.arguments || '{}'), null, 2)
              } catch {
                return toolCall.function?.arguments || ''
              }
            })()}
          </pre>
          {toolCall.result ? (
            <div className="rounded border border-[var(--border)] bg-[var(--surface)] p-2 text-[var(--text)]">
              {toolCall.result}
            </div>
          ) : null}
        </div>
      )}
    </div>
  )
}
