/**
 * Public Demo 화면(`03_UI_UX_SPEC.md`의 `Demo`). **`api.ts`도 `endpoints.ts`도 import하지 않는다.**
 *
 * demo는 static frontend fixture이고 demo 전용 endpoint·DB·provider가 없다(`04_SECURITY_AND_DATA.md`). 그래서
 * backend/LLM 장애와 구조적으로 독립이다. import 한 줄이 들어오면 `tests/unit/demo-isolation.test.ts`가
 * **전이적** import 그래프를 훑어 빨개진다.
 *
 * 실제 학습 UX와 최대한 같아야 하므로 **학습 화면의 렌더러를 그대로 쓴다.** `ui/interactions.ts`의
 * `InteractionOps` 자리에 fixture와 진행 규칙(`progress.ts`)을 꽂는다 --- 탭, 설명 시트, 번역 펼침, probe,
 * 신고가 실제 화면과 같은 코드로 돈다. 후리가나 토글도 Study Screen과 같은 모듈이다.
 *
 * -   진도는 `progress.ts`가 `nc.demo.v1`에 저장한다. 다시 열면 이어서 보여주고, 없거나 맞지 않으면 조용히
 *     처음부터다. 서버로 보내지 않고 학습 신호가 아니다.
 * -   진행 표시는 `본 문장 수 / 전체 문장 수` 하나다. 12분 진행바, `오늘 학습 완료 / 더 학습하기`, 연장이 없다.
 * -   타이머도 주기 호출도 없다. 진행은 `다음 문장`을 누를 때만 움직인다.
 * -   `beforeunload`/`pagehide`/`visibilitychange`에 아무것도 달지 않는다.
 */

import type { PublicScreenContext } from '../routes'
import type { Probe, ProbeResponseValue } from '../types'
import { renderFuriganaToggle } from '../ui/furigana'
import type { InteractionOps } from '../ui/interactions'
import { createInteractions } from '../ui/interactions'
import { MESSAGES, showToast } from '../ui/notice'
import { showScreen } from '../ui/screen'
import { renderSentence } from '../ui/segments'
import { renderTopBar } from '../ui/topbar'
import './demo.css'
import type { DemoProbePick, DemoProgress, DemoView } from './progress'
import {
  DEMO_FIXTURE,
  advance,
  initialProgress,
  isComplete,
  nextView,
  pickProbe,
  readDemoProgress,
  recordProbeAnswer,
  recordSelfReport,
  resetDemoProgress,
  writeDemoProgress,
} from './progress'

/** demo 전용 문구(`03_UI_UX_SPEC.md`의 `화면 문구 표` > `Demo`). 실제 화면 문구(`MESSAGES`)와 섞지 않는다. */
const DEMO_MESSAGES = {
  title: '표현 학습 체험',
  banner: '체험 중이에요. 기록은 이 브라우저에만 남아요.',
  reset: '진도 초기화',
  resetQuestion: '진도를 초기화할까요?',
  resetDetail: '이 브라우저에 남은 체험 기록이 지워져요.',
  resetConfirm: '초기화하기',
  resetCancel: '취소',
  resetDone: '진도를 초기화했어요.',
  /** demo 전용. 요청을 보내지 않으므로 신고가 저장되지 않는다. */
  flagSubmitted: '체험에서는 신고가 저장되지 않아요.',
  next: '다음 문장',
  completeTitle: (total: number) => `${total}문장을 모두 봤어요.`,
  completeThanks: '끝까지 둘러봐 주셔서 고마워요.',
  learnKana: '글자 배우기',
  restart: '처음부터 다시',
  restartNote: '처음부터 다시 하면 체험 기록이 지워져요.',
} as const

/** probe 질문과 선택지는 `Mastery Probe` 절의 고정값이다. demo에는 서버가 없으므로 여기서 채운다. */
const PROBE_PROMPT = '이 표현을 알고 계세요?'
const PROBE_OPTIONS: readonly ProbeResponseValue[] = ['known', 'uncertain', 'unknown', 'skip']

const KANA_HASH = '#/kana'

/**
 * `#/demo` route의 화면(`routes.ts`). 나가는 길은 상단바다 --- 앱 이름은 선택 홈, `로그인`은 main.ts가
 * 주입한 로그인 진입을 **넘기기만** 한다.
 */
