/**
 * 학습 기록 화면. `03_UI_UX_SPEC.md`의 `History` --- **두 목록으로 끝난다.**
 *
 * 이 파일이 하지 않는 것들이 요구사항의 절반이다.
 *
 * -   **`50`(고정 상한)을 적지 않는다.** 잘렸는지는 서버가 응답의 `truncated`로 알려준다.
 *     받은 행 수를 상한과 비교해 추측하면, 행이 정확히 상한만큼인 사용자에게 "잘렸다"고
 *     거짓을 말한다. 그래서 화면은 boolean 하나만 본다(05_API_SPEC.md의 `개수 상한`).
 * -   **`null`을 0이나 빈 문자열로 뭉개지 않는다.** `comprehension_mastery`가 `null`인
 *     것은 "아직 evidence가 없음"이고 0%는 "능력이 0"으로 읽힌다
 *     (02_LEARNING_POLICY.md). `next_review_at`도 같다.
 * -   더 보기·기간 선택·검색·정렬 변경·통계·차트·item별 상세를 두지 않는다
 *     (`00_SCOPE.md`의 `advanced analytics`). 여기서 학습으로 이어지는 버튼도 두지
 *     않는다 --- 학습은 Study Screen에서만 일어난다.
 * -   `표현 보관함`과 `설정`은 **MVP 화면이 아니다.** 지탱하는 API가 없다.
 *
 * 목록 렌더러는 순수 함수다(데이터 -> DOM). 화면을 띄우는 `mountHistory`만 endpoint를
 * 부른다.
 *
 * **날짜는 `users.timezone` 기준이다.** `04_DB_SPEC.md`의 공통 규칙이 "사용자 local day
 * 경계는 `users.timezone`으로 계산한다"이고, `09_BACKGROUND_JOBS.md`가 일일 비용 한도만
 * UTC로 예외 처리하면서 그 규칙을 **학습 데이터 집계 규칙**이라고 부른다. history 날짜는
 * 학습 데이터다. 기기 시간대로 찍으면 해외에서 접속한 사용자에게 같은 세션이 다른 날로
 * 보인다. 값은 `GET /api/auth/me`의 `timezone`이며 **화면이 새 요청을 만들지 않는다**
 * --- 부팅에서 이미 받은 것을 `main.ts`가 내려준다.
 */

import { ApiError } from '../api'
import { fetchItemHistory, fetchSessionHistory } from '../endpoints'
import type { HistoryItem, HistoryItemsResponse, HistorySession, HistorySessionsResponse } from '../types'
import { errorMessage } from './api-failure'
import { itemTypeLabel } from './explanation'
import { renderLogoutButton } from './logout'
import { MESSAGES, renderNotice } from './notice'
import { showScreen } from './screen'
import { renderTopBar } from './topbar'

const HISTORY_MESSAGES = {
  title: '학습 기록',
  back: '학습으로 돌아가기',
  sessions: '최근 학습',
  items: '학습한 표현',
  emptySessions: '아직 학습 기록이 없어요.',
  emptyItems: '아직 학습한 표현이 없어요.',
  /** 상한에 걸려 잘렸다는 사실. 숨기면 사용자가 기록이 사라졌다고 읽는다. 상한 숫자를 적지 않는다. */
  truncated: '오래된 기록은 여기서 보이지 않아요.',
  inProgress: '진행 중',
  /** `comprehension_mastery`가 `null`일 때. 0%로 적지 않는다. */
  noMastery: '아직 평가 없음',
  noReview: '복습 예정 없음',
  /** 시간대를 쓸 수 없을 때. 조용히 다른 기준으로 찍지 않는다. */
  timezoneFallback: '학습 시간대를 확인하지 못했어요. 날짜는 이 기기 기준으로 보여 드려요.',
} as const

const SECONDS_PER_MINUTE = 60

/** `iso` -> `2026-09-12`. */
export type DateFormatter = (iso: string) => string

export type DateFormat = {
  format: DateFormatter
  /** `false`면 요청한 시간대를 쓸 수 없어 기기 시간대로 떨어졌다는 뜻이다. */
  usesRequestedZone: boolean
}

