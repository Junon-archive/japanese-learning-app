/**
 * 가나 학습 화면(`src/kana/screen.ts`). `03_UI_UX_SPEC.md`의 `가나 학습`과 `화면 문구 표`의 `가나 학습`,
 * `12_TEST_PLAN.md`(MVP-02)의 `가나 학습`, 합격 기준 29·32·33·34. Wave 3 메인 결정 G6·W3-2도 따른다.
 *
 * -   화면 문구는 **03 문구 표의 리터럴**로 단정한다(구현의 `KANA_MESSAGES`를 참조하지 않는다).
 *     W3-2로 표에 아직 없는 문구(범위 표기 `히라가나 · 청음`, 진행 `{현재} / {전체}`, 가타카나 탭의
 *     작은 글자)는 결정문의 표기를 쓴다.
 * -   표의 행·칸 수와 문항 수는 데이터(`KANA_TABLES`, `KANA_ITEMS`)와 `KANA_ROUND_MAX_QUESTIONS`에서
 *     얻는다. 숫자를 복사하지 않는다.
 * -   문항과 선택지는 `Math.random`을 상수로 고정하고, 같은 상수를 `quiz.ts`에 넘긴 결과와 비교한다.
 *     상수이므로 화면이 난수를 부르는 순서에 기대지 않는다.
 * -   `progress.ts`는 import 시점에 `localSlot`을 만들고 `local-store.ts`는 메모리 값을 모듈에 둔다.
 *     그래서 테스트마다 모듈을 새로 불러온다(`kana-progress.test.ts`와 같은 이유).
 *
 * `fetch`는 던지는 스텁이고 모든 테스트 끝에 호출 0회를, `history.pushState` 호출 0회를 단정한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { KanaItem, KanaRange, KanaScript } from '../../src/kana/data'
import { KANA_CHAR_RANGES, KANA_ITEMS, KANA_RANGES, KANA_SCRIPTS, KANA_TABLES } from '../../src/kana/data'
import { createKanaChoices, createKanaRound, KANA_ROUND_MAX_QUESTIONS } from '../../src/kana/quiz'
import type { FakeBrowser, FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, descendants, fakeBrowser, fakeDocument, flatText } from './fake-dom'

// ---------------------------------------------------------------------------------------------
// 03 문구 표 리터럴
// ---------------------------------------------------------------------------------------------

const SCRIPT_LABEL: Record<KanaScript, string> = { hiragana: '히라가나', katakana: '가타카나' }

const RANGE_LABEL: Record<KanaRange, string> = {
  seion: '청음',
  dakuon: '탁음',
  handakuon: '반탁음',
  yoon: '요음',
  sokuon: '촉음',
  choon: '장음',
  gairaigo: '외래어',
}

/** 03 `범위 설명`. 가타카나 탭의 요음·촉음 작은 글자는 W3-2 (6)의 표기다(03 표에는 아직 없다). */
const RANGE_DESCRIPTION: Record<KanaScript, Partial<Record<KanaRange, string>>> = {
  hiragana: {
    seion: '기본 글자예요.',
    dakuon: '점 두 개(゛)가 붙으면 흐린 소리가 나요.',
    handakuon: '작은 동그라미(゜)가 붙으면 ㅍ 소리가 나요.',
    yoon: '작은 ゃ·ゅ·ょ가 붙으면 한 소리로 읽어요.',
    sokuon: '작은 っ 자리에서 한 박자 쉬어요.',
    choon: 'あ·い·う 같은 모음 글자만큼 길게 읽어요.',
  },
  katakana: {
    seion: '기본 글자예요.',
    dakuon: '점 두 개(゛)가 붙으면 흐린 소리가 나요.',
    handakuon: '작은 동그라미(゜)가 붙으면 ㅍ 소리가 나요.',
    yoon: '작은 ャ·ュ·ョ가 붙으면 한 소리로 읽어요.',
    sokuon: '작은 ッ 자리에서 한 박자 쉬어요.',
    choon: 'ー 표시만큼 길게 읽어요.',
    gairaigo: '다른 나라 말을 가타카나로 적어요. ティ, ファ처럼 작은 글자를 붙인 표기도 있어요.',
  },
}

