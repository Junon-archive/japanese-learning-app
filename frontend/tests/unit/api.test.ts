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
import { errorMessage } from '../../src/ui/api-failure'
import { MESSAGES } from '../../src/ui/notice'

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

/**
 * 실패 -> 화면 문구(`ui/api-failure.ts`). 문구는 `03_UI_UX_SPEC.md`의 `공통 안내와 오류`와 같다.
 * 주소·Origin·상태 코드를 문구에 적지 않는다.
 */
describe('failure wording', () => {
  it('maps each failure to the confirmed wording', () => {
    const cases: [ApiError | Error, string][] = [
      [new ApiError('OriginRejected', 403), '설정 문제로 연결할 수 없어요. 관리자에게 알려 주세요.'],
      [new ApiError('NotFound', 404), '내용을 찾지 못했어요.'],
      [new ApiError('StateGate', 409), '이 학습은 이미 끝났어요. 새로 불러올게요.'],
      [new ApiError('Invalid', 422), '이 요청은 처리할 수 없어요.'],
      [new ApiError('Transient', 503), '지금 연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요.'],
      [new ApiError('Unexpected', 418), '예상하지 못한 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'],
      [new Error('boom'), '예상하지 못한 문제가 생겼어요. 잠시 후 다시 시도해 주세요.'],
    ]

    for (const [error, text] of cases) expect(errorMessage(error)).toBe(text)
  })

  it('keeps the common notices and buttons in the confirmed wording', () => {
    expect(MESSAGES.sessionResumed).toBe('이어서 학습해요.')
    expect(MESSAGES.previousSessionTimedOut).toBe('한동안 쉬어서 새로 시작해요. 지난 기록은 그대로 있어요.')
    expect(MESSAGES.emptyPool).toBe('지금은 준비된 문장이 없어요. 잠시 후 다시 시도해 주세요.')
    expect(MESSAGES.sessionClosedElsewhere).toBe('진행 중인 학습이 없어요. 새로 시작할 수 있어요.')
    expect(MESSAGES.saveFailed).toBe('저장하지 못했어요. 다시 시도해 주세요.')
    expect(MESSAGES.retry).toBe('다시 시도하기')
    expect(MESSAGES.startNewSession).toBe('새로 시작하기')
    // 보안 문구: 사유와 무관한 한 문구. 어느 쪽이 틀렸는지 암시하지 않는다.
    expect(MESSAGES.loginFailed).toBe('아이디나 비밀번호를 다시 확인해 주세요.')
    for (const message of Object.values(MESSAGES)) {
      expect(message).not.toMatch(/서버|세션|API|요청이 거부|습니다/)
    }
  })
})
