/**
 * `api.ts`가 지켜야 하는 것들.
 *
 * 가장 중요한 것은 **재시도가 같은 `client_event_id`를 다시 보내는 것**이다. 재시도가
 * 새 UUID를 만들면 서버의 `(user_id, client_event_id)` 중복 방지가 통하지 않아 자가보고
 * 하나가 evidence로 두 번 적용된다. 화면에는 아무 이상이 없으므로 이 테스트가 아니면
 * 발견되지 않는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiGet, apiPost, apiPostEvent } from '../../src/api'

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function empty(status: number): Response {
  return new Response(null, { status })
}

const fetchMock = vi.fn<typeof fetch>()

function sentBodies(): Record<string, unknown>[] {
  return fetchMock.mock.calls.map(([, init]) => JSON.parse(String(init?.body)))
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('client_event_id', () => {
  it('stays identical across two retries of the same action', async () => {
    fetchMock
      .mockResolvedValueOnce(empty(500))
      .mockResolvedValueOnce(empty(503))
      .mockResolvedValueOnce(empty(204))

    await apiPostEvent('/api/study/presentations/1/self-report', {
      sentence_item_id: 5511,
      value: 'unknown',
    })

    expect(fetchMock).toHaveBeenCalledTimes(3)
    const ids = sentBodies().map((body) => body['client_event_id'])
    expect(ids[0]).toMatch(UUID_V4)
    expect(new Set(ids).size).toBe(1)
    // 재시도가 payload를 바꾸지도 않는다.
    expect(sentBodies().every((body) => body['value'] === 'unknown')).toBe(true)
  })

  it('differs between two distinct actions', async () => {
    fetchMock.mockResolvedValue(empty(204))

    await apiPostEvent('/api/study/presentations/1/self-report', {
      sentence_item_id: 5511,
      value: 'known',
    })
    await apiPostEvent('/api/study/presentations/1/self-report', {
      sentence_item_id: 5512,
      value: 'known',
    })

    const [first, second] = sentBodies().map((body) => body['client_event_id'])
    expect(first).toMatch(UUID_V4)
    expect(second).toMatch(UUID_V4)
    expect(first).not.toBe(second)
  })
})

describe('error mapping', () => {
  const cases: [number, string][] = [
    [401, 'Unauthenticated'],
    [403, 'OriginRejected'],
    [404, 'NotFound'],
    [409, 'StateGate'],
    [422, 'Invalid'],
    [400, 'Invalid'],
  ]

  for (const [status, kind] of cases) {
    it(`maps ${status} to ${kind} without retrying`, async () => {
      fetchMock.mockResolvedValue(empty(status))

      const failure = await apiPostEvent(`/api/study/presentations/${status}/flag`, {
        reason: 'wrong',
      }).catch((error: unknown) => error)

      expect(failure).toBeInstanceOf(ApiError)
      expect((failure as ApiError).kind).toBe(kind)
      // 특히 409. 재전송하면 무한 루프가 된다.
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  }

  it('maps a network failure to Transient and gives up after a finite number of tries', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))

    const failure = await apiGet('/api/study/session').catch((error: unknown) => error)

    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).kind).toBe('Transient')
    expect((failure as ApiError).status).toBe(0)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })
})

describe('requests', () => {
  it('sends cookies and JSON, and returns undefined for 204', async () => {
    fetchMock.mockResolvedValue(empty(204))

    const result = await apiPostEvent('/api/study/presentations/9/translation/reveal')

    const [url, init] = fetchMock.mock.calls[0]!
    expect(String(url).endsWith('/api/study/presentations/9/translation/reveal')).toBe(true)
    expect(init?.credentials).toBe('include')
    expect(init?.headers).toEqual({ 'Content-Type': 'application/json' })
    expect(result).toBeUndefined()
  })

  it('sends no body for server-keyed POSTs', async () => {
    fetchMock.mockResolvedValue(json({ presentation: null }))

    await apiPost('/api/study/session/7/next')

    const [, init] = fetchMock.mock.calls[0]!
    expect(init?.body).toBeUndefined()
    expect(init?.method).toBe('POST')
  })

  it('collapses a double tap into one in-flight request', async () => {
    fetchMock.mockResolvedValue(empty(204))
    const body = { sentence_item_id: 5511, value: 'known' } as const

    const [first, second] = await Promise.all([
      apiPostEvent('/api/study/presentations/1/self-report', body),
      apiPostEvent('/api/study/presentations/1/self-report', body),
    ])

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(first).toBe(second)
  })
})