const TEXT = {
  title: '글자 배우기',
  gairaigoNote: ['외래어는 가타카나로 적어요.', '가타카나에서 볼 수 있어요.'],
  showKatakana: '가타카나로 보기',
  quizTitle: '퀴즈로 연습해요',
  quizScope: (script: KanaScript, range: KanaRange) =>
    `지금 고른 ${SCRIPT_LABEL[script]} · ${RANGE_LABEL[range]}에서 문제를 내요.`,
  modes: [
    { name: '보고 읽기', description: '읽어 본 뒤 정답을 확인해요.' },
    { name: '보고 고르기', description: '알맞은 읽기를 4개 중에서 골라요.' },
  ],
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
  resultAll: (n: number) => `${n}문제를 모두 바로 맞혔어요.`,
  resultSome: (n: number, k: number) => `${n}문제 중 ${k}문제를 바로 맞혔어요.`,
  resultRetried: '한 번 더 풀어 본 글자예요.',
  again: '한 번 더 풀기',
  backToTable: '글자 표로 돌아가기',
  progress: (current: number, total: number) => `${current} / ${total}`,
} as const

const READ = '보고 읽기'
const CHOOSE = '보고 고르기'

// ---------------------------------------------------------------------------------------------
// 하네스
// ---------------------------------------------------------------------------------------------

const INITIAL_HASH = '#/kana'
const KANA_KEY = 'nc.kana.v1'
/** 난수를 고정하는 값. 둘 이상으로 돌려 "난수가 실제로 문항을 고른다"도 본다. */
const RANDOM_VALUES = [0, 0.75] as const

const fetchMock = vi.fn<typeof fetch>(() => {
  throw new Error('kana learning must not make requests')
})

let doc: FakeDocument
let root: FakeElement
let browser: FakeBrowser
let pushState: ReturnType<typeof vi.fn>
let navigations: string[]
let logins: number

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  }
}

function throwingStorage() {
  const fail = (): never => {
    throw new DOMException('denied', 'SecurityError')
  }
  return { getItem: vi.fn(fail), setItem: vi.fn(fail), removeItem: vi.fn(fail) }
}

async function mountKana(subpath = '', hash = INITIAL_HASH): Promise<void> {
  browser = fakeBrowser(hash)
  pushState = vi.fn()
  vi.stubGlobal('location', browser.location)
  vi.stubGlobal('history', { ...browser.history, pushState })
  vi.stubGlobal('window', browser.window)
  const { mount } = await import('../../src/kana/screen')
  mount({
    root: root as unknown as HTMLElement,
    signal: new AbortController().signal,
    subpath,
    navigate: (target) => navigations.push(target),
    openLogin: () => {
      logins += 1
    },
  })
}

beforeEach(() => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.setSystemTime(1_000_000)
  fetchMock.mockClear()
  doc = fakeDocument()
  root = createFakeElement('div')
  navigations = []
  logins = 0
  vi.stubGlobal('document', doc)
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', memoryStorage())
})

afterEach(() => {
  expect(fetchMock).not.toHaveBeenCalled()
  expect(pushState).not.toHaveBeenCalled()
  vi.restoreAllMocks()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.resetModules()
})

// ---------------------------------------------------------------------------------------------
// 화면 읽기·조작
// ---------------------------------------------------------------------------------------------

/** 자식 textContent를 구분자 없이 이어 붙인다(한 줄에 span 여럿으로 나뉜 문구). */
function joined(node: FakeElement): string {
  return descendants(node)
    .map((each) => each.textContent)
    .join('')
}

function screenClass(): string {
  return root.children[0]?.className ?? ''
}

function title(): string {
  return root.querySelector('h1')?.textContent ?? ''
}

function one(className: string, scope: FakeElement = root): FakeElement {
  const found = byClass(scope, className)
  expect(found, `expected exactly one .${className}`).toHaveLength(1)
  return found[0]!
}

function texts(className: string, scope: FakeElement = root): string[] {
  return byClass(scope, className).map((node) => node.textContent)
}

function press(label: string, scope: FakeElement = root): void {
  const found = buttons(scope).filter((node) => joined(node) === label)
  expect(found, `expected exactly one button "${label}"`).toHaveLength(1)
  found[0]!.click()
}

function hasButton(label: string): boolean {
  return buttons(root).some((node) => joined(node) === label)
}

function groupLabels(group: string): string[] {
  return buttons(one(group)).map((node) => node.textContent)
}

function pressed(group: string): string[] {
  return buttons(one(group))
    .filter((node) => node.getAttribute('aria-pressed') === 'true')
    .map((node) => node.textContent)
}

function select(script: KanaScript, range: KanaRange): void {
  press(SCRIPT_LABEL[script], one('kana-tabs'))
  press(RANGE_LABEL[range], one('kana-chips'))
}

function startQuiz(name: string): void {
  const found = byClass(root, 'kana-mode').filter((node) => texts('kana-mode-name', node)[0] === name)
  expect(found, `expected one quiz mode "${name}"`).toHaveLength(1)
  found[0]!.click()
}

function topBarRight(): string[] {
  return buttons(one('topbar-actions')).map((node) => node.textContent)
}

