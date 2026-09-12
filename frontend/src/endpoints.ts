/**
 * endpoint별 호출부. path와 응답 타입을 여기 한 곳에만 적는다.
 *
 * `api.ts`는 HTTP 한 겹이고 path를 모른다. 화면 모듈이 path 문자열을 직접 조립하면
 * 같은 endpoint가 여러 파일에 흩어지고, 그중 하나만 오타가 나면 그 동작만 404가 된다.
 *
 * **`client_event_id`를 붙이는 것은 `apiPostEvent` 하나다.** 이 파일은 어느 endpoint가
 * 그것을 받는지만 고른다(05_API_SPEC.md의 `event idempotency key`). 직접 UUID를 만들어
 * body에 넣지 않는다 --- 그러면 재시도가 새 key를 발급해 자가보고 하나가 evidence로 두
 * 번 적용된다.
 *
 * **`/next`를 부르는 함수는 `/complete`를 부르지 않는다.** 순서는 호출하는 쪽
 * (`ui/study.ts`)이 지킨다 --- 두 호출을 한 함수로 묶으면 "완료 없이 다음"과 "완료 후
 * 다음"을 구분할 수 없게 된다.
 */

import { apiGet, apiPost, apiPostEvent, apiPostJson } from './api'
import type {
  CompletePresentationResponse,
  ContentFlagBody,
  Explanation,
  HistoryItemsResponse,
  HistorySessionsResponse,
  LoginBody,
  NextPresentationResponse,
  OpenSessionResponse,
  ProbeResponseBody,
  ProbeResultResponse,
  SelfReportBody,
  StartSessionResponse,
  StudySession,
  TranslationResponse,
  User,
} from './types'

// --------------------------------------------------------------------------
// auth
// --------------------------------------------------------------------------

export function fetchMe(): Promise<User> {
  return apiGet<User>('/api/auth/me')
}

export function login(body: LoginBody): Promise<User> {
  return apiPostJson<User>('/api/auth/login', { ...body })
}

/**
 * auth session을 폐기한다. 204라 body가 없다.
 *
 * **진행 중인 study session은 닫지 않는다** --- 폐기되는 것은 auth session이고, 다시
 * 로그인하면 idle timeout 이내인 study session은 그대로 resume된다(03_UI_UX_SPEC.md의
 * `로그아웃`). 그래서 이 호출 전에 `/finish`를 부르지 않는다.
 *
 * `client_event_id`를 받지 않는다. learning event가 아니다.
 */
export function logout(): Promise<void> {
  return apiPost<void>('/api/auth/logout')
}

// --------------------------------------------------------------------------
// study session
// --------------------------------------------------------------------------

/** 조회다. `touch()`하지 않으므로 진행 표시 갱신에 쓸 수 있다(05_API_SPEC.md). */
export function fetchOpenSession(): Promise<OpenSessionResponse> {
  return apiGet<OpenSessionResponse>('/api/study/session')
}

/** create 또는 resume. body를 받지 않는다. */
export function startSession(): Promise<StartSessionResponse> {
  return apiPost<StartSessionResponse>('/api/study/session')
}

/** Ready Pool이 비면 `presentation: null` + 200이다. 오류가 아니다. */
export function fetchNextPresentation(sessionId: number): Promise<NextPresentationResponse> {
  return apiPost<NextPresentationResponse>(`/api/study/session/${sessionId}/next`)
}

export function finishSession(sessionId: number): Promise<StudySession> {
  return apiPost<StudySession>(`/api/study/session/${sessionId}/finish`)
}

/** client가 `client_event_id`를 들고 가는 유일한 session endpoint다(ADR-008). */
export function extendSession(sessionId: number): Promise<StudySession> {
  return apiPostEvent<StudySession>(`/api/study/session/${sessionId}/extend`)
}

// --------------------------------------------------------------------------
// presentation
// --------------------------------------------------------------------------

