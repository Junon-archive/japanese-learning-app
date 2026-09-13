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
 * -   (D3 임시) 12분 진행 표시와 `오늘 학습 완료`/`더 학습하기`를 뺐다. fixture 문장을 차례로
 *     보여주고 끝에 처음부터 다시 보기만 둔다. 진도 저장·다시 보기·probe·완료 화면은 D6에서
 *     이 파일을 다시 쓸 때 들어온다.
 * -   `beforeunload`/`pagehide`/`visibilitychange`에 아무것도 달지 않는다.
 */

import type { PublicScreenContext } from '../routes'
import type { ContentFlagReason, ExplicitSignal } from '../types'
import type { InteractionOps } from '../ui/interactions'
import { createInteractions } from '../ui/interactions'
import { MESSAGES, renderNotice } from '../ui/notice'
import { showScreen } from '../ui/screen'
import { renderSentence } from '../ui/segments'
import { renderTopBar } from '../ui/topbar'
import type { DemoSentence } from './fixture'
import { DEMO_SENTENCES } from './fixture'

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

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  const sentenceSlot = document.createElement('section')
  sentenceSlot.className = 'sentence-box'

  const interactionSlot = document.createElement('div')
  interactionSlot.className = 'interaction-slot'

  const nextButton = document.createElement('button')
  nextButton.type = 'button'
  nextButton.className = 'primary next'
  nextButton.textContent = '다음 문장'

  const foot = document.createElement('footer')
  foot.className = 'study-foot'
  foot.append(nextButton)

  screen.append(topBar, title, banner, noticeSlot, sentenceSlot, interactionSlot, foot)
  showScreen(ctx.root, screen, ctx.signal)

  // ----------------------------------------------------------------------
  // 상태. **메모리에만 있다.**
  // ----------------------------------------------------------------------

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
      // 실패는 fixture에 설명이 빠진 경우뿐이다. 예외 메시지·fixture id를 화면에 내지 않고 고정 문구만 쓴다.
      reportFailure: () => ({ kind: 'message', text: MESSAGES.notFound }),
    }
  }

  // ----------------------------------------------------------------------
  // 렌더
  // ----------------------------------------------------------------------

  function setNotice(node: HTMLElement | null): void {
    noticeSlot.replaceChildren(...(node === null ? [] : [node]))
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
    index += 1
    showSentence()
  }

  function restart(): void {
    index = 0
    setNotice(renderNotice(DEMO_MESSAGES.restarted, 'info'))
    showSentence()
  }

  nextButton.addEventListener('click', advance)

  showSentence()
}
