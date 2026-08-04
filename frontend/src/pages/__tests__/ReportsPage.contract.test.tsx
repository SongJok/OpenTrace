import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  apiCreateEnterpriseReport,
  apiGetEnterpriseReport,
  apiListEnterpriseReports,
  apiListEnterpriseReportTemplates,
} from '../../api/client'

describe('enterprise reports contracts', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('exposes the three governed lighthouse templates', async () => {
    const templates = [
      { id: 'data_insight', title: '数据洞察' },
      { id: 'monthly_report', title: '经营月报' },
      { id: 'management_brief', title: '经营简报' },
    ]
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: templates }), { status: 200 }),
    )
    vi.stubGlobal('fetch', fetchMock)

    const result = await apiListEnterpriseReportTemplates('token')

    expect(result.map((item) => item.id)).toEqual([
      'data_insight',
      'monthly_report',
      'management_brief',
    ])
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/v2/reports/templates',
      expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer token' }) }),
    )
  })

  it('uses report resources while run and lifecycle reuse scheduled task commands', async () => {
    const responses = [
      new Response(JSON.stringify({ items: [] }), { status: 200 }),
      new Response(JSON.stringify({ id: 'report-1', report_type: 'data_insight' }), { status: 200 }),
      new Response(JSON.stringify({ id: 'report-1', runs: [] }), { status: 200 }),
    ]
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(responses.shift()))
    vi.stubGlobal('fetch', fetchMock)

    await apiListEnterpriseReports('token')
    await apiCreateEnterpriseReport('token', { report_type: 'data_insight' })
    await apiGetEnterpriseReport('token', 'report-1')

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/v2/reports',
      '/api/v2/reports',
      '/api/v2/reports/report-1',
    ])
    expect(fetchMock.mock.calls[1][1]).toMatchObject({ method: 'POST' })
  })

  it('renders evidence, SQL, citations and charts from report artifacts', async () => {
    const page = await import('../ReportsPage')
    const source = page.ReportRuns.toString()
    expect(source).toContain('artifact.charts')
    expect(source).toContain('data_evidence')
    expect(source).toContain('knowledge_citations')
    expect(source).toContain('verification')
  })
})
