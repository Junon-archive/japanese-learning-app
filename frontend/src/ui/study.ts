/**
 * 학습 화면. 세션 시작 -> 문장 -> Next -> 진행 -> 종료/연장의 한 루프.
 *
 * 이 파일이 지키는 것들. 전부 화면에서는 잘 도는 것처럼 보이기 때문에 주석으로 남긴다.
 *
 * 1.  **`/next` 전에 반드시 `/complete`가 성공한다.** `/complete` 없이 `/next`를 부르면
 *     `열린 presentation 불변식` 때문에 **같은 문장이 다시 온다.** 화면은 정상 진행처럼
 *     보이고(같은 payload를 다시 그린다) 사용자만 제자리를 걷는다. 그래서 `/complete`가
 *     던지면 `/next`를 부르지 않는다.
 * 2.  **단일 비행.** `busy` 하나로 막는다. 연타가 두 번의 진행이 되면 노출이 늘어난다
 *     --- 노출은 제시당 item당 1회다.
 * 3.  **주기적 호출이 없다.** 진행은 `/complete` 직후 `GET /api/study/session` 한 번으로만
 *     움직인다. 상호작용 endpoint를 주기 호출하면 서버의 `touch()`가 자리를 비운 시간을
 *     학습 시간으로 누적한다(05_API_SPEC.md). `GET /session`은 `touch()`하지 않는다.
 * 4.  **`beforeunload` / `visibilitychange` / `pagehide`에 아무것도 달지 않는다.
 *     `sendBeacon`을 쓰지 않는다.** 사용자가 보지 않은 문장이 완료로 확정되면 없던
 *     노출이 생긴다(불변식 #2: 부재를 완료로 추론하지 않는다). 탭을 닫고 돌아오면 같은
 *     문장이 `열린 presentation 불변식`으로 그대로 다시 나온다.
 * 5.  **409를 받은 요청을 재전송하지 않는다.** 게이트 409(닫힌 session / 완료된
 *     presentation)면 상호작용을 멈추고 `POST /api/study/session`으로 현재 session을
 *     다시 얻은 뒤 `/next`로 진행한다. 재전송은 무한 루프다. 반면 `노출당 evidence
 *     상한`의 409는 재획득 대상이 **아니다** --- 서버가 이미 답을 받아 뒀다는 뜻이므로
 *     그 자리에서 "이미 기록했습니다"로 끝낸다(`reportInteractionFailure`).
 * 6.  **`presentation: null`은 오류가 아니다.** 짧은 안내와 **수동** 재시도 버튼을 둔다.
 *     자동 재시도 루프를 만들지 않는다(무한 spinner 금지).
 */

import { ApiError } from '../api'
import {
  clickItem,
  completePresentation,
  extendSession,
  fetchNextPresentation,
  fetchOpenSession,
  finishSession,
  flagContent,
  markExplanationRevealed,
  respondToProbe,
  revealTranslation,
  selfReport,
  startSession,
} from '../endpoints'
import type { Presentation, StudySession } from '../types'
import type { InteractionFailure, InteractionOps, InteractionsHandle } from './interactions'
import { createInteractions } from './interactions'
import { errorMessage } from './api-failure'
import { renderLogoutButton } from './logout'
import { MESSAGES, renderNotice, showToast } from './notice'
import { renderProgress, sessionProgress } from './progress'
import { showScreen } from './screen'
import { renderSentence } from './segments'
import { renderSessionEndChoice, renderSessionFinished } from './session-end'
import { renderTopBar } from './topbar'

export type StudyActions = {
  /** 상단바 앱 이름. study session을 닫지 않는다(03_UI_UX_SPEC.md의 `상단바`). */
  onHome: () => void
  onUnauthenticated: () => void
  onOpenHistory: () => void
  /** auth session이 폐기됐다(또는 이미 없었다). 호출부가 선택 홈으로 보낸다. */
  onLoggedOut: () => void
}

/**
 * `signal`은 로그인 영역의 것이다. 떠났으면(abort) 화면을 그리지 않고 `POST /api/study/session`도
 * 보내지 않는다 --- 로그인 확인이나 로그인 성공이 늦게 도착해도 study session을 만들거나 resume하지 않는다.
 */