/**
 * `users.timezone`으로 날짜를 찍는 formatter.
 *
 * -   `Intl.DateTimeFormat`의 `timeZone` 옵션만 쓴다. tz 라이브러리를 넣지 않는다.
 * -   locale을 `'en-US'`로 고정하고 **`formatToParts`로 조각을 골라 직접 조립한다.** 그래야
 *     기기 locale이 무엇이든 `2026-09-12` 한 모양이고, 숫자 체계가 다른 locale에서 자릿수가
 *     바뀌지 않는다.
 * -   **`Asia/Seoul`을 여기 적지 않는다.** 기본값은 서버의 `users.timezone` 컬럼 기본값이며
 *     화면의 것이 아니다.
 * -   서버가 `Intl`이 모르는 값을 주면 생성자가 `RangeError`를 던진다. 그때는 **기기
 *     시간대로 떨어지고 그 사실을 화면에 적는다**(`usesRequestedZone: false`). 던지게 두면
 *     기록 화면 전체가 빈 화면이 되고, 조용히 떨어지면 사용자가 잘못된 날짜를 사실로 읽는다.
 */
export function dateFormat(timeZone: string): DateFormat {
  try {
    return { format: partsFormatter(timeZone), usesRequestedZone: true }
  } catch {
    // 사유(어떤 값이 왜 거부됐는지)는 화면에 담지 않는다. 사용자가 고칠 수 있는 것이 아니다.
    return { format: partsFormatter(undefined), usesRequestedZone: false }
  }
}

function partsFormatter(timeZone: string | undefined): DateFormatter {
  const formatter = new Intl.DateTimeFormat('en-US', {
    timeZone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  })
  return (iso) => {
    const parts = formatter.formatToParts(new Date(iso))
    const pick = (type: string): string => parts.find((part) => part.type === type)?.value ?? ''
    return `${pick('year')}-${pick('month')}-${pick('day')}`
  }
}

function row(className: string, cells: string[]): HTMLElement {
  const line = document.createElement('li')
  line.className = className
  for (const cell of cells) {
    const span = document.createElement('span')
    span.className = 'history-cell'
    span.textContent = cell
    line.append(span)
  }
  return line
}

function section(title: string, body: HTMLElement[]): HTMLElement {
  const box = document.createElement('section')
  box.className = 'history-section'

  const heading = document.createElement('h2')
  heading.className = 'history-heading'
  heading.textContent = title

  box.append(heading, ...body)
  return box
}

/** 잘림 문구. **`truncated`가 `true`일 때만** 만든다. */
function truncatedLine(truncated: boolean): HTMLElement[] {
  if (!truncated) return []
  const line = document.createElement('p')
  line.className = 'history-truncated'
  line.textContent = HISTORY_MESSAGES.truncated
  return [line]
}

function emptyLine(text: string): HTMLElement {
  const line = document.createElement('p')
  line.className = 'history-empty'
  line.textContent = text
  return line
}

function sessionCells(session: HistorySession, format: DateFormatter): string[] {
  const minutes = Math.floor(session.active_seconds / SECONDS_PER_MINUTE)
  return [
    format(session.started_at),
    // 진행 중인 session은 종료 시각 자리에 이것을 적는다.
    session.ended_at === null ? HISTORY_MESSAGES.inProgress : format(session.ended_at),
    `학습 ${minutes}분 · ${session.completed_sentence_count}문장 완료`,
  ]
}

export function renderSessionHistory(
  data: HistorySessionsResponse,
  format: DateFormatter,
): HTMLElement {
  if (data.sessions.length === 0) {
    return section(HISTORY_MESSAGES.sessions, [emptyLine(HISTORY_MESSAGES.emptySessions)])
  }

  const list = document.createElement('ul')
  list.className = 'history-list'
  for (const session of data.sessions) {
    list.append(row('history-row', sessionCells(session, format)))
  }
  return section(HISTORY_MESSAGES.sessions, [list, ...truncatedLine(data.truncated)])
}