/** 이 동작이 띄운 토스트 문구. 토스트는 body에 붙는다. */
function toastsDuring(action: () => void): string[] {
  doc.body.replaceChildren()
  action()
  return doc.body.children.filter((node) => node.classList.contains('toast')).map((node) => node.textContent)
}

function storedProgress(storage: ReturnType<typeof memoryStorage>): {
  items: Record<string, { correct: number; wrong: number }>
  lastStudiedAt: number
} | null {
  const raw = storage.data.get(KANA_KEY)
  return raw === undefined ? null : JSON.parse(raw)
}

function answerCount(storage: ReturnType<typeof memoryStorage>): number {
  const progress = storedProgress(storage)
  if (progress === null) return 0
  return Object.values(progress.items).reduce((sum, entry) => sum + entry.correct + entry.wrong, 0)
}

type Seen = { text: string; retry: boolean; progress: string }

function currentQuestion(): Seen {
  const retry = texts('kana-retry')
  expect(retry.length <= 1).toBe(true)
  if (retry.length === 1) expect(retry[0]).toBe(TEXT.retryQuestion)
  return {
    text: one('kana-question-text').textContent,
    retry: retry.length === 1,
    progress: one('kana-progress').textContent,
  }
}

function itemOf(pool: readonly KanaItem[], text: string): KanaItem {
  const item = pool.find((candidate) => candidate.text === text)
  expect(item, `question ${text} is not in the pool`).toBeDefined()
  return item!
}

/** `quiz.ts`에 같은 난수를 넘기고 같은 응답을 주었을 때의 문항 순서. */
function plannedQuestions(
  pool: readonly KanaItem[],
  random: number,
  decide: (index: number, retry: boolean) => boolean,
): { text: string; retry: boolean }[] {
  const round = createKanaRound(pool, () => random)
  const planned: { text: string; retry: boolean }[] = []
  for (let question = round.current(); question !== undefined; question = round.current()) {
    planned.push({ text: question.item.text, retry: question.retry })
    round.answer(decide(planned.length - 1, question.retry))
  }
  return planned
}

function inQuiz(): boolean {
  return screenClass().includes('kana-quiz')
}

/** 보고 읽기 한 문항: 정답 보기 → 맞았어요/틀렸어요. 띄운 토스트를 돌려준다. */
function answerRead(correct: boolean): string[] {
  return toastsDuring(() => {
    press(TEXT.showAnswer)
    press(correct ? TEXT.right : TEXT.wrong)
  })
}

/** 보고 고르기 한 문항: 선택지를 고른다. 다음 버튼은 누르지 않는다. */
function answerChoose(item: KanaItem, correct: boolean): { feedback: string; toasts: string[] } {
  const options = byClass(root, 'kana-option')
  const target = correct
    ? options.find((node) => node.textContent === item.romaji)
    : options.find((node) => node.textContent !== item.romaji)
  expect(target).toBeDefined()
  const toasts = toastsDuring(() => target!.click())
  return { feedback: one('kana-feedback').textContent, toasts }
}

// ---------------------------------------------------------------------------------------------
// 글자 표
// ---------------------------------------------------------------------------------------------