export function mountStudy(root: HTMLElement, signal: AbortSignal, actions: StudyActions): void {
  const onUnauthenticated = actions.onUnauthenticated

  const screen = document.createElement('main')
  screen.className = 'screen study'

  const progressSlot = document.createElement('header')
  progressSlot.className = 'progress-slot'

  // 상단바 메뉴. MVP-01에서 화면 안에 있던 `학습 기록`과 `로그아웃`을 옮긴 것이다(03_UI_UX_SPEC.md의
  // `상단바`). 메뉴를 늘리지 않는다. 후리가나 토글은 이 배열에 더해진다.
  const historyButton = document.createElement('button')
  historyButton.type = 'button'
  historyButton.className = 'topbar-button history-link'
  historyButton.textContent = '학습 기록'
  historyButton.addEventListener('click', actions.onOpenHistory)

  // 확인 대화상자도 계정 관리 화면도 없고, 실패하면 화면을 바꾸지 않고 문구만 띄운다.
  const logoutButton = renderLogoutButton({
    onLoggedOut: actions.onLoggedOut,
    onFailure: (message) => {
      setNotice(renderNotice(message, 'error'))
    },
  })

  const topBar = renderTopBar({ onHome: actions.onHome, actions: [historyButton, logoutButton] })

  // 화면 제목. 보이는 제목을 두지 않고 스크린 리더와 포커스 이동에만 쓴다.
  const title = document.createElement('h1')
  title.className = 'visually-hidden'
  title.textContent = '오늘의 학습'

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  const sentenceSlot = document.createElement('section')
  sentenceSlot.className = 'sentence-box'

  // 설명 패널 / 번역 / probe / 신고가 붙는 자리(`ui/interactions.ts`). **번역 노드를
  // 미리 만들어 두지 않는다** --- reveal 응답을 받은 뒤에 만들어야 "호출 후 공개"가
  // 참이 된다. 이 슬롯은 컨트롤러 노드 하나만 담는다.
  const interactionSlot = document.createElement('div')
  interactionSlot.className = 'interaction-slot'

  const endSlot = document.createElement('div')
  endSlot.className = 'end-slot'

  const nextButton = document.createElement('button')
  nextButton.type = 'button'
  nextButton.className = 'primary next'
  nextButton.textContent = '다음 문장'
  nextButton.disabled = true

  const foot = document.createElement('footer')
  foot.className = 'study-foot'
  foot.append(nextButton)

  screen.append(
    topBar,
    title,
    progressSlot,
    noticeSlot,
    sentenceSlot,
    interactionSlot,
    endSlot,
    foot,
  )
  showScreen(root, screen, signal)

  let session: StudySession | null = null
  let presentation: Presentation | null = null
  let interactions: InteractionsHandle | null = null
  let busy = false

  // ----------------------------------------------------------------------
  // 렌더
  // ----------------------------------------------------------------------

  function setNotice(node: HTMLElement | null): void {
    if (node === null) {
      noticeSlot.replaceChildren()
      return
    }
    noticeSlot.replaceChildren(node)
  }

  /** 수동 재시도 안내. 자동으로 다시 부르지 않는다. */
  function noticeWithRetry(message: string, label: string, task: () => Promise<void>): HTMLElement {
    return renderNotice(message, 'error', {
      label,
      onClick: () => {
        setNotice(null)
        void run(task)
      },
    })
  }

  function applySession(next: StudySession): void {
    session = next
    progressSlot.replaceChildren(renderProgress(next))
    // 도달은 세션 종료가 아니다. 선택지를 **덧붙이고** 문장은 그대로 둔다.
    endSlot.replaceChildren(
      ...(sessionProgress(next).reached
        ? [renderSessionEndChoice({ onFinish: handleFinish, onExtend: handleExtend })]
        : []),
    )
  }

  function showSentence(next: Presentation): void {
    presentation = next
    // 문장의 tappable span과 상호작용 영역은 서로 다른 슬롯에 있다. span이 눌리면 그
    // 컨트롤러의 `tapItem`으로 들어간다.
    const handle = createInteractions(next, interactionOps(next))
    interactions = handle
    sentenceSlot.replaceChildren(
      renderSentence(next.render_segments, (sentenceItemId) => {
        handle.tapItem(sentenceItemId)
      }),
    )
    interactionSlot.replaceChildren(handle.element)
    nextButton.disabled = false
  }

  function clearSentence(): void {
    presentation = null
    // 컨트롤러를 놓는다. 응답이 늦게 도착해도 이미 떼어낸 자기 노드에만 그린다.
    interactions = null
    sentenceSlot.replaceChildren()
    interactionSlot.replaceChildren()
    nextButton.disabled = true
  }

  /**
   * 상호작용 호출부. **path와 idempotency key를 아는 것은 여기뿐이다** --- 컨트롤러는
   * `api.ts`도 `endpoints.ts`도 모른다.
   */
  function interactionOps(current: Presentation): InteractionOps {
    const pid = current.presentation_id
    return {
      clickItem: (sentenceItemId) => clickItem(pid, sentenceItemId),
      markExplanationRevealed: (sentenceItemId) => markExplanationRevealed(pid, sentenceItemId),
      revealTranslation: async () => (await revealTranslation(pid)).korean_translation,
      selfReport: (sentenceItemId, value) =>
        selfReport(pid, { sentence_item_id: sentenceItemId, value }),
      respondToProbe: async (probeId, value) => {
        // 서버가 준 option 값을 **그대로** 돌려보낸다. 모르는 값이라 화면이 원문을
        // 보여준 경우에도 같다 --- client가 목록을 고쳐 보내면 그 답이 위조가 된다.
        const result = await respondToProbe(pid, { probe_id: probeId, value })
        return result.value
      },
      flagContent: (reason, note) => flagContent(pid, { reason, note }),
      reportFailure: reportInteractionFailure,
    }
  }

  /**
   * 상호작용 실패를 처리하고 **무엇이었는지**를 컨트롤러에 알린다.
   *
   * 409를 사유로 가른다(05_API_SPEC.md의 `409 사유 구분`). 게이트 409는 화면 상태가
   * 서버와 어긋났다는 뜻이라 session 재획득으로 이어지고, `EvidenceAlreadyRecorded`는
   * 서버가 이미 답을 받아 뒀다는 뜻이라 **어떤 재시도도 성공하지 못한다**(ADR-018).
   * 알 수 없는 사유는 일반 오류로 다룬다 --- 추측해서 재획득하지 않는다.
   */
  function reportInteractionFailure(error: unknown): InteractionFailure {
    if (error instanceof ApiError) {
      if (error.kind === 'Unauthenticated') {
        onUnauthenticated()
        return { kind: 'handled' }
      }
      if (error.kind === 'StateGate') {
        if (error.conflictReason === 'EvidenceAlreadyRecorded') {
          return { kind: 'alreadyRecorded' }
        }
        if (
          error.conflictReason === 'SessionFinished' ||
          error.conflictReason === 'PresentationCompleted'
        ) {
          // 거부된 요청을 재전송하지 않는다. 현재 session을 다시 얻는다.
          void run(recoverSession)
          return { kind: 'handled' }
        }
      }
    }
    return { kind: 'message', text: errorMessage(error) }
  }

  function setBusy(value: boolean): void {
    screen.classList.toggle('busy', value)
    // 상단바는 잠그지 않는다. 요청을 기다리는 동안에도 앱 이름·학습 기록·로그아웃으로 나갈 수 있다.
    const topBarButtons = new Set(topBar.querySelectorAll('button'))
    for (const button of screen.querySelectorAll('button')) {
      if (topBarButtons.has(button)) continue
      button.disabled = value
    }
    if (!value) {
      nextButton.disabled = presentation === null
      // 위 루프가 화면의 **모든** 버튼을 다시 켰다. 잠겨 있어야 하는 self-report/probe
      // 버튼이 되살아나지 않게 상호작용 영역을 자기 상태로 다시 그린다.
      interactions?.refresh()
    }
  }

  // ----------------------------------------------------------------------
  // 흐름
  // ----------------------------------------------------------------------

  /** 단일 비행. 진행 중이면 새 작업을 시작하지 않는다. */
  async function run(task: () => Promise<void>, failureMessage?: string): Promise<void> {
    if (busy) return
    busy = true
    setBusy(true)
    try {
      await task()
    } catch (error) {
      await handleError(error, failureMessage)
    } finally {
      busy = false
      setBusy(false)
    }
  }

  async function begin(): Promise<void> {
    // 떠난 화면은 새 화면 진입 요청을 시작하지 않는다(04_SECURITY_AND_DATA.md의 `모듈 경계`).
    if (signal.aborted) return
    const started = await startSession()
    applySession(started.session)
    setNotice(null)
    // 한 번 사라지는 안내(토스트). 학습 진행을 막지 않는다(03_UI_UX_SPEC.md의 `세션 시작 안내`).
    if (started.timed_out_session_id !== null) {
      // id 값 자체는 화면에 내지 않는다. 사용자에게 뜻이 없는 내부 id다.
      showToast(MESSAGES.previousSessionTimedOut)
    } else if (started.resumed) {
      showToast(MESSAGES.sessionResumed)
    }
    await loadNext()
  }

  async function loadNext(): Promise<void> {
    const current = session
    if (current === null) return
    const response = await fetchNextPresentation(current.session_id)
    if (response.presentation === null) {
      clearSentence()
      setNotice(
        renderNotice(MESSAGES.emptyPool, 'info', {
          label: MESSAGES.retry,
          onClick: () => {
            setNotice(null)
            void run(loadNext)
          },
        }),
      )
      return
    }
    showSentence(response.presentation)
  }

  /** `Next`. `/complete` -> `GET /session` -> `/next` 순서를 바꾸지 않는다. */
  async function advance(): Promise<void> {
    const current = presentation
    if (current === null || session === null) return
    setNotice(null)

    try {
      await completePresentation(current.presentation_id)
    } catch (error) {
      // 완료가 실패했다. **여기서 멈춘다** --- `/next`를 부르면 같은 문장이 다시 와서
      // 정상 진행처럼 보인다. 문장은 화면에 그대로 두고 실패를 적는다.
      await handleError(error, MESSAGES.saveFailed)
      return
    }
    clearSentence()

    // 진행 갱신. 조회이므로 `last_activity_at`과 `active_seconds`를 건드리지 않는다.
    await refreshSession()
    if (session === null) return
    await loadNext()
  }

  async function refreshSession(): Promise<void> {
    const open = await fetchOpenSession()
    if (open.session === null) {
      // 다른 경로(직접 종료 / 다른 탭)로 이미 닫혔다. 자동으로 새 세션을 만들지 않는다.
      session = null
      clearSentence()
      progressSlot.replaceChildren()
      endSlot.replaceChildren()
      setNotice(
        renderNotice(MESSAGES.sessionClosedElsewhere, 'info', {
          label: MESSAGES.startNewSession,
          onClick: () => {
            setNotice(null)
            void run(begin)
          },
        }),
      )
      return
    }
    applySession(open.session)
  }

  function handleFinish(): void {
    void run(async () => {
      const current = session
      if (current === null) return
      const finished = await finishSession(current.session_id)
      session = finished
      presentation = null
      // 학습이 끝났으므로 문장도 Next도 남기지 않는다.
      screen.replaceChildren(topBar, renderSessionFinished(finished))
    }, MESSAGES.saveFailed)
  }

  function handleExtend(): void {
    void run(async () => {
      const current = session
      if (current === null) return
      // 응답이 갱신된 session payload다. 연장분은 `extended_minutes`로 온다.
      applySession(await extendSession(current.session_id))
    }, MESSAGES.saveFailed)
  }

  // ----------------------------------------------------------------------
  // 오류
  // ----------------------------------------------------------------------

  async function handleError(error: unknown, failureMessage?: string): Promise<void> {
    if (error instanceof ApiError) {
      if (error.kind === 'Unauthenticated') {
        onUnauthenticated()
        return
      }
      if (error.kind === 'OriginRejected') {
        // 배포 설정 문제다. 재시도 버튼을 주지 않는다 --- 눌러도 같은 403이다.
        setNotice(renderNotice(MESSAGES.originRejected, 'error'))
        return
      }
      if (error.kind === 'StateGate') {
        await recoverSession()
        return
      }
    }
    // 나머지는 문구 + 수동 재시도. 저장 실패는 진행한 것처럼 보이지 않게 문구가 다르다.
    setNotice(noticeWithRetry(failureMessage ?? errorMessage(error), MESSAGES.retry, retryNow))
  }

  /**
   * 409 복구. 거부된 요청을 다시 보내지 않고 현재 session을 다시 얻는다.
   *
   * 이 안에서 다시 실패하면 **재귀하지 않는다.** 안내와 수동 재시도로 끝낸다.
   */
  async function recoverSession(): Promise<void> {
    clearSentence()
    try {
      const started = await startSession()
      applySession(started.session)
      setNotice(renderNotice(MESSAGES.sessionChanged, 'info'))
      await loadNext()
    } catch (error) {
      if (error instanceof ApiError && error.kind === 'Unauthenticated') {
        onUnauthenticated()
        return
      }
      setNotice(noticeWithRetry(errorMessage(error), MESSAGES.retry, retryNow))
    }
  }

  /** 수동 재시도의 기본 동작. 지금 상태를 다시 읽는 것이지 실패한 요청의 재전송이 아니다. */
  function retryNow(): Promise<void> {
    if (session === null) return begin()
    return resume()
  }

  /**
   * 진행 상태를 다시 읽고 문장이 없으면 받아온다.
   *
   * `/complete`가 실패해 아직 열려 있는 presentation은 `/next`가 **그것을 그대로**
   * 돌려주므로(열린 presentation 불변식) 문장을 건너뛰지도 중복 노출하지도 않는다.
   */
  async function resume(): Promise<void> {
    await refreshSession()
    if (session === null || presentation !== null) return
    await loadNext()
  }

  nextButton.addEventListener('click', () => {
    void run(advance)
  })

  void run(begin)
}