/** `Next`를 누를 때 **명시적으로** 호출한다. 재호출해도 결과가 같다. */
export function completePresentation(
  presentationId: number,
): Promise<CompletePresentationResponse> {
  return apiPost<CompletePresentationResponse>(
    `/api/study/presentations/${presentationId}/complete`,
  )
}

// --------------------------------------------------------------------------
// interaction
// --------------------------------------------------------------------------

/**
 * tap -> `item_clicked` + precomputed 설명. live LLM fallback이 없으므로 설명이 없는
 * item은 500(`Explanation is not available`)이다 --- 그 경로에서는 `item_clicked`만
 * 남고 `explanation_revealed`는 남지 않는다(05_API_SPEC.md).
 */
export function clickItem(
  presentationId: number,
  sentenceItemId: number,
): Promise<Explanation> {
  return apiPostEvent<Explanation>(
    `/api/study/presentations/${presentationId}/items/${sentenceItemId}/click`,
  )
}

/**
 * 설명 패널이 **실제로 렌더된 뒤에** 부른다. tap과 동시에 부르면 두 event가 항상
 * 1:1이 되어 "탭했지만 표시되지 않은 경우"를 구분할 수 없다(05_API_SPEC.md의
 * `explanation_revealed를 언제 보내는가`).
 */
export function markExplanationRevealed(
  presentationId: number,
  sentenceItemId: number,
): Promise<void> {
  return apiPostEvent<void>(
    `/api/study/presentations/${presentationId}/items/${sentenceItemId}/explanation-revealed`,
  )
}

/**
 * 번역이 나오는 **유일한** 경로다. `/next` 응답에는 번역 필드 자체가 없으므로, 이
 * 호출이 성공하기 전에는 화면이 번역을 가질 방법이 없다.
 */
export function revealTranslation(presentationId: number): Promise<TranslationResponse> {
  return apiPostEvent<TranslationResponse>(
    `/api/study/presentations/${presentationId}/translation/reveal`,
  )
}

/** 선택이다. 보내지 않아도 다음 문장으로 넘어갈 수 있다. 204라 body가 없다. */
export function selfReport(presentationId: number, body: SelfReportBody): Promise<void> {
  return apiPostEvent<void>(`/api/study/presentations/${presentationId}/self-report`, { ...body })
}

/** `learning_item_id`를 보내지 않는다. 서버가 `probe_id`의 event에서 읽는다(ADR-009). */
export function respondToProbe(
  presentationId: number,
  body: ProbeResponseBody,
): Promise<ProbeResultResponse> {
  return apiPostEvent<ProbeResultResponse>(
    `/api/study/presentations/${presentationId}/probe-response`,
    { ...body },
  )
}

/**
 * 현재 문장 신고. 닫힌 session과 완료된 presentation에서도 받는 유일한 상호작용이지만
 * (05_API_SPEC.md의 상태 게이트) **MVP UI는 현재 문장에서만 제공한다** --- 지난 문장을
 * 신고하는 화면은 Future다.
 */
export function flagContent(presentationId: number, body: ContentFlagBody): Promise<void> {
  return apiPostEvent<void>(`/api/study/presentations/${presentationId}/flag`, {
    reason: body.reason,
    // `undefined`는 JSON에서 사라진다. 서버 기본값과 같게 명시적으로 null을 보낸다.
    note: body.note ?? null,
  })
}

// --------------------------------------------------------------------------
// history
// --------------------------------------------------------------------------

/**
 * 읽기 전용이다. 행을 만들지 않고 event도 남기지 않으며 `last_activity_at`과
 * `active_seconds`를 건드리지 않는다(05_API_SPEC.md의 `History`).
 *
 * 대상 사용자를 지정하는 파라미터가 없다 --- 서버가 요청 사용자의 행만 담는다.
 */
export function fetchSessionHistory(): Promise<HistorySessionsResponse> {
  return apiGet<HistorySessionsResponse>('/api/history/sessions')
}

export function fetchItemHistory(): Promise<HistoryItemsResponse> {
  return apiGet<HistoryItemsResponse>('/api/history/items')
}