describe('kana table screen', () => {
  it('shows the title, two tabs, seven range chips, the save note and only 로그인 on the right', async () => {
    await mountKana()

    expect(screenClass()).toContain('kana')
    expect(title()).toBe(TEXT.title)
    expect(groupLabels('kana-tabs')).toEqual(KANA_SCRIPTS.map((script) => SCRIPT_LABEL[script]))
    expect(groupLabels('kana-chips')).toEqual(KANA_RANGES.map((range) => RANGE_LABEL[range]))
    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.hiragana])
    expect(pressed('kana-chips')).toEqual([RANGE_LABEL.seion])
    expect(one('kana-save-text').textContent).toBe(TEXT.saveNote)
    expect(hasButton(TEXT.reset)).toBe(true)
    expect(topBarRight()).toEqual(['로그인'])
  })

  it('opens the tab named by the subpath and treats anything else as 히라가나', async () => {
    await mountKana('katakana', '#/kana/katakana')
    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.katakana])
    expect(texts('kana-cell-text')[0]).toBe(KANA_TABLES.katakana.seion[0]![0]!.text)

    for (const subpath of ['', 'hiragana', 'Katakana', 'katakana/extra']) {
      vi.resetModules()
      root = createFakeElement('div')
      await mountKana(subpath, `#/kana/${subpath}`)
      expect(pressed('kana-tabs'), `subpath ${subpath}`).toEqual([SCRIPT_LABEL.hiragana])
    }
  })

  it('does not print the subpath value anywhere', async () => {
    const subpath = '<img src=x onerror=alert(1)>'
    await mountKana(subpath, `#/kana/${subpath}`)

    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.hiragana])
    for (const scope of [root, doc.body]) {
      const all = descendants(scope)
      expect(all.filter((node) => node.tagName === 'IMG')).toEqual([])
      const printed = [
        flatText(scope),
        ...all.flatMap((node) => Object.values(node.attributes)),
        ...all.map((node) => node.className),
      ].join('\n')
      expect(printed).not.toContain('<')
      expect(printed).not.toContain('img')
      expect(printed).not.toContain('onerror')
    }
  })

  for (const script of KANA_SCRIPTS) {
    for (const range of KANA_CHAR_RANGES) {
      it(`draws the ${script} ${range} table with the data's rows, cells and empty cells`, async () => {
        await mountKana()
        select(script, range)

        expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL[script]])
        expect(pressed('kana-chips')).toEqual([RANGE_LABEL[range]])
        expect(one('kana-range-desc').textContent).toBe(RANGE_DESCRIPTION[script][range])
        expect(byClass(root, 'kana-word')).toEqual([])

        const table = KANA_TABLES[script][range]
        const rows = byClass(one('kana-table'), 'kana-row')
        expect(rows).toHaveLength(table.length)
        rows.forEach((row, rowIndex) => {
          const data = table[rowIndex]!
          const cells = byClass(row, 'kana-cell')
          expect(cells).toHaveLength(data.length)
          expect(byClass(row, 'is-empty')).toHaveLength(data.filter((cell) => cell === null).length)
          cells.forEach((cell, cellIndex) => {
            const expected = data[cellIndex]
            if (expected === null || expected === undefined) {
              expect(cell.classList.contains('is-empty')).toBe(true)
              expect(joined(cell)).toBe('')
              return
            }
            expect(texts('kana-cell-text', cell)).toEqual([expected.text])
            expect(texts('kana-cell-romaji', cell)).toEqual([expected.romaji])
            expect(texts('kana-cell-hangul', cell)).toEqual([expected.hangul])
          })
        })

        expect(one('kana-quiz-title').textContent).toBe(TEXT.quizTitle)
        expect(one('kana-quiz-scope').textContent).toBe(TEXT.quizScope(script, range))
      })
    }
  }

  for (const script of KANA_SCRIPTS) {
    for (const range of KANA_RANGES.filter((each) => !(KANA_CHAR_RANGES as readonly string[]).includes(each))) {
      if (script === 'hiragana' && range === 'gairaigo') continue
      it(`lists the ${script} ${range} words with romaji, hangul and meaning`, async () => {
        await mountKana()
        select(script, range)

        expect(one('kana-range-desc').textContent).toBe(RANGE_DESCRIPTION[script][range])
        expect(byClass(root, 'kana-table')).toEqual([])
        const words = KANA_ITEMS[script][range]
        const rows = byClass(root, 'kana-word')
        expect(rows).toHaveLength(words.length)
        rows.forEach((row, index) => {
          const word = words[index]!
          expect([
            ...texts('kana-word-text', row),
            ...texts('kana-word-romaji', row),
            ...texts('kana-word-hangul', row),
            ...texts('kana-word-meaning', row),
          ]).toEqual([word.text, word.romaji, word.hangul, word.meaning])
        })
        expect(one('kana-quiz-scope').textContent).toBe(TEXT.quizScope(script, range))
      })
    }
  }

  it('shows the two quiz modes with their descriptions', async () => {
    await mountKana()
    const modes = byClass(root, 'kana-mode').map((node) => ({
      name: texts('kana-mode-name', node)[0],
      description: texts('kana-mode-desc', node)[0],
    }))
    expect(modes).toEqual(TEXT.modes)
  })

  it('uses the katakana small letters in the katakana range descriptions', async () => {
    await mountKana('katakana', '#/kana/katakana')
    press(RANGE_LABEL.yoon, one('kana-chips'))
    expect(one('kana-range-desc').textContent).toBe('작은 ャ·ュ·ョ가 붙으면 한 소리로 읽어요.')
    press(RANGE_LABEL.sokuon, one('kana-chips'))
    expect(one('kana-range-desc').textContent).toBe('작은 ッ 자리에서 한 박자 쉬어요.')
  })
})

