/**
 * 가나 학습 화면(`#/kana`). `03_UI_UX_SPEC.md`의 `가나 학습`.
 *
 * ``` text
 * 글자 표    탭(히라가나/가타카나) · 범위 칩 7개 · 범위 설명 · 표 또는 단어 목록 · 퀴즈 카드 · 저장 안내
 * 퀴즈       진행 {현재} / {전체} · 보고 읽기 | 보고 고르기 · [글자 표로 돌아가기]. 한 라운드는 quiz.ts의 createKanaRound
 * 결과       바로 맞힌 수 · 한 번 더 풀어 본 글자 · [한 번 더 풀기] [글자 표로 돌아가기]
 * ```
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 상단바 `로그인`에는 main.ts가 주입한
 *     `openLogin`을 넘기기만 한다.
 * -   **하위 경로는 처음 보여줄 탭만 고른다.** `'hiragana'`, `'katakana'`와 비교만 하고 화면에 내지 않는다.
 *     모르는 값은 히라가나다. 탭·범위·라운드 상태는 이 mount의 메모리에만 있고 hash나 history에 쓰지 않는다
 *     (하위 hash가 바뀌면 라우터가 다시 mount한다).
 * -   진도는 `progress.ts`로만 남긴다(응답마다, 다시 묻는 문항 포함). 가나의 어떤 동작도 학습 신호가 아니다.
 * -   화면(표·퀴즈·결과) 사이는 `showScreen`으로 바꾼다. 퀴즈 안에서 문항이 바뀌는 것은 화면 안의 변화다.
 */

import type { PublicScreenContext } from '../routes'
import { showToast } from '../ui/notice'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'
import type { KanaRange, KanaScript } from './data'
import { KANA_ITEMS, KANA_RANGES, KANA_SCRIPTS } from './data'
import { recordKanaAnswer, resetKanaProgress } from './progress'
import type { KanaRound } from './quiz'
import { createKanaChoices, createKanaRound } from './quiz'
import type { QuizMode } from './views'
import {
  button,
  KANA_MESSAGES,
  QUIZ_MODES,
  RANGE_LABELS,
  renderAnswer,
  renderFeedback,
  renderQuestionHead,
  renderQuizCard,
  renderRangePanel,
  renderResultBody,
  renderSaveNote,
  renderToggleGroup,
  SCRIPT_LABELS,
} from './views'
import './kana.css'

/** 하위 경로 허용 목록과 비교만 한다. */
function scriptFromSubpath(subpath: string): KanaScript {
  return KANA_SCRIPTS.find((script) => script === subpath) ?? 'hiragana'
}

