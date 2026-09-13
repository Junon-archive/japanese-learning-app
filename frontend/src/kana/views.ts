/**
 * 가나 학습 화면의 DOM 조각과 문구(`03_UI_UX_SPEC.md`의 `가나 학습`, `화면 문구 표`의 `가나 학습`).
 *
 * -   상태를 들지 않는다. 무엇을 그릴지는 인자로 받고 동작은 콜백으로 넘긴다. 흐름은 `screen.ts`에 있다.
 * -   DOM은 `textContent`와 리터럴 태그의 `createElement`로만 만든다. URL 값은 여기로 오지 않는다.
 * -   소리(발음 재생)와 획순은 없다.
 */

import type { KanaItem, KanaRange, KanaScript } from './data'
import { KANA_CHAR_RANGES, KANA_ITEMS, KANA_TABLES } from './data'

export const KANA_MESSAGES = {
  title: '글자 배우기',
  gairaigoOnKatakana: '외래어는 가타카나로 적어요.',
  gairaigoWhere: '가타카나에서 볼 수 있어요.',
  showKatakana: '가타카나로 보기',
  quizTitle: '퀴즈로 연습해요',
  quizScope: (scope: string) => `지금 고른 ${scope}에서 문제를 내요.`,
  saveNote: '푼 기록은 이 브라우저에만 남아요.',
  reset: '진도 초기화',
  resetQuestion: '진도를 초기화할까요?',
  resetDetail: '이 브라우저에 남은 퀴즈 기록이 지워져요.',
  resetConfirm: '초기화하기',
  resetCancel: '취소',
  resetDone: '진도를 초기화했어요.',
  readInstruction: '소리 내어 읽어 보세요.',
  showAnswer: '정답 보기',
  wrong: '틀렸어요',
  right: '맞았어요',
  retryQuestion: '한 번 더 볼게요.',
  willRetry: '이번 라운드에서 한 번 더 나와요.',
  chooseRight: '맞았어요.',
  chooseWrong: (romaji: string) => `정답은 ${romaji}예요.`,
  nextQuestion: '다음 문제',
  showResult: '결과 보기',
  resultTitle: '이번 라운드를 마쳤어요.',
  resultAll: (total: number) => `${total}문제를 모두 바로 맞혔어요.`,
  resultSome: (total: number, correct: number) => `${total}문제 중 ${correct}문제를 바로 맞혔어요.`,
  resultRetried: '한 번 더 풀어 본 글자예요.',
  quizProgress: (current: number, total: number) => `${current} / ${total}`,
  again: '한 번 더 풀기',
  backToTable: '글자 표로 돌아가기',
} as const

export const SCRIPT_LABELS: Readonly<Record<KanaScript, string>> = {
  hiragana: '히라가나',
  katakana: '가타카나',
}

export const RANGE_LABELS: Readonly<Record<KanaRange, string>> = {
  seion: '청음',
  dakuon: '탁음',
  handakuon: '반탁음',
  yoon: '요음',
  sokuon: '촉음',
  choon: '장음',
  gairaigo: '외래어',
}

const RANGE_DESCRIPTIONS: Readonly<Record<KanaRange, Readonly<Record<KanaScript, string>>>> = {
  seion: both('기본 글자예요.'),
  dakuon: both('점 두 개(゛)가 붙으면 흐린 소리가 나요.'),
  handakuon: both('작은 동그라미(゜)가 붙으면 ㅍ 소리가 나요.'),
  yoon: { hiragana: '작은 ゃ·ゅ·ょ가 붙으면 한 소리로 읽어요.', katakana: '작은 ャ·ュ·ョ가 붙으면 한 소리로 읽어요.' },
  sokuon: { hiragana: '작은 っ 자리에서 한 박자 쉬어요.', katakana: '작은 ッ 자리에서 한 박자 쉬어요.' },
  choon: { hiragana: 'あ·い·う 같은 모음 글자만큼 길게 읽어요.', katakana: 'ー 표시만큼 길게 읽어요.' },
  gairaigo: both('다른 나라 말을 가타카나로 적어요. ティ, ファ처럼 작은 글자를 붙인 표기도 있어요.'),
}

function both(text: string): Record<KanaScript, string> {
  return { hiragana: text, katakana: text }
}

export type QuizMode = 'read' | 'choose'