describe('외래어 on the hiragana tab', () => {
  it('shows the note and the move button without a table, word list or quiz card', async () => {
    await mountKana()
    select('hiragana', 'gairaigo')

    expect(texts('kana-note-text')).toEqual(TEXT.gairaigoNote)
    expect(hasButton(TEXT.showKatakana)).toBe(true)
    expect(byClass(root, 'kana-table')).toEqual([])
    expect(byClass(root, 'kana-word')).toEqual([])
    expect(byClass(root, 'kana-quiz-card')).toEqual([])
    expect(byClass(root, 'kana-mode')).toEqual([])
    expect(flatText(root)).not.toContain(TEXT.quizTitle)
  })

  it('moves to the katakana tab keeping 외래어', async () => {
    await mountKana()
    select('hiragana', 'gairaigo')

    press(TEXT.showKatakana)

    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.katakana])
    expect(pressed('kana-chips')).toEqual([RANGE_LABEL.gairaigo])
    expect(texts('kana-word-text')).toEqual(KANA_ITEMS.katakana.gairaigo.map((word) => word.text))
    expect(byClass(root, 'kana-note-text')).toEqual([])
    expect(one('kana-quiz-scope').textContent).toBe(TEXT.quizScope('katakana', 'gairaigo'))
    expect(browser.location.hash).toBe(INITIAL_HASH)
  })
})

// ---------------------------------------------------------------------------------------------
// 보고 읽기
// ---------------------------------------------------------------------------------------------

describe('보고 읽기', () => {
  it('shows the instruction, then the answer only after 정답 보기, with the meaning only for words', async () => {
    for (const [script, range] of [
      ['hiragana', 'seion'],
      ['katakana', 'choon'],
    ] as const) {
      vi.resetModules()
      root = createFakeElement('div')
      vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[0])
      await mountKana()
      select(script, range)
      startQuiz(READ)

      const pool = KANA_ITEMS[script][range]
      expect(title()).toBe(READ)
      expect(topBarRight()).toEqual(['로그인'])
      const item = itemOf(pool, currentQuestion().text)
      expect(one('kana-instruction').textContent).toBe(TEXT.readInstruction)
      expect(byClass(root, 'kana-answer')).toEqual([])
      expect(hasButton(TEXT.right)).toBe(false)
      expect(hasButton(TEXT.wrong)).toBe(false)

      press(TEXT.showAnswer)

      const expected =
        item.meaning === undefined
          ? `${item.romaji} ${item.hangul}`
          : `${item.romaji} ${item.hangul} (${item.meaning})`
      expect(joined(one('kana-answer'))).toBe(expected)
      expect(hasButton(TEXT.showAnswer)).toBe(false)
      expect(buttons(one('kana-actions')).map((node) => node.textContent)).toEqual([TEXT.wrong, TEXT.right])
      vi.restoreAllMocks()
    }
  })

  for (const random of RANDOM_VALUES) {
    it(`asks the fixed questions, retries a wrong one once at the end and toasts only the first miss (random ${random})`, async () => {
      vi.spyOn(Math, 'random').mockReturnValue(random)
      const pool = KANA_ITEMS.katakana.choon
      const total = Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS)
      expect(total).toBeGreaterThan(1)
      // 첫 문항만 틀리고 다시 나와도 또 틀린다.
      const decide = (index: number, retry: boolean) => index !== 0 && !retry
      await mountKana()
      select('katakana', 'choon')
      startQuiz(READ)

      const seen: Seen[] = []
      const toasts: string[][] = []
      while (inQuiz()) {
        const question = currentQuestion()
        seen.push(question)
        toasts.push(answerRead(decide(seen.length - 1, question.retry)))
        expect(seen.length).toBeLessThanOrEqual(total + 1)
      }

      expect(seen.map(({ text, retry }) => ({ text, retry }))).toEqual(plannedQuestions(pool, random, decide))
      expect(seen).toHaveLength(total + 1)
      expect(seen.filter((question) => question.retry)).toHaveLength(1)
      expect(seen[total]).toMatchObject({ text: seen[0]!.text, retry: true })
      expect(seen.map((question) => question.progress)).toEqual([
        TEXT.progress(1, total),
        ...seen.slice(1).map((_, index) => TEXT.progress(index + 2, total + 1)),
      ])
      expect(toasts[0]).toEqual([TEXT.willRetry])
      expect(toasts.slice(1)).toEqual(seen.slice(1).map(() => []))

      expect(screenClass()).toContain('kana-result')
      expect(title()).toBe(TEXT.resultTitle)
      expect(one('kana-result-summary').textContent).toBe(TEXT.resultSome(total, total - 1))
      expect(one('kana-retried-title').textContent).toBe(TEXT.resultRetried)
      const retried = itemOf(pool, seen[0]!.text)
      expect(byClass(root, 'kana-retried-item').map(joined)).toEqual([`${retried.text}${retried.romaji}`])
      expect(buttons(one('kana-result-actions')).map((node) => node.textContent)).toEqual([
        TEXT.again,
        TEXT.backToTable,
      ])
      expect(topBarRight()).toEqual(['로그인'])
    })
  }
})