export function mount(ctx: PublicScreenContext): void {
  let script = scriptFromSubpath(ctx.subpath)
  let range: KanaRange = 'seion'

  function newScreen(className: string, title: string): HTMLElement {
    const screen = document.createElement('main')
    screen.className = `screen kana ${className}`
    const heading = document.createElement('h1')
    heading.className = 'kana-title'
    heading.textContent = title
    screen.append(
      renderTopBar({ onHome: () => ctx.navigate('#/'), onLogin: ctx.openLogin, actions: [] }),
      heading,
    )
    return screen
  }

  // ------------------------------------------------------------------------------------------
  // 글자 표
  // ------------------------------------------------------------------------------------------

  function showTable(): void {
    const screen = newScreen('kana-home', KANA_MESSAGES.title)
    const tabs = renderToggleGroup('kana-tabs', KANA_SCRIPTS, SCRIPT_LABELS, (value) => {
      script = value
      refresh()
    })
    const chips = renderToggleGroup('kana-chips', KANA_RANGES, RANGE_LABELS, (value) => {
      range = value
      refresh()
    })
    const content = document.createElement('div')
    content.className = 'kana-content'

    function refresh(): void {
      tabs.select(script)
      chips.select(range)
      const quizCard = renderQuizCard(script, range, startRound)
      content.replaceChildren(
        renderRangePanel(script, range, () => {
          script = 'katakana'
          refresh()
        }),
        ...(quizCard === null ? [] : [quizCard]),
      )
    }

    refresh()
    screen.append(
      tabs.element,
      chips.element,
      content,
      renderSaveNote(() => {
        resetKanaProgress()
        showToast(KANA_MESSAGES.resetDone)
      }),
    )
    showScreen(ctx.root, screen, ctx.signal)
  }

  // ------------------------------------------------------------------------------------------
  // 퀴즈
  // ------------------------------------------------------------------------------------------

  function startRound(mode: QuizMode): void {
    const pool = KANA_ITEMS[script][range]
    const round = createKanaRound(pool, Math.random)
    const name = QUIZ_MODES.find((entry) => entry.mode === mode)?.name ?? ''
    const screen = newScreen('kana-quiz', name)
    const progress = document.createElement('p')
    progress.className = 'kana-progress'
    const area = document.createElement('div')
    area.className = 'kana-question-area'
    // 라운드를 버리고 표로 돌아간다. 응답마다 저장한 진도는 그대로다.
    screen.append(progress, area, button('secondary kana-back', KANA_MESSAGES.backToTable, showTable))
    showScreen(ctx.root, screen, ctx.signal)

    function answer(key: string, correct: boolean): { willRetry: boolean } {
      recordKanaAnswer(key, correct, Date.now())
      return round.answer(correct)
    }

    /** 다음 문항이나 결과. 첫 문항은 showScreen이 제목에 둔 포커스를 그대로 두고, 그 뒤는 문항으로 옮긴다. */
    function next(): void {
      if (round.current() === undefined) {
        showResult(round, mode)
        return
      }
      // 다시 묻는 문항이 끝에 붙으면 전체 수가 늘어난다.
      progress.textContent = KANA_MESSAGES.quizProgress(round.position() + 1, round.length())
      const question = mode === 'read' ? renderRead() : renderChoose()
      if (round.position() > 0) question.focus({ preventScroll: true })
    }

    function renderRead(): HTMLElement {
      const question = round.current()!
      const head = renderQuestionHead(question.item, question.retry)
      const instruction = document.createElement('p')
      instruction.className = 'kana-instruction'
      instruction.textContent = KANA_MESSAGES.readInstruction
      const answerSlot = document.createElement('div')
      answerSlot.className = 'kana-answer-slot'
      const actions = document.createElement('div')
      actions.className = 'kana-actions'

      function respond(correct: boolean): void {
        const { willRetry } = answer(question.item.key, correct)
        if (willRetry) showToast(KANA_MESSAGES.willRetry)
        next()
      }

      actions.append(
        button('primary kana-show-answer', KANA_MESSAGES.showAnswer, () => {
          // 정답 노드는 누른 뒤에 만든다.
          const shown = renderAnswer(question.item)
          answerSlot.replaceChildren(shown)
          actions.replaceChildren(
            button('secondary kana-wrong', KANA_MESSAGES.wrong, () => respond(false)),
            button('primary kana-right', KANA_MESSAGES.right, () => respond(true)),
          )
          shown.focus({ preventScroll: true })
        }),
      )
      area.replaceChildren(...head, instruction, answerSlot, actions)
      return head[head.length - 1]!
    }

    function renderChoose(): HTMLElement {
      const question = round.current()!
      const { item } = question
      const head = renderQuestionHead(item, question.retry)
      const options = document.createElement('div')
      options.className = 'kana-options'
      const feedbackSlot = document.createElement('div')
      feedbackSlot.className = 'kana-feedback-slot'
      const actions = document.createElement('div')
      actions.className = 'kana-actions'

      const choices = createKanaChoices(item, pool, Math.random).map((romaji) => ({
        romaji,
        node: button('kana-option', romaji, () => choose(romaji)),
      }))
      options.append(...choices.map((choice) => choice.node))

      function choose(picked: string): void {
        const correct = picked === item.romaji
        for (const { romaji, node } of choices) {
          node.disabled = true
          if (romaji === item.romaji) node.classList.add('is-correct')
          else if (romaji === picked) node.classList.add('is-wrong')
        }
        const { willRetry } = answer(item.key, correct)
        // 다시 나온 문항을 또 틀리면 더 나오지 않으므로 정답만 알린다.
        const text = correct
          ? KANA_MESSAGES.chooseRight
          : willRetry
            ? `${KANA_MESSAGES.chooseWrong(item.romaji)} ${KANA_MESSAGES.willRetry}`
            : KANA_MESSAGES.chooseWrong(item.romaji)
        feedbackSlot.replaceChildren(renderFeedback(text))
        const last = round.current() === undefined
        actions.replaceChildren(
          button('primary kana-next', last ? KANA_MESSAGES.showResult : KANA_MESSAGES.nextQuestion, next),
        )
      }

      area.replaceChildren(...head, options, feedbackSlot, actions)
      return head[head.length - 1]!
    }

    next()
  }

  // ------------------------------------------------------------------------------------------
  // 결과
  // ------------------------------------------------------------------------------------------

  function showResult(round: KanaRound, mode: QuizMode): void {
    const { total, firstTryCorrect, retried } = round.result()
    const screen = newScreen('kana-result', KANA_MESSAGES.resultTitle)
    const actions = document.createElement('div')
    actions.className = 'kana-result-actions'
    actions.append(
      button('primary kana-again', KANA_MESSAGES.again, () => startRound(mode)),
      button('secondary kana-back', KANA_MESSAGES.backToTable, showTable),
    )
    screen.append(...renderResultBody(total, firstTryCorrect, retried), actions)
    showScreen(ctx.root, screen, ctx.signal)
  }

  showTable()
}
