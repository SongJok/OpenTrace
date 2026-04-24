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
    expect(screen.getByText('上海')).toBeInTheDocument()
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
    expect(screen.getByText('🌤️ 上海 天气')).toBeInTheDocument()
    expect(screen.getByText('温度：22°C')).toBeInTheDocument()
    expect(screen.getByText('天气：多云')).toBeInTheDocument()
  })
})