// ---------------------------------------------------------------------------------------------
// 보고 고르기
// ---------------------------------------------------------------------------------------------

describe('보고 고르기', () => {
  for (const random of RANDOM_VALUES) {
    it(`caps the round, fixes questions and choices, and gives the three feedbacks (random ${random})`, async () => {
      vi.spyOn(Math, 'random').mockReturnValue(random)
      const pool = KANA_ITEMS.hiragana.seion
      expect(pool.length).toBeGreaterThan(KANA_ROUND_MAX_QUESTIONS)
      const total = KANA_ROUND_MAX_QUESTIONS
      const missed = 1
      // 두 번째 문항만 틀리고 다시 나와도 또 틀린다.
      const decide = (index: number, retry: boolean) => index !== missed && !retry
      await mountKana()
      startQuiz(CHOOSE)
      expect(title()).toBe(CHOOSE)

      const seen: Seen[] = []
      while (inQuiz()) {
        const question = currentQuestion()
        seen.push(question)
        const index = seen.length - 1
        const item = itemOf(pool, question.text)
        const correct = decide(index, question.retry)

        const options = byClass(root, 'kana-option')
        expect(options.map((node) => node.textContent)).toEqual(createKanaChoices(item, pool, () => random))
        expect(byClass(root, 'kana-feedback')).toEqual([])
        expect(byClass(root, 'kana-next')).toEqual([])

        const picked = correct
          ? options.find((node) => node.textContent === item.romaji)!
          : options.find((node) => node.textContent !== item.romaji)!
        const { feedback } = answerChoose(item, correct)

        if (correct) expect(feedback).toBe(TEXT.chooseRight)
        else if (question.retry) expect(feedback).toBe(TEXT.chooseWrong(item.romaji))
        else expect(feedback).toBe(`${TEXT.chooseWrong(item.romaji)} ${TEXT.willRetry}`)

        for (const node of options) {
          expect(node.disabled).toBe(true)
          expect(node.classList.contains('is-correct')).toBe(node.textContent === item.romaji)
          expect(node.classList.contains('is-wrong')).toBe(!correct && node === picked)
        }

        const last = question.retry
        expect(one('kana-next').textContent).toBe(last ? TEXT.showResult : TEXT.nextQuestion)
        press(last ? TEXT.showResult : TEXT.nextQuestion)
        expect(seen.length).toBeLessThanOrEqual(total + 1)
      }

      expect(seen.map(({ text, retry }) => ({ text, retry }))).toEqual(plannedQuestions(pool, random, decide))
      expect(seen).toHaveLength(total + 1)
      expect(seen[total]).toMatchObject({ text: seen[missed]!.text, retry: true })
      expect(seen.slice(0, missed + 1).map((question) => question.progress)).toEqual(
        seen.slice(0, missed + 1).map((_, index) => TEXT.progress(index + 1, total)),
      )
      expect(seen.slice(missed + 1).map((question) => question.progress)).toEqual(
        seen.slice(missed + 1).map((_, index) => TEXT.progress(missed + 2 + index, total + 1)),
      )

      expect(title()).toBe(TEXT.resultTitle)
      expect(one('kana-result-summary').textContent).toBe(TEXT.resultSome(total, total - 1))
      expect(one('kana-retried-title').textContent).toBe(TEXT.resultRetried)
      expect(texts('kana-retried-text')).toEqual([seen[missed]!.text])
    })
  }

  it('says every question was answered right at once with no retried list', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[1])
    const pool = KANA_ITEMS.katakana.handakuon
    const total = Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS)
    await mountKana('katakana', '#/kana/katakana')
    press(RANGE_LABEL.handakuon, one('kana-chips'))
    startQuiz(CHOOSE)

    let asked = 0
    while (inQuiz()) {
      const question = currentQuestion()
      asked += 1
      expect(question.retry).toBe(false)
      expect(question.progress).toBe(TEXT.progress(asked, total))
      answerChoose(itemOf(pool, question.text), true)
      press(asked === total ? TEXT.showResult : TEXT.nextQuestion)
    }

    expect(asked).toBe(total)
    expect(one('kana-result-summary').textContent).toBe(TEXT.resultAll(total))
    expect(flatText(root)).not.toContain(TEXT.resultRetried)
    expect(byClass(root, 'kana-retried-item')).toEqual([])
  })
})

// ---------------------------------------------------------------------------------------------
// 퀴즈 중·결과에서 표로 돌아가기, 한 번 더 풀기
// ---------------------------------------------------------------------------------------------