/** 표현 이름과 `{유형} · {mastery}% · 본 횟수 {n}회 · 다음 복습 {날짜}` 한 줄. 값은 서버 값이다. */
function itemCells(item: HistoryItem, format: DateFormatter): string[] {
  return [
    item.lemma,
    [
      itemTypeLabel(item.item_type),
      item.comprehension_mastery === null
        ? HISTORY_MESSAGES.noMastery
        : `${Math.round(item.comprehension_mastery * 100)}%`,
      `본 횟수 ${item.exposure_count}회`,
      item.next_review_at === null
        ? HISTORY_MESSAGES.noReview
        : `다음 복습 ${format(item.next_review_at)}`,
    ].join(' · '),
  ]
}

export function renderItemHistory(data: HistoryItemsResponse, format: DateFormatter): HTMLElement {
  if (data.items.length === 0) {
    return section(HISTORY_MESSAGES.items, [emptyLine(HISTORY_MESSAGES.emptyItems)])
  }

  const list = document.createElement('ul')
  list.className = 'history-list'
  for (const item of data.items) {
    list.append(row('history-row', itemCells(item, format)))
  }
  return section(HISTORY_MESSAGES.items, [list, ...truncatedLine(data.truncated)])
}

export type HistoryActions = {
  /** `GET /api/auth/me`의 `timezone`. 로그인 진입에서 이미 받은 값이다(새 요청을 만들지 않는다). */
  timezone: string
  onHome: () => void
  onBack: () => void
  onUnauthenticated: () => void
  /** auth session이 폐기됐다(또는 이미 없었다). 호출부가 선택 홈으로 보낸다. */
  onLoggedOut: () => void
}

/**
 * 읽기 전용 화면이므로 여기에 상태 변경도 자동 재시도도 없다.
 *
 * 상단바 오른쪽은 `로그아웃` 하나다. 로그인 영역 공통 틀의 메뉴이지 화면 내용이 아니다 --- 화면 내용은
 * 여전히 두 목록과 `학습으로 돌아가기`로 끝난다(03_UI_UX_SPEC.md의 `로그아웃`). 문장이 없어 후리가나
 * 토글이 없고, `학습 기록`은 자기 자신이라 없다.
 */
export function mountHistory(root: HTMLElement, signal: AbortSignal, actions: HistoryActions): void {
  const screen = document.createElement('main')
  screen.className = 'screen history'

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  const logoutButton = renderLogoutButton({
    onLoggedOut: actions.onLoggedOut,
    onFailure: (message) => {
      noticeSlot.replaceChildren(renderNotice(message, 'error'))
    },
  })
  const topBar = renderTopBar({ onHome: actions.onHome, actions: [logoutButton] })

  const head = document.createElement('header')
  head.className = 'history-head'

  const title = document.createElement('h1')
  title.className = 'history-title'
  title.textContent = HISTORY_MESSAGES.title

  const back = document.createElement('button')
  back.type = 'button'
  back.className = 'history-back'
  back.textContent = HISTORY_MESSAGES.back
  back.addEventListener('click', actions.onBack)
  head.append(title, back)

  const body = document.createElement('div')
  body.className = 'history-body'

  screen.append(topBar, head, noticeSlot, body)
  showScreen(root, screen, signal)

  const dates = dateFormat(actions.timezone)

  function load(): void {
    Promise.all([fetchSessionHistory(), fetchItemHistory()])
      .then(([sessions, items]) => {
        body.replaceChildren(
          // 시간대를 쓸 수 없었으면 그 사실을 먼저 적는다. 조용히 다른 기준으로 찍지 않는다.
          ...(dates.usesRequestedZone
            ? []
            : [renderNotice(HISTORY_MESSAGES.timezoneFallback, 'info')]),
          renderSessionHistory(sessions, dates.format),
          renderItemHistory(items, dates.format),
        )
      })
      .catch((error: unknown) => {
        // 떠난 화면은 로그인 화면으로 가로채지 않는다.
        if (signal.aborted) return
        if (error instanceof ApiError && error.kind === 'Unauthenticated') {
          actions.onUnauthenticated()
          return
        }
        body.replaceChildren(
          renderNotice(errorMessage(error), 'error', { label: MESSAGES.retry, onClick: load }),
        )
      })
  }

  load()
}
