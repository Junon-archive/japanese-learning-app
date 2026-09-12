/**
 * 409 사유 구분.
 *
 * **넷을 한 덩어리로 다루면 안 된다**(05_API_SPEC.md의 `409 사유 구분`, ADR-018). 게이트
 * 409는 "화면 상태가 서버와 어긋났다"라서 세션 재획득으로 이어지고, evidence 상한의
 * 409는 "서버가 이미 답을 받아 뒀다"라서 **어떤 재시도도 성공하지 못한다.** 합치면
 * client가 무한 재시도나 불필요한 세션 재획득을 한다.
 *
 * 사유 코드 체계를 새로 만들지 않았으므로 구분 수단은 응답 body의 `detail` 문구다.
 * 그래서 **그 문구가 backend에 실제로 있는지도 함께 단정한다** --- 문구가 바뀌면 분기가
 * 조용히 전부 `Unknown`으로 떨어지고, 화면에서는 "알 수 없는 문제" 하나로만 보인다.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiPostEvent } from '../../src/api'
import type { ConflictReason } from '../../src/api'

/** `backend/app/api/study.py`의 `_http_errors()`가 내는 409 문구 그대로. */
const BACKEND_DETAILS: [string, ConflictReason][] = [
  ['Session is already finished', 'SessionFinished'],
  ['Presentation is already completed', 'PresentationCompleted'],
  ['This exposure already has recorded evidence', 'EvidenceAlreadyRecorded'],
  ['client_event_id is already used by another event', 'EventKeyUsed'],
]

const fetchMock = vi.fn<typeof fetch>()

function conflict(detail: string | undefined): Response {
  return new Response(detail === undefined ? null : JSON.stringify({ detail }), {
    status: 409,
    headers: { 'Content-Type': 'application/json' },
  })
}

async function reasonOf(response: Response): Promise<ConflictReason> {
  fetchMock.mockResolvedValue(response)
  const failure = await apiPostEvent('/api/study/presentations/1/self-report', {
    sentence_item_id: 5511,
    value: 'known',
  }).catch((error: unknown) => error)

  expect(failure).toBeInstanceOf(ApiError)
  return (failure as ApiError).conflictReason
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('409 reason', () => {
  for (const [detail, reason] of BACKEND_DETAILS) {
    it(`reads "${detail}" as ${reason}`, async () => {
      expect(await reasonOf(conflict(detail))).toBe(reason)
      // 사유를 읽었다고 재전송하지 않는다.
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  }

  it('tells the four reasons apart', () => {
    expect(new Set(BACKEND_DETAILS.map(([, reason]) => reason)).size).toBe(4)
  })

  it('falls back to Unknown for a phrase it does not know', async () => {
    // 추측해서 세션을 재획득하지 않는다. 화면은 일반 오류로 다룬다.
    expect(await reasonOf(conflict('Something else entirely'))).toBe('Unknown')
  })

  it('falls back to Unknown when there is no body at all', async () => {
    expect(await reasonOf(conflict(undefined))).toBe('Unknown')
  })

  it('leaves the reason Unknown for statuses that are not 409', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 404 }))

    const failure = await apiPostEvent('/api/study/presentations/1/flag', {
      reason: 'wrong',
    }).catch((error: unknown) => error)

    expect((failure as ApiError).kind).toBe('NotFound')
    expect((failure as ApiError).conflictReason).toBe('Unknown')
  })
})

describe('detail phrases', () => {
  it('are the ones the backend actually sends', () => {
    const study = readFileSync(
      fileURLToPath(new URL('../../../backend/app/api/study.py', import.meta.url)),
      'utf8',
    )

    for (const [detail] of BACKEND_DETAILS) {
      expect(study).toContain(detail)
    }
  })
})