describe('leaving a round', () => {
  it('returns to the table from a quiz keeping the tab and range and the saved progress', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[0])
    await mountKana()
    select('katakana', 'yoon')
    startQuiz(CHOOSE)
    const pool = KANA_ITEMS.katakana.yoon
    const item = itemOf(pool, currentQuestion().text)
    answerChoose(item, true)
    expect(answerCount(storage)).toBe(1)

    press(TEXT.backToTable)

    expect(screenClass()).toContain('kana-home')
    expect(title()).toBe(TEXT.title)
    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.katakana])
    expect(pressed('kana-chips')).toEqual([RANGE_LABEL.yoon])
    expect(byClass(one('kana-table'), 'kana-row')).toHaveLength(KANA_TABLES.katakana.yoon.length)
    expect(storedProgress(storage)!.items).toEqual({ [item.key]: { correct: 1, wrong: 0 } })

    startQuiz(CHOOSE)
    expect(currentQuestion()).toMatchObject({
      progress: TEXT.progress(1, Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS)),
      retry: false,
    })
  })

  it('starts the same mode again or returns to the table from the result', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[0])
    const pool = KANA_ITEMS.hiragana.handakuon
    const total = Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS)
    await mountKana()
    select('hiragana', 'handakuon')
    startQuiz(READ)
    while (inQuiz()) answerRead(true)
    expect(title()).toBe(TEXT.resultTitle)

    press(TEXT.again)
    expect(title()).toBe(READ)
    expect(currentQuestion()).toMatchObject({ progress: TEXT.progress(1, total), retry: false })
    while (inQuiz()) answerRead(true)

    press(TEXT.backToTable)
    expect(title()).toBe(TEXT.title)
    expect(pressed('kana-tabs')).toEqual([SCRIPT_LABEL.hiragana])
    expect(pressed('kana-chips')).toEqual([RANGE_LABEL.handakuon])
  })
})

// ---------------------------------------------------------------------------------------------
// 진도 저장
// ---------------------------------------------------------------------------------------------

describe('progress in nc.kana.v1', () => {
  it('counts every answer including the retried one and stores the last study time', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[1])
    const pool = KANA_ITEMS.hiragana.sokuon
    await mountKana()
    select('hiragana', 'sokuon')
    startQuiz(READ)

    const expected: Record<string, { correct: number; wrong: number }> = {}
    let answers = 0
    let now = Date.now()
    while (inQuiz()) {
      const question = currentQuestion()
      const item = itemOf(pool, question.text)
      const correct = answers !== 0 // 첫 문항만 틀리고 다시 나오면 맞힌다
      now += 1000
      vi.setSystemTime(now)

      answerRead(correct)
      answers += 1

      const entry = (expected[item.key] ??= { correct: 0, wrong: 0 })
      if (correct) entry.correct += 1
      else entry.wrong += 1
      expect(answerCount(storage)).toBe(answers)
      expect(storedProgress(storage)).toEqual({ items: expected, lastStudiedAt: now })
    }

    expect(answers).toBe(Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS) + 1)
    expect(Object.values(expected).filter((entry) => entry.correct === 1 && entry.wrong === 1)).toHaveLength(1)
    expect([...storage.data.keys()]).toEqual([KANA_KEY])
  })

  it('counts the answers of 보고 고르기 too', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[0])
    const pool = KANA_ITEMS.katakana.gairaigo
    await mountKana('katakana', '#/kana/katakana')
    press(RANGE_LABEL.gairaigo, one('kana-chips'))
    startQuiz(CHOOSE)

    let answers = 0
    while (inQuiz()) {
      const question = currentQuestion()
      answerChoose(itemOf(pool, question.text), question.retry)
      answers += 1
      expect(answerCount(storage)).toBe(answers)
      press(one('kana-next').textContent)
    }
    expect(answers).toBe(2 * Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS))
  })

  it('finishes rounds of both modes and resets when localStorage throws', async () => {
    const storage = throwingStorage()
    vi.stubGlobal('localStorage', storage)
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[1])
    const pool = KANA_ITEMS.hiragana.dakuon
    const total = Math.min(pool.length, KANA_ROUND_MAX_QUESTIONS)
    await mountKana()
    select('hiragana', 'dakuon')

    startQuiz(READ)
    let asked = 0
    while (inQuiz()) {
      answerRead(asked !== 0)
      asked += 1
      expect(asked).toBeLessThanOrEqual(total + 1)
    }
    expect(one('kana-result-summary').textContent).toBe(TEXT.resultSome(total, total - 1))

    press(TEXT.backToTable)
    startQuiz(CHOOSE)
    asked = 0
    while (inQuiz()) {
      answerChoose(itemOf(pool, currentQuestion().text), asked !== 0)
      asked += 1
      press(one('kana-next').textContent)
      expect(asked).toBeLessThanOrEqual(total + 1)
    }
    expect(one('kana-result-summary').textContent).toBe(TEXT.resultSome(total, total - 1))
    expect(storage.setItem).toHaveBeenCalled()

    press(TEXT.backToTable)
    press(TEXT.reset)
    expect(toastsDuring(() => press(TEXT.resetConfirm))).toEqual([TEXT.resetDone])
  })
})

