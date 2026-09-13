/**
 * Public Demo 화면. **`api.ts`도 `endpoints.ts`도 import하지 않는다.**
 *
 * 그것이 이 기능의 불변식이다: demo는 static frontend fixture이고 demo 전용
 * endpoint·DB·provider가 없다(`04_SECURITY_AND_DATA.md`, `05_API_SPEC.md`). 그래서
 * backend/LLM 장애와 구조적으로 독립이다(`10_ERROR_HANDLING.md`). import 한 줄이
 * 들어오면 `tests/unit/demo-isolation.test.ts`가 **전이적** import 그래프를 훑어
 * 빨개진다.
 *
 * 실제 학습 UX와 최대한 동일해야 하므로(`03_UI_UX_SPEC.md`의 `Demo`) 화면을 새로 만들지
 * 않고 **학습 화면의 렌더러를 그대로 재사용한다.** `ui/interactions.ts`가 호출을
 * `InteractionOps`로 주입받게 되어 있어서 그 구멍에 fixture를 꽂으면 끝이다 --- 탭, 설명,
 * `explanation_revealed` 시점, 번역 reveal, probe 잠금, 신고가 전부 실제 화면과 같은
 * 코드로 돈다.
 *
 * -   **상태는 메모리(이 closure)에만 있다.** localStorage·sessionStorage·cookie·
 *     IndexedDB를 쓰지 않는다. 탭을 닫으면 사라진다.
 * -   타이머도 주기 호출도 없다. 진행은 `다음 문장`을 누를 때만 움직인다.
 * -   `beforeunload`/`pagehide`/`visibilitychange`에 아무것도 달지 않는다.
 */

import type { PublicScreenContext } from '../routes'
import type { ContentFlagReason, ExplicitSignal } from '../types'
import type { InteractionOps } from '../ui/interactions'
import { createInteractions } from '../ui/interactions'
import { MESSAGES, renderNotice } from '../ui/notice'
import { renderProgress, sessionProgress } from '../ui/progress'
import { showScreen } from '../ui/screen'
import { renderSentence } from '../ui/segments'
import { renderSessionEndChoice, renderSessionFinished } from '../ui/session-end'
import { renderTopBar } from '../ui/topbar'
import type { DemoSentence } from './fixture'
import {
  DEMO_EXTENDED_MINUTES,
  DEMO_SECONDS_PER_SENTENCE,
  DEMO_SENTENCES,
  DEMO_SESSION,
} from './fixture'

/** demo 전용 문구. 실제 화면 문구(`ui/notice.ts`의 `MESSAGES`)와 섞지 않는다. */
const DEMO_MESSAGES = {
  title: '표현 학습 체험',
  banner: '체험 중이에요. 기록은 이 브라우저에만 남아요.',
  /** demo 전용. 요청을 보내지 않으므로 신고가 저장되지 않는다. */
  flagSubmitted: '체험에서는 신고가 저장되지 않아요.',
  lastSentence: '데모 문장을 모두 보았습니다.',
  restart: '처음부터 다시 보기',
  restarted: '데모 문장을 처음부터 다시 보여줍니다.',
} as const

/**
 * `#/demo` route의 화면(`routes.ts`). 나가는 길은 상단바다 --- 앱 이름은 선택 홈, `로그인`은 main.ts가
 * 주입한 로그인 진입을 **넘기기만** 한다.
 */
