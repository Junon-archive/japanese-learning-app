/**
 * HTTP 한 겹. 화면 로직도 상태 저장소도 여기 두지 않는다.
 *
 * 세 가지를 이 파일에서만 보장한다.
 *
 * 1.  **재시도는 같은 `client_event_id`를 다시 보낸다.** 재시도마다 새 UUID를
 *     발급하면 서버의 `(user_id, client_event_id)` 중복 방지가 통하지 않아 self-report
 *     하나가 evidence로 두 번 적용된다(EMA가 두 번 돈다). 화면은 정상으로 보이므로
 *     사용자도 개발자도 알아채지 못한다. 그래서 body 문자열을 재시도 루프 **밖에서**
 *     한 번만 만든다.
 * 2.  **409에는 재전송하지 않는다.** 어느 사유든 같은 요청을 다시 보내 바뀌는 것이
 *     없다. 재전송하면 무한 루프다. 다음 동작은 사유마다 다르므로(세션 재획득 /
 *     "이미 기록했습니다") `ConflictReason`으로 갈라 화면에 넘긴다
 *     (05_API_SPEC.md의 `409 사유 구분`).
 * 3.  **재시도는 유한하다.** 무한 spinner를 만들지 않는다(10_ERROR_HANDLING.md).
 *
 * 같은 요청이 이미 날아가 있으면 새로 보내지 않고 그 Promise를 함께 기다린다.
 * 모바일 더블탭이 두 개의 event POST가 되는 것을 막는다.
 */

import { API_BASE_URL } from './env'
import { newClientEventId } from './ids'

/**
 * 화면이 분기해야 하는 실패의 종류. 상태 코드를 화면까지 들고 가지 않는다.
 *
 * `Transient`만 재시도 대상이다. 나머지는 같은 요청을 다시 보내도 결과가 같다.
 */
export type ApiErrorKind =
  /** 401. 로그인 화면으로 보낸다. */
  | 'Unauthenticated'
  /** 403. Origin 검증 실패 --- 배포 설정 문제이지 사용자가 고칠 수 있는 것이 아니다. */
  | 'OriginRejected'
  /** 404. 없거나 남의 것. 서버는 둘을 구분하지 않는다. */
  | 'NotFound'
  /** 409. 닫힌 session / 완료된 presentation. **재전송하지 않는다.** */
  | 'StateGate'
  /** 400, 422. 보낸 값이 잘못됐다. 같은 값으로 재시도해도 같다. */
  | 'Invalid'
  /** 5xx와 네트워크 실패. 재시도 대상. */
  | 'Transient'
  | 'Unexpected'

/**
 * 409의 사유. **복구 동작이 사유마다 다르다**(05_API_SPEC.md의 `409 사유 구분`).
 *
 * 앞의 둘은 "화면 상태가 서버와 어긋났다"이므로 세션 재획득으로 이어지고,
 * `EvidenceAlreadyRecorded`는 "서버가 이미 답을 받아 뒀다"이므로 **어떤 재시도도
 * 성공하지 못하고 해서도 안 된다**(ADR-018). 한 종류로 합치면 client가 불필요한
 * 세션 재획득이나 무한 재시도를 한다.
 *
 * 사유 코드 체계를 새로 만들지 않는다 --- 구분 수단은 응답 body의 `detail` 문구
 * 그대로이고, 그 문구가 사유 코드다(같은 절). 알 수 없는 문구는 `Unknown`이며
 * 화면은 그것을 일반 오류로 다룬다.
 */
export type ConflictReason =
  | 'SessionFinished'
  | 'PresentationCompleted'
  | 'EvidenceAlreadyRecorded'
  | 'EventKeyUsed'
  | 'Unknown'

export class ApiError extends Error {
  readonly kind: ApiErrorKind
  /** 네트워크 실패로 응답 자체가 없으면 0. */
  readonly status: number
  /** `kind`가 `StateGate`일 때만 뜻이 있다. 그 밖에는 `Unknown`이다. */
  readonly conflictReason: ConflictReason

  constructor(kind: ApiErrorKind, status: number, conflictReason: ConflictReason = 'Unknown') {
    super(`API request failed (${kind}, status ${status})`)
    this.name = 'ApiError'
    this.kind = kind
    this.status = status
    this.conflictReason = conflictReason
  }
}

/** 첫 시도 뒤 허용하는 추가 시도 횟수. 유한해야 한다. */
const MAX_RETRIES = 2
const RETRY_BASE_DELAY_MS = 200

type JsonBody = Record<string, unknown>

const inFlight = new Map<string, Promise<unknown>>()