describe('진도 초기화', () => {
  const OTHER_KEYS = { 'nc.furigana.v1': 'furigana', 'nc.demo.v1': 'demo', unrelated: 'other' }

  function seededStorage() {
    const key = KANA_ITEMS.hiragana.seion[0]!.key
    return memoryStorage({
      ...OTHER_KEYS,
      [KANA_KEY]: JSON.stringify({ items: { [key]: { correct: 2, wrong: 3 } }, lastStudiedAt: 5 }),
    })
  }

  it('asks inline and cancel keeps the progress without a toast', async () => {
    const storage = seededStorage()
    const before = storage.data.get(KANA_KEY)
    vi.stubGlobal('localStorage', storage)
    await mountKana()

    press(TEXT.reset)
    const box = one('kana-save')
    expect(texts('kana-confirm-question', box)).toEqual([TEXT.resetQuestion])
    expect(texts('kana-confirm-detail', box)).toEqual([TEXT.resetDetail])
    expect(buttons(box).map((node) => node.textContent)).toEqual([TEXT.resetConfirm, TEXT.resetCancel])
    expect(hasButton(TEXT.reset)).toBe(false)
    expect(texts('kana-save-text')).toEqual([])
    expect(texts('sheet')).toEqual([])

    expect(toastsDuring(() => press(TEXT.resetCancel))).toEqual([])

    expect(storage.data.get(KANA_KEY)).toBe(before)
    expect(texts('kana-save-text')).toEqual([TEXT.saveNote])
    expect(hasButton(TEXT.reset)).toBe(true)
    expect(byClass(root, 'kana-confirm-question')).toEqual([])
  })

  it('confirm removes only nc.kana.v1, toasts, and the next answer starts from zero', async () => {
    const storage = seededStorage()
    vi.stubGlobal('localStorage', storage)
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[0])
    await mountKana()

    press(TEXT.reset)
    expect(toastsDuring(() => press(TEXT.resetConfirm))).toEqual([TEXT.resetDone])

    expect(storage.data.has(KANA_KEY)).toBe(false)
    expect(Object.fromEntries(storage.data)).toEqual(OTHER_KEYS)
    expect(texts('kana-save-text')).toEqual([TEXT.saveNote])
    expect(byClass(root, 'kana-confirm-question')).toEqual([])

    startQuiz(READ)
    const item = itemOf(KANA_ITEMS.hiragana.seion, currentQuestion().text)
    answerRead(true)
    expect(storedProgress(storage)!.items).toEqual({ [item.key]: { correct: 1, wrong: 0 } })
  })
})

// ---------------------------------------------------------------------------------------------
// 격리: hash·history·요청
// ---------------------------------------------------------------------------------------------

describe('round state stays out of the url', () => {
  it('never changes location.hash nor pushes history through tabs, chips, a round and the result', async () => {
    vi.spyOn(Math, 'random').mockReturnValue(RANDOM_VALUES[1])
    const hash = '#/kana/katakana'
    await mountKana('katakana', hash)
    const steps: (() => void)[] = [
      () => select('hiragana', 'gairaigo'),
      () => press(TEXT.showKatakana),
      () => select('katakana', 'sokuon'),
      () => startQuiz(READ),
      () => answerRead(false),
      () => {
        while (inQuiz()) answerRead(false)
      },
      () => press(TEXT.again),
      () => press(TEXT.backToTable),
      () => startQuiz(CHOOSE),
      () => {
        while (inQuiz()) {
          answerChoose(itemOf(KANA_ITEMS.katakana.sokuon, currentQuestion().text), false)
          press(one('kana-next').textContent)
        }
      },
      () => press(TEXT.backToTable),
      () => press(TEXT.reset),
      () => press(TEXT.resetConfirm),
    ]

    for (const step of steps) {
      step()
      await vi.advanceTimersByTimeAsync(0)
      expect(browser.location.hash).toBe(hash)
    }

    expect(browser.entries()).toEqual([hash])
    expect(browser.replaceStateCalls).toEqual([])
    expect(browser.listenerTypes()).toEqual([])
    expect(navigations).toEqual([])
    expect(logins).toBe(0)
  })
})