export const QUIZ_MODES: readonly { mode: QuizMode; name: string; description: string }[] = [
  { mode: 'read', name: '보고 읽기', description: '읽어 본 뒤 정답을 확인해요.' },
  { mode: 'choose', name: '보고 고르기', description: '알맞은 읽기를 4개 중에서 골라요.' },
]

// ---------------------------------------------------------------------------------------------
// 작은 요소. createElement의 태그는 리터럴이어야 한다(격리 검사 (d)).
// ---------------------------------------------------------------------------------------------

function div(className: string): HTMLElement {
  const node = document.createElement('div')
  node.className = className
  return node
}

function span(className: string, text: string): HTMLElement {
  const node = document.createElement('span')
  node.className = className
  node.textContent = text
  return node
}

function paragraph(className: string, text: string): HTMLElement {
  const node = document.createElement('p')
  node.className = className
  node.textContent = text
  return node
}

export function button(className: string, text: string, onClick: () => void): HTMLButtonElement {
  const node = document.createElement('button')
  node.type = 'button'
  node.className = className
  node.textContent = text
  node.addEventListener('click', onClick)
  return node
}

function japanese(className: string, text: string): HTMLElement {
  const node = span(className, text)
  node.lang = 'ja'
  return node
}

// ---------------------------------------------------------------------------------------------
// 글자 표 화면
// ---------------------------------------------------------------------------------------------

/** 누른 상태를 `aria-pressed`로 두는 버튼 줄(탭, 범위 칩). */
export function renderToggleGroup<T extends string>(
  className: string,
  options: readonly T[],
  labels: Readonly<Record<T, string>>,
  onSelect: (value: T) => void,
): { element: HTMLElement; select: (value: T) => void } {
  const group = div(className)
  const buttons = options.map((value) => {
    const node = button(`${className}-button`, labels[value], () => onSelect(value))
    group.append(node)
    return { value, node }
  })
  return {
    element: group,
    select(selected) {
      for (const { value, node } of buttons) node.setAttribute('aria-pressed', String(value === selected))
    },
  }
}

export function scopeLabel(script: KanaScript, range: KanaRange): string {
  return `${SCRIPT_LABELS[script]} · ${RANGE_LABELS[range]}`
}

function isCharRange(range: KanaRange): range is (typeof KANA_CHAR_RANGES)[number] {
  return (KANA_CHAR_RANGES as readonly KanaRange[]).includes(range)
}

function renderTable(script: KanaScript, range: (typeof KANA_CHAR_RANGES)[number]): HTMLElement {
  const table = div(`kana-table ${range === 'yoon' ? 'cols-3' : 'cols-5'}`)
  for (const row of KANA_TABLES[script][range]) {
    const line = div('kana-row')
    for (const cell of row) {
      if (cell === null) {
        const empty = div('kana-cell is-empty')
        empty.setAttribute('aria-hidden', 'true')
        line.append(empty)
        continue
      }
      const node = div('kana-cell')
      node.append(
        japanese('kana-cell-text', cell.text),
        span('kana-cell-romaji', cell.romaji),
        span('kana-cell-hangul', cell.hangul),
      )
      line.append(node)
    }
    table.append(line)
  }
  return table
}

function renderWords(words: readonly KanaItem[]): HTMLElement {
  const list = document.createElement('ul')
  list.className = 'kana-words'
  for (const word of words) {
    const row = document.createElement('li')
    row.className = 'kana-word'
    row.append(
      japanese('kana-word-text', word.text),
      span('kana-word-romaji', word.romaji),
      span('kana-word-hangul', word.hangul),
      span('kana-word-meaning', word.meaning ?? ''),
    )
    list.append(row)
  }
  return list
}

/** 범위 설명과 표(또는 단어 목록). 히라가나 탭의 외래어는 안내와 가타카나 이동 버튼이다. */
export function renderRangePanel(script: KanaScript, range: KanaRange, onShowKatakana: () => void): HTMLElement {
  const panel = div('kana-panel')
  if (script === 'hiragana' && range === 'gairaigo') {
    const note = div('kana-gairaigo-note')
    note.append(
      paragraph('kana-note-text', KANA_MESSAGES.gairaigoOnKatakana),
      paragraph('kana-note-text', KANA_MESSAGES.gairaigoWhere),
      button('secondary kana-show-katakana', KANA_MESSAGES.showKatakana, onShowKatakana),
    )
    panel.append(note)
    return panel
  }
  panel.append(
    paragraph('kana-range-desc', RANGE_DESCRIPTIONS[range][script]),
    isCharRange(range) ? renderTable(script, range) : renderWords(KANA_ITEMS[script][range]),
  )
  return panel
}