export function mount(ctx: PublicScreenContext): void {
  const fixture = DEMO_FIXTURE
  const total = fixture.sentences.length
  let progress: DemoProgress = readDemoProgress() ?? initialProgress(fixture)

  function save(next: DemoProgress): void {
    progress = next
    writeDemoProgress(next)
  }

  function startOver(): void {
    resetDemoProgress()
    progress = initialProgress(fixture)
  }

  /** 후리가나 토글은 문장이 있는 화면에만 둔다(03_UI_UX_SPEC.md의 `상단바`). 완료 화면은 `로그인`뿐이다. */
  function topBar(withFurigana: boolean): HTMLElement {
    return renderTopBar({
      onHome: () => {
        ctx.navigate('#/')
      },
      onLogin: ctx.openLogin,
      actions: withFurigana ? [renderFuriganaToggle()] : [],
    })
  }

  function showCurrent(): void {
    if (isComplete(fixture, progress)) showCompletion()
    else showLearning()
  }

  // ----------------------------------------------------------------------
  // 학습 화면
  // ----------------------------------------------------------------------

  function showLearning(): void {
    const screen = document.createElement('main')
    screen.className = 'screen study demo'

    const title = document.createElement('h1')
    title.className = 'demo-title'
    title.textContent = DEMO_MESSAGES.title

    const banner = document.createElement('div')
    banner.className = 'demo-banner'

    const progressText = document.createElement('p')
    progressText.className = 'demo-progress'

    const sentenceSlot = document.createElement('section')
    sentenceSlot.className = 'sentence-box'

    const interactionSlot = document.createElement('div')
    interactionSlot.className = 'interaction-slot'

    const nextButton = document.createElement('button')
    nextButton.type = 'button'
    nextButton.className = 'primary next'
    nextButton.textContent = DEMO_MESSAGES.next

    const foot = document.createElement('footer')
    foot.className = 'study-foot'
    foot.append(nextButton)

    screen.append(topBar(true), title, banner, progressText, sentenceSlot, interactionSlot, foot)
    showScreen(ctx.root, screen, ctx.signal)

    /** 지금 문장의 수명. 문장을 바꾸거나 화면을 떠나면 abort되어 열린 설명 시트가 닫힌다. */
    let sentence: AbortController | null = null

    function sentenceSignal(): AbortSignal {
      sentence?.abort()
      const controller = new AbortController()
      sentence = controller
      if (ctx.signal.aborted) {
        controller.abort()
      } else {
        ctx.signal.addEventListener('abort', () => {
          controller.abort()
        })
      }
      return controller.signal
    }

    // --- 체험 안내와 진도 초기화(인라인 확인. 시트가 아니다) ---

    const resetButton = document.createElement('button')
    resetButton.type = 'button'
    resetButton.className = 'demo-reset'
    resetButton.textContent = DEMO_MESSAGES.reset
    resetButton.addEventListener('click', showResetConfirm)

    function showBanner(): void {
      const text = document.createElement('p')
      text.className = 'demo-banner-text'
      text.textContent = DEMO_MESSAGES.banner
      const separator = document.createElement('span')
      separator.className = 'demo-banner-separator'
      separator.setAttribute('aria-hidden', 'true')
      separator.textContent = '·'
      banner.replaceChildren(text, separator, resetButton)
    }

    function showResetConfirm(): void {
      const question = document.createElement('p')
      question.className = 'demo-confirm-question'
      question.textContent = DEMO_MESSAGES.resetQuestion

      const detail = document.createElement('p')
      detail.className = 'demo-confirm-detail'
      detail.textContent = DEMO_MESSAGES.resetDetail

      const confirm = document.createElement('button')
      confirm.type = 'button'
      confirm.className = 'demo-reset-confirm'
      confirm.textContent = DEMO_MESSAGES.resetConfirm
      confirm.addEventListener('click', () => {
        startOver()
        renderView()
        showBanner()
        resetButton.focus()
        showToast(DEMO_MESSAGES.resetDone)
      })

      const cancel = document.createElement('button')
      cancel.type = 'button'
      cancel.className = 'demo-reset-cancel'
      cancel.textContent = DEMO_MESSAGES.resetCancel
      cancel.addEventListener('click', () => {
        showBanner()
        resetButton.focus()
      })

      const actions = document.createElement('div')
      actions.className = 'demo-confirm-actions'
      actions.append(confirm, cancel)

      const box = document.createElement('div')
      box.className = 'demo-confirm'
      box.setAttribute('role', 'group')
      box.setAttribute('aria-label', DEMO_MESSAGES.reset)
      box.append(question, detail, actions)
      banner.replaceChildren(box)
      cancel.focus()
    }

    // --- 문장 ---

    function renderView(): void {
      const view = nextView(fixture, progress)
      if (view === null) {
        sentence?.abort()
        showCompletion()
        return
      }
      const signal = sentenceSignal()
      const pick = pickProbe(fixture, progress)
      const presentation =
        pick === null ? view.sentence.presentation : { ...view.sentence.presentation, probe: probeFor(pick) }

      const handle = createInteractions(presentation, demoOps(view, pick), {
        signal,
        sheetContainer: screen,
        flagSubmittedText: DEMO_MESSAGES.flagSubmitted,
      })
      // Study와 같은 문장 아래 힌트(03_UI_UX_SPEC.md의 화면 문구 표).
      const hint = document.createElement('p')
      hint.className = 'sentence-hint'
      hint.textContent = MESSAGES.sentenceHint
      sentenceSlot.replaceChildren(
        renderSentence(view.sentence.presentation.render_segments, (sentenceItemId) => {
          handle.tapItem(sentenceItemId)
        }),
        hint,
      )
      interactionSlot.replaceChildren(handle.element)
      progressText.textContent = `${progress.seen} / ${total}`
    }

    /** fixture로 채운 InteractionOps. 실제 화면에서는 이 자리에 endpoint 호출이 들어간다. */
    function demoOps(view: DemoView, pick: DemoProbePick | null): InteractionOps {
      const { explanations, korean_translation, presentation } = view.sentence
      return {
        clickItem: async (sentenceItemId) => {
          const explanation = explanations[sentenceItemId]
          // fixture가 불완전하다. 성공처럼 보이게 하지 않고, 화면에는 고정 문구만 낸다(reportFailure).
          if (explanation === undefined) throw new Error()
          return explanation
        },
        // auxiliary signal이다. demo에는 보낼 곳이 없다.
        markExplanationRevealed: async () => {},
        revealTranslation: async () => korean_translation,
        selfReport: async (sentenceItemId, value) => {
          const item = presentation.tappable_items.find((entry) => entry.sentence_item_id === sentenceItemId)
          if (item !== undefined) save(recordSelfReport(fixture, progress, item.learning_item_id, value))
        },
        respondToProbe: async (_probeId, value) => {
          if (pick !== null) save(recordProbeAnswer(fixture, progress, pick.learningItemId, value))
          // 서버와 같게 "기록된 값"을 돌려준다. demo에서는 방금 고른 값이다.
          return value
        },
        // 요청을 보내지 않는다. 신고한 문장의 다시 보기 동작도 그대로다.
        flagContent: async () => {},
        reportFailure: () => ({ kind: 'message', text: MESSAGES.notFound }),
      }
    }

    nextButton.addEventListener('click', () => {
      save(advance(fixture, progress))
      renderView()
    })

    showBanner()
    renderView()
  }

  /** probe 표현은 그 표현이 처음 나온 문장의 segment text를 이은 것이다. offset을 계산하지 않는다. */
  function probeFor(pick: DemoProbePick): Probe {
    const { presentation } = fixture.sentences[pick.sentenceIndex]!
    const ids = new Set(
      presentation.tappable_items
        .filter((item) => item.learning_item_id === pick.learningItemId)
        .map((item) => item.sentence_item_id),
    )
    return {
      probe_id: pick.learningItemId,
      learning_item_id: pick.learningItemId,
      prompt: PROBE_PROMPT,
      expression: presentation.render_segments
        .filter((segment) => segment.sentence_item_id !== null && ids.has(segment.sentence_item_id))
        .map((segment) => segment.text)
        .join(''),
      options: [...PROBE_OPTIONS],
    }
  }

  // ----------------------------------------------------------------------
  // 완료 화면. 통계·정답률을 넣지 않는다.
  // ----------------------------------------------------------------------

  function showCompletion(): void {
    const screen = document.createElement('main')
    screen.className = 'screen demo demo-complete'

    const title = document.createElement('h1')
    title.className = 'demo-complete-title'
    title.textContent = DEMO_MESSAGES.completeTitle(total)

    const thanks = document.createElement('p')
    thanks.className = 'demo-complete-thanks'
    thanks.textContent = DEMO_MESSAGES.completeThanks

    const body = document.createElement('section')
    body.className = 'demo-complete-body'
    body.append(title, thanks)

    const kana = document.createElement('button')
    kana.type = 'button'
    kana.className = 'primary demo-learn-kana'
    kana.textContent = DEMO_MESSAGES.learnKana
    kana.addEventListener('click', () => {
      ctx.navigate(KANA_HASH)
    })

    const restart = document.createElement('button')
    restart.type = 'button'
    restart.className = 'secondary demo-restart'
    restart.textContent = DEMO_MESSAGES.restart
    restart.addEventListener('click', () => {
      startOver()
      showCurrent()
    })

    const note = document.createElement('p')
    note.className = 'demo-restart-note'
    note.textContent = DEMO_MESSAGES.restartNote

    const foot = document.createElement('footer')
    foot.className = 'demo-complete-foot'
    foot.append(kana, restart, note)

    screen.append(topBar(false), body, foot)
    showScreen(ctx.root, screen, ctx.signal)
  }

  showCurrent()
}
