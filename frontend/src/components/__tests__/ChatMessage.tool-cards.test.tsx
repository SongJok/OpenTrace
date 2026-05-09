import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import ChatMessage from '../ChatMessage'

const baseAssistant = {
  id: 'a1',
  role: 'assistant' as const,
  status: 'done' as const,
  streamText: '',
  finalText: '',
}

describe('ChatMessage tool cards', () => {
  it('renders time card from JSON content', () => {
    const message = {
      ...baseAssistant,
      finalText: JSON.stringify({
        type: 'time',
        displayTime: '23:10',
        time: '2026-04-09 23:10:00',
        timestamp: 1775776200,
        timezone: 'local',
        location: '上海',
      }),
    }
    render(<ChatMessage message={message as any} />)
    expect(screen.getByText('23:10')).toBeInTheDocument()
  })

  it('renders weather card from JSON content', () => {
    const message = {
      ...baseAssistant,
      finalText: JSON.stringify({
        city: '上海',
        temperature: 22,
        weather: '多云',
        humidity: 60,
      }),
    }
    render(<ChatMessage message={message as any} />)
    // Weather card title shows city name
    expect(screen.getByText('上海')).toBeInTheDocument()
    // Weather condition is displayed
    expect(screen.getAllByText('多云').length).toBeGreaterThanOrEqual(1)
    // Temperature is displayed
    expect(screen.getByText('22')).toBeInTheDocument()
  })

  it('renders table card from JSON content', () => {
    const message = {
      ...baseAssistant,
      finalText: JSON.stringify({
        type: 'table',
        title: '销售数据',
        columns: ['月份', '销售额'],
        rows: [
          { '月份': '1月', '销售额': 12000 },
          { '月份': '2月', '销售额': 15000 },
        ],
      }),
    }
    render(<ChatMessage message={message as any} />)
    expect(screen.getByText('销售数据')).toBeInTheDocument()
    expect(screen.getByText('月份')).toBeInTheDocument()
  })

  it('strips JSON from displayed markdown content', () => {
    const message = {
      ...baseAssistant,
      finalText: '{"type":"table","columns":["a"],"rows":[{"a":1}]}\n\n这是数据分析的结论。',
    }
    render(<ChatMessage message={message as any} />)
    // The text content should be visible
    expect(screen.getByText('这是数据分析的结论。')).toBeInTheDocument()
    // The raw JSON should not be rendered as visible text
    expect(screen.queryByText('"type":"table"')).not.toBeInTheDocument()
  })

  it('renders table card from raw result array', () => {
    const message = {
      ...baseAssistant,
      finalText: '[{"排挡次数": 445}]',
    }
    render(<ChatMessage message={message as any} />)
    // Should render as a table card, showing the column name
    expect(screen.getByText('排挡次数')).toBeInTheDocument()
    // Should show the value
    expect(screen.getByText('445')).toBeInTheDocument()
  })

  it('strips trailing JSON array from text, keeps intro text', () => {
    const message = {
      ...baseAssistant,
      finalText: '查询已执行，共返回 1 行数据，以下是结果预览：\n\n[{"排挡次数": 445}]',
    }
    render(<ChatMessage message={message as any} />)
    // The raw JSON array should be removed from text display
    expect(screen.queryByText('[{"排挡次数": 445}]')).not.toBeInTheDocument()
    // The table card should show the column
    expect(screen.getByText('排挡次数')).toBeInTheDocument()
    // The intro text should still be visible
    expect(screen.getByText(/查询已执行/)).toBeInTheDocument()
  })
})