function errorKind(status: number): ApiErrorKind {
  if (status === 401) return 'Unauthenticated'
  if (status === 403) return 'OriginRejected'
  if (status === 404) return 'NotFound'
  if (status === 409) return 'StateGate'
  if (status === 400 || status === 422) return 'Invalid'
  if (status >= 500) return 'Transient'
  return 'Unexpected'
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

/**
 * 409 사유 문구 -> `ConflictReason`. 문구는 서버의 `detail`이다
 * (`backend/app/api/study.py`의 `_http_errors()`).
 *
 * 네 문구가 서로 겹치지 않는 단어를 갖고 있으므로 그 단어로 가른다. 문구 전체를
 * 그대로 비교하면 서버가 문장을 다듬는 순간 전부 `Unknown`이 된다.
 */
const CONFLICT_REASONS: [RegExp, ConflictReason][] = [
  [/evidence/i, 'EvidenceAlreadyRecorded'],
  [/session is already finished/i, 'SessionFinished'],
  [/presentation is already completed/i, 'PresentationCompleted'],
  [/client_event_id/i, 'EventKeyUsed'],
]

async function conflictReason(response: Response): Promise<ConflictReason> {
  let detail = ''
  try {
    const body: unknown = JSON.parse(await response.text())
    const value = (body as { detail?: unknown } | null)?.detail
    if (typeof value === 'string') detail = value
  } catch {
    // body가 비었거나 JSON이 아니다. 사유를 알 수 없으면 일반 오류로 다룬다.
  }
  return CONFLICT_REASONS.find(([pattern]) => pattern.test(detail))?.[1] ?? 'Unknown'
}

async function readBody(response: Response): Promise<unknown> {
  // 204(self-report, flag, explanation-revealed, logout)는 본문이 없다.
  const text = await response.text()
  return text === '' ? undefined : JSON.parse(text)
}

/**
 * 한 요청을 유한 번 시도한다. `body`는 **문자열로 이미 고정돼 있다** --- 그래서
 * 재시도가 `client_event_id`를 새로 만들 수 없다.
 */
async function send(method: string, path: string, body: string | undefined): Promise<unknown> {
  let lastError = new ApiError('Transient', 0)

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt += 1) {
    if (attempt > 0) {
      await delay(RETRY_BASE_DELAY_MS * 2 ** (attempt - 1))
    }

    let response: Response
    try {
      response = await fetch(`${API_BASE_URL}${path}`, {
        method,
        // 인증은 세션 cookie다. 토큰을 JS가 들고 있지 않는다.
        credentials: 'include',
        headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
        body,
      })
    } catch {
      // 실패 사유(DNS, offline, CORS)를 화면까지 옮기지 않는다.
      lastError = new ApiError('Transient', 0)
      continue
    }

    if (response.ok) {
      return await readBody(response)
    }

    const kind = errorKind(response.status)
    // 409만 body를 읽는다. 사유로 갈릴 수 있는 실패가 그것뿐이다.
    const error = new ApiError(
      kind,
      response.status,
      kind === 'StateGate' ? await conflictReason(response) : 'Unknown',
    )
    if (error.kind !== 'Transient') {
      throw error
    }
    lastError = error
  }

  throw lastError
}

/** 같은 요청이 날아가 있으면 그것을 함께 기다린다. */
function dedupe<T>(key: string, start: () => Promise<unknown>): Promise<T> {
  const existing = inFlight.get(key)
  if (existing !== undefined) {
    return existing as Promise<T>
  }
  const request = start().finally(() => {
    inFlight.delete(key)
  })
  inFlight.set(key, request)
  return request as Promise<T>
}

export function apiGet<T>(path: string): Promise<T> {
  return dedupe<T>(`GET ${path}`, () => send('GET', path, undefined))
}

/**
 * `client_event_id`를 받지 않는 POST (`/session`, `/next`, `/complete`, `/finish`).
 * 이 event들의 idempotency key는 서버가 자연키로 만든다(ADR-008).
 */
export function apiPost<T>(path: string): Promise<T> {
  return dedupe<T>(`POST ${path}`, () => send('POST', path, undefined))
}

/**
 * body는 보내지만 `client_event_id`는 **붙이지 않는** POST. 지금은 `/api/auth/login`
 * 하나다 --- login은 learning event가 아니므로 idempotency key가 없다.
 *
 * dedupe key에 body를 넣지 않는다. body에 평문 password가 들어 있어서 key로 쓰면
 * 요청이 끝날 때까지 Map의 key 문자열로 남는다. 대신 화면이 제출 버튼을 비활성화하고,
 * 같은 path로 동시에 두 번 눌린 것은 같은 시도로 합친다.
 */
export function apiPostJson<T>(path: string, body: JsonBody): Promise<T> {
  return dedupe<T>(`POST ${path}`, () => send('POST', path, JSON.stringify(body)))
}

/**
 * client가 idempotency key를 들고 가는 POST.
 *
 * `client_event_id`는 이 호출 하나당 **한 번** 만들어지고 재시도 전부가 같은 값을
 * 다시 보낸다. dedupe key에는 그 UUID가 들어가지 않는다 --- 들어가면 더블탭이 서로
 * 다른 key가 되어 같은 자가보고가 두 번 기록된다.
 */
export function apiPostEvent<T>(path: string, body: JsonBody = {}): Promise<T> {
  return dedupe<T>(`POST ${path} ${JSON.stringify(body)}`, () =>
    send('POST', path, JSON.stringify({ ...body, client_event_id: newClientEventId() })),
  )
}