export function mount(ctx: PublicScreenContext): void {
  const screen = document.createElement('main')
  screen.className = 'screen study demo'

  const topBar = renderTopBar({
    onHome: () => {
      ctx.navigate('#/')
    },
    onLogin: ctx.openLogin,
    actions: [],
  })

  const title = document.createElement('h1')
  title.className = 'demo-title'
  title.textContent = DEMO_MESSAGES.title

  const banner = document.createElement('div')
  banner.className = 'demo-banner'
  banner.setAttribute('role', 'status')

  const bannerText = document.createElement('p')
  bannerText.className = 'demo-banner-text'
  bannerText.textContent = DEMO_MESSAGES.banner

  banner.append(bannerText)

  const progressSlot = document.createElement('header')
  progressSlot.className = 'progress-slot'

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  const sentenceSlot = document.createElement('section')
  sentenceSlot.className = 'sentence-box'

  const interactionSlot = document.createElement('div')
  interactionSlot.className = 'interaction-slot'

  const endSlot = document.createElement('div')
  endSlot.className = 'end-slot'

  const nextButton = document.createElement('button')
  nextButton.type = 'button'
  nextButton.className = 'primary next'
  nextButton.textContent = '다음 문장'

  const foot = document.createElement('footer')
  foot.className = 'study-foot'
  foot.append(nextButton)

  screen.append(topBar, title, banner, progressSlot, noticeSlot, sentenceSlot, interactionSlot, endSlot, foot)
  showScreen(ctx.root, screen, ctx.signal)

  // ----------------------------------------------------------------------
  // 상태. **메모리에만 있다.**
  // ----------------------------------------------------------------------

  const session = { ...DEMO_SESSION }
  /** 사용자가 demo에서 남긴 답. 아무 곳에도 보내지 않고 저장하지도 않는다. */
  const answers: string[] = []
  let index = 0

  // ----------------------------------------------------------------------
  // fixture로 채운 InteractionOps. 실제 화면에서는 이 자리에 endpoint 호출이 들어간다.
  // ----------------------------------------------------------------------

  function demoOps(entry: DemoSentence): InteractionOps {
    return {
      clickItem: async (sentenceItemId) => {
        const explanation = entry.explanations[sentenceItemId]
        if (explanation === undefined) {
          // fixture가 불완전하다는 뜻이다. 성공처럼 보이게 하지 않는다.
          throw new Error(`demo fixture has no explanation for ${sentenceItemId}`)
        }
        return explanation
      },
      // auxiliary signal이다. demo에는 보낼 곳이 없으므로 아무것도 하지 않는다.
      markExplanationRevealed: async () => {},
      revealTranslation: async () => entry.korean_translation,
      selfReport: async (sentenceItemId: number, value: ExplicitSignal) => {
        answers.push(`self-report:${sentenceItemId}:${value}`)
      },
      respondToProbe: async (probeId: number, value: string) => {
        answers.push(`probe:${probeId}:${value}`)
        // 서버와 같게 "기록된 값"을 돌려준다. demo에서는 방금 고른 값이다.
        return value
      },
      flagContent: async (reason: ContentFlagReason, note: string | null) => {
        answers.push(`flag:${reason}:${note ?? ''}`)
      },
      // demo에서는 실패가 없다. 그래도 화면이 문구를 낼 수 있게 채워 둔다.
      reportFailure: (error: unknown) => ({
        kind: 'message',
        text: error instanceof Error ? error.message : '데모 데이터를 불러오지 못했습니다.',
      }),
    }
  }

  // ----------------------------------------------------------------------
  // 렌더
  // ----------------------------------------------------------------------

  function setNotice(node: HTMLElement | null): void {
    noticeSlot.replaceChildren(...(node === null ? [] : [node]))
  }

  function applySession(): void {
    progressSlot.replaceChildren(renderProgress(session))
    // 도달은 세션 종료가 아니다. 선택지를 덧붙이고 문장은 그대로 둔다.
    endSlot.replaceChildren(
      ...(sessionProgress(session).reached
        ? [renderSessionEndChoice({ onFinish: finish, onExtend: extend })]
        : []),
    )
  }

  function showSentence(): void {
    const entry = DEMO_SENTENCES[index]
    if (entry === undefined) {
      sentenceSlot.replaceChildren()
      interactionSlot.replaceChildren()
      nextButton.disabled = true
      setNotice(
        renderNotice(DEMO_MESSAGES.lastSentence, 'info', {
          label: DEMO_MESSAGES.restart,
          onClick: restart,
        }),
      )
      return
    }

    // fixture 응답은 기다림이 없으므로 문장별 signal을 따로 두지 않는다. 화면 signal이면 충분하다.
    const handle = createInteractions(entry.presentation, demoOps(entry), {
      signal: ctx.signal,
      sheetContainer: screen,
      flagSubmittedText: DEMO_MESSAGES.flagSubmitted,
    })
    // Study와 같은 문장 아래 힌트(03_UI_UX_SPEC.md의 화면 문구 표).
    const hint = document.createElement('p')
    hint.className = 'sentence-hint'
    hint.textContent = MESSAGES.sentenceHint
    sentenceSlot.replaceChildren(
      renderSentence(entry.presentation.render_segments, (sentenceItemId) => {
        handle.tapItem(sentenceItemId)
      }),
      hint,
    )
    interactionSlot.replaceChildren(handle.element)
    nextButton.disabled = false
  }

  // ----------------------------------------------------------------------
  // 흐름
  // ----------------------------------------------------------------------

  function advance(): void {
    if (DEMO_SENTENCES[index] === undefined) return
    setNotice(null)
    // 실제 화면에서는 `/complete` 뒤 `GET /session`이 이 값을 갱신한다. 문장 단위다.
    session.active_seconds += DEMO_SECONDS_PER_SENTENCE
    index += 1
    applySession()
    showSentence()
  }

  function restart(): void {
    index = 0
    setNotice(renderNotice(DEMO_MESSAGES.restarted, 'info'))
    showSentence()
  }

  function finish(): void {
    screen.replaceChildren(topBar, title, banner, renderSessionFinished(session))
  }

  function extend(): void {
    // `/extend` 응답이 갱신된 session payload를 주는 것과 같은 모양이다.
    session.extended_minutes += DEMO_EXTENDED_MINUTES
    applySession()
    if (DEMO_SENTENCES[index] === undefined) restart()
  }

  nextButton.addEventListener('click', advance)

  applySession()
  showSentence()
}