/** 퀴즈 카드. 고른 범위에 문항이 없으면(히라가나 외래어) 그리지 않는다. */
export function renderQuizCard(
  script: KanaScript,
  range: KanaRange,
  onStart: (mode: QuizMode) => void,
): HTMLElement | null {
  if (KANA_ITEMS[script][range].length === 0) return null
  const card = document.createElement('section')
  card.className = 'kana-quiz-card'
  const title = document.createElement('h2')
  title.className = 'kana-quiz-title'
  title.textContent = KANA_MESSAGES.quizTitle
  const modes = div('kana-modes')
  for (const { mode, name, description } of QUIZ_MODES) {
    const start = button('kana-mode', '', () => onStart(mode))
    start.append(span('kana-mode-name', name), span('kana-mode-desc', description))
    modes.append(start)
  }
  card.append(title, paragraph('kana-quiz-scope', KANA_MESSAGES.quizScope(scopeLabel(script, range))), modes)
  return card
}

/** 저장 안내와 `진도 초기화`. 확인은 시트가 아니라 그 자리에서 한 번 더 묻는다. */
export function renderSaveNote(onReset: () => void): HTMLElement {
  const box = div('kana-save')
  const openButton = button('kana-reset-open', KANA_MESSAGES.reset, () => {
    const question = paragraph('kana-confirm-question', KANA_MESSAGES.resetQuestion)
    question.setAttribute('tabindex', '-1')
    const actions = div('kana-confirm-actions')
    actions.append(
      button('kana-reset-confirm', KANA_MESSAGES.resetConfirm, () => {
        onReset()
        close()
      }),
      button('kana-reset-cancel', KANA_MESSAGES.resetCancel, close),
    )
    box.replaceChildren(question, paragraph('kana-confirm-detail', KANA_MESSAGES.resetDetail), actions)
    question.focus({ preventScroll: true })
  })
  const note = paragraph('kana-save-text', KANA_MESSAGES.saveNote)

  function close(): void {
    box.replaceChildren(note, openButton)
    openButton.focus({ preventScroll: true })
  }

  box.append(note, openButton)
  return box
}

// ---------------------------------------------------------------------------------------------
// 퀴즈와 결과
// ---------------------------------------------------------------------------------------------

/** 문항 머리: 다시 나오는 문항 표시와 글자·단어. */
export function renderQuestionHead(item: KanaItem, retry: boolean): HTMLElement[] {
  const text = document.createElement('p')
  text.className = item.meaning === undefined ? 'kana-question-text' : 'kana-question-text is-word'
  text.lang = 'ja'
  text.textContent = item.text
  text.setAttribute('tabindex', '-1')
  return retry ? [paragraph('kana-retry', KANA_MESSAGES.retryQuestion), text] : [text]
}

/** 보고 읽기의 정답: `{로마자} {한글} ({뜻})`. 뜻은 단어일 때만. 누른 뒤에 만든다. */
export function renderAnswer(item: KanaItem): HTMLElement {
  const answer = paragraph('kana-answer inline-expand', '')
  const rest = item.meaning === undefined ? ` ${item.hangul}` : ` ${item.hangul} (${item.meaning})`
  answer.append(span('kana-answer-romaji', item.romaji), span('kana-answer-rest', rest))
  answer.setAttribute('tabindex', '-1')
  return answer
}

export function renderFeedback(text: string): HTMLElement {
  const feedback = paragraph('kana-feedback inline-expand', text)
  feedback.setAttribute('role', 'status')
  return feedback
}

export function renderResultBody(
  total: number,
  firstTryCorrect: number,
  retried: readonly KanaItem[],
): HTMLElement[] {
  const summary = paragraph(
    'kana-result-summary',
    firstTryCorrect === total ? KANA_MESSAGES.resultAll(total) : KANA_MESSAGES.resultSome(total, firstTryCorrect),
  )
  if (retried.length === 0) return [summary]

  const section = div('kana-retried')
  const list = document.createElement('ul')
  list.className = 'kana-retried-list'
  for (const item of retried) {
    const row = document.createElement('li')
    row.className = 'kana-retried-item'
    row.append(japanese('kana-retried-text', item.text), span('kana-retried-romaji', item.romaji))
    list.append(row)
  }
  section.append(paragraph('kana-retried-title', KANA_MESSAGES.resultRetried), list)
  return [summary, section]
}
