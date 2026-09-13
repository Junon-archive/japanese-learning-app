/**
 * Demo 화면(`03_UI_UX_SPEC.md`의 `Demo`, 합격 기준 39·40·42·43). 문구는 `화면 문구 표`의 `Demo`와 같다.
 *
 * 진행 규칙 자체와 저장값 검증은 `demo-progress.test.ts`가 본다. 여기서는 사용자가 보는 화면이다.
 *
 * 모든 테스트에 걸린 단정 둘:
 *
 * 1.  **`fetch`가 한 번도 불리지 않는다.** 던지는 스텁이고 `afterEach`가 호출 0회를 단정한다. 정적 검사
 *     (`demo-isolation.test.ts`)는 "코드에 없다"까지고, 이 테스트가 "그래서 아무것도 안 나간다"를 말한다.
 * 2.  **`nc.demo.v1`(과 토글을 누르면 `nc.furigana.v1`) 밖에 쓰지 않는다.** localStorage의 다른 key,
 *     sessionStorage, cookie에 쓰면 `afterEach`에서 드러난다.
 *
 * 숫자는 fixture 길이와 `constants.ts`에서 온다. 테스트에 적지 않는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEMO_PROBE_EVERY_SENTENCES as P, DEMO_REVIEW_AFTER_SENTENCES as R } from '../../src/demo/constants'
import { DEMO_FIXTURE_ID, DEMO_SENTENCES } from '../../src/demo/fixture'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, descendants, fakeDocument, flatText, textWithoutRt } from './fake-dom'
import type { DemoModules, MemoryStorage, MountedDemo } from './demo-harness'
import {
  answerProbe,
  click,
  flush,
  freshDemo,
  memoryStorage,
  mountDemo,
  next,
  press,
  progressLabel,
  progressText,
  selfReport,
  sentenceOnScreen,
} from './demo-harness'

const DEMO_KEY = 'nc.demo.v1'
const FURIGANA_KEY = 'nc.furigana.v1'
const TOTAL = DEMO_SENTENCES.length

const COPY = {
  title: '표현 학습 체험',
  banner: '체험 중이에요. 기록은 이 브라우저에만 남아요.',
  reset: '진도 초기화',
  resetQuestion: '진도를 초기화할까요?',
  resetDetail: '이 브라우저에 남은 체험 기록이 지워져요.',
  resetConfirm: '초기화하기',
  resetCancel: '취소',
  resetDone: '진도를 초기화했어요.',
  flagSubmitted: '체험에서는 신고가 저장되지 않아요.',
  next: '다음 문장',
  completeTitle: `${TOTAL}문장을 모두 봤어요.`,
  completeThanks: '끝까지 둘러봐 주셔서 고마워요.',
  learnKana: '글자 배우기',
  restart: '처음부터 다시',
  restartNote: '처음부터 다시 하면 체험 기록이 지워져요.',
  probePrompt: '이 표현을 알고 계세요?',
  probeOptions: ['알고 있었음', '애매함', '몰랐음', '건너뛰기'],
  furigana: '후리가나',
  login: '로그인',
} as const

/** Study Screen의 시간 진행과 세션 끝(`ui/progress.ts`, `ui/session-end.ts`)에만 있는 것. demo에 없어야 한다. */
const SESSION_ONLY_CLASSES = ['progress', 'progress-bar', 'progress-label', 'session-end', 'session-finished']
const SESSION_ONLY_TEXTS = ['오늘 학습 완료', '더 학습하기', '오늘 목표한 시간을 채웠어요.', '오늘 학습을 마쳤어요.']

const fetchMock = vi.fn(() => {
  throw new Error('demo must not make network requests')
})

let modules: DemoModules
let page: MountedDemo
let local: MemoryStorage
let session: MemoryStorage
let cookieWrites: string[]

function documentWithCookieJar(): object {
  const doc: Record<string, unknown> = { ...fakeDocument() }
  Object.defineProperty(doc, 'cookie', {
    get: () => '',
    set: (value: string) => {
      cookieWrites.push(value)
    },
  })
  return doc
}

function screen(): FakeElement {
  const current = page.root.children[0]
  expect(current).toBeDefined()
  return current!
}

function text(): string {
  return textWithoutRt(page.root)
}

function topBarRight(): (string | null)[] {
  const bar = byClass(page.root, 'topbar')
  expect(bar).toHaveLength(1)
  return buttons(byClass(bar[0]!, 'topbar-actions')[0]!).map((button) => button.textContent)
}

/** 새 페이지로 연다(모듈 새로 불러오기). `stored`가 있으면 그 진도가 저장된 브라우저다. */
async function reopen(stored?: object): Promise<void> {
  if (stored !== undefined) local.data.set(DEMO_KEY, JSON.stringify(stored))
  modules = await freshDemo()
  page = mountDemo(modules)
}

beforeEach(async () => {
  fetchMock.mockClear()
  cookieWrites = []
  local = memoryStorage()
  session = memoryStorage()
  vi.stubGlobal('document', documentWithCookieJar())
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', local)
  vi.stubGlobal('sessionStorage', session)
  await reopen()
})

afterEach(() => {
  // **모든** 테스트에 걸린다. 어느 경로가 요청을 보내거나 저장소를 쓰든 그 테스트에서 직접 드러난다.
  expect(fetchMock).not.toHaveBeenCalled()
  expect(local.writtenKeys.filter((key) => key !== DEMO_KEY && key !== FURIGANA_KEY)).toEqual([])
  expect(session.writtenKeys).toEqual([])
  expect(cookieWrites).toEqual([])
  vi.unstubAllGlobals()
})

describe('demo fixture', () => {
  it('has sentences with every tappable item explained', () => {
    expect(TOTAL).toBeGreaterThan(0)

    for (const entry of DEMO_SENTENCES) {
      expect(entry.korean_translation).not.toBe('')
      expect(entry.presentation.tappable_items.length).toBeGreaterThan(0)
      for (const item of entry.presentation.tappable_items) {
        const explanation = entry.explanations[item.sentence_item_id]
        expect(explanation, `no explanation for ${item.sentence_item_id}`).toBeDefined()
        expect(explanation!.learning_item_id).toBe(item.learning_item_id)
        for (const field of [
          explanation!.canonical_form,
          explanation!.reading,
          explanation!.item_type,
          explanation!.core_meaning,
          explanation!.meaning_in_context,
          explanation!.nuance,
          explanation!.example_sentence,
        ]) {
          expect(field).toBeTruthy()
        }
      }
      // render_segments를 이으면 그 문장이다. demo도 offset을 계산하지 않는다.
      expect(entry.presentation.render_segments.map((s) => s.text).join('')).toBe(entry.presentation.japanese)
      // 번역은 payload에 없다. 누른 뒤에 건넨다.
      expect(JSON.stringify(entry.presentation)).not.toContain(entry.korean_translation)
    }
  })
})

describe('demo screen', () => {
  it('says it is a demo and shows the progress as seen / total', () => {
    expect(screen().querySelector('h1')!.textContent).toBe(COPY.title)
    const banner = byClass(page.root, 'demo-banner')
    expect(banner).toHaveLength(1)
    expect(flatText(banner[0]!)).toContain(COPY.banner)
    expect(buttons(banner[0]!).map((button) => button.textContent)).toEqual([COPY.reset])

    expect(progressText(page.root)).toBe(progressLabel(1, TOTAL))
    // 문장 바로 아래 힌트. Study Screen과 같다.
    expect(flatText(byClass(page.root, 'sentence-box')[0]!)).toContain(MESSAGES.sentenceHint)
  })

  it('has no 12-minute bar, no session end, and no extension, down to the completion screen', async () => {
    function expectNoSessionUi(): void {
      for (const name of SESSION_ONLY_CLASSES) expect(byClass(page.root, name), name).toEqual([])
      for (const phrase of SESSION_ONLY_TEXTS) expect(text()).not.toContain(phrase)
      expect(descendants(page.root).filter((node) => node.getAttribute('role') === 'progressbar')).toEqual([])
    }

    expectNoSessionUi()
    await reopen({ ...startOf(), position: TOTAL - 1, seen: TOTAL })
    expectNoSessionUi()
    next(page.root)
    expect(sentenceOnScreen(page.root)).toBeNull()
    expectNoSessionUi()
  })

  it('walks a sentence without a single request', async () => {
    const [first, second] = DEMO_SENTENCES

    // 1. 첫 문장. 일본어가 먼저고 번역은 없다.
    expect(sentenceOnScreen(page.root)).toBe(first!.presentation.japanese)
    expect(text()).not.toContain(first!.korean_translation)
    expect(byClass(page.root, 'translation')).toEqual([])

    // 2. 탭 -> 설명 시트.
    click(page.root, 'token')
    await flush()
    const firstExplanation = first!.explanations[first!.presentation.tappable_items[0]!.sentence_item_id]!
    expect(text()).toContain(firstExplanation.core_meaning)
    expect(text()).toContain(firstExplanation.reading)

    // 3. 자기평가는 선택이다. 누르면 잠긴다.
    click(page.root, 'self-report', 1)
    await flush()
    expect(byClass(page.root, 'self-report')).toEqual([])

    // 4. 번역은 누른 뒤에 생긴다.
    click(page.root, 'reveal-translation')
    await flush()
    expect(text()).toContain(first!.korean_translation)

    // 5. 다음 문장 -> 두 번째 문장. 번역은 다시 숨어 있고 본 문장 수가 하나 늘었다.
    next(page.root)
    expect(sentenceOnScreen(page.root)).toBe(second!.presentation.japanese)
    expect(text()).not.toContain(second!.korean_translation)
    expect(progressText(page.root)).toBe(progressLabel(2, TOTAL))
  })

  it('renders ruby in the sentence while the text without rt stays the original', () => {
    const { presentation } = DEMO_SENTENCES[0]!
    const readings = presentation.render_segments.flatMap((segment) =>
      segment.ruby.flatMap((part) => (part.reading === null ? [] : [part.reading])),
    )
    expect(readings.length, 'the first fixture sentence has readings (premise)').toBeGreaterThan(0)

    const sentence = byClass(page.root, 'sentence')[0]!
    expect(textWithoutRt(sentence)).toBe(presentation.japanese)
    expect(sentence.querySelectorAll('rt').map((rt) => rt.textContent)).toEqual(readings)
    expect(sentence.getAttribute('aria-label')).toBe(presentation.japanese)
  })

  it('brings back a sentence self-reported unknown after the review interval without counting it again', async () => {
    const first = sentenceOnScreen(page.root)
    await selfReport(page.root, 0, '몰랐음')

    for (let i = 1; i <= R; i += 1) {
      next(page.root)
      expect(sentenceOnScreen(page.root)).not.toBe(first)
      expect(progressText(page.root)).toBe(progressLabel(1 + i, TOTAL))
    }
    next(page.root)
    expect(sentenceOnScreen(page.root)).toBe(first)
    expect(progressText(page.root)).toBe(progressLabel(R + 1, TOTAL))
  })

  it('shows a probe at the checkpoint with the fixed prompt, the expression without ruby, and four choices', async () => {
    for (let seen = 2; seen <= P; seen += 1) {
      expect(byClass(page.root, 'probe'), `probe before seen ${seen - 1}`).toEqual([])
      next(page.root)
    }
    expect(progressText(page.root)).toBe(progressLabel(P, TOTAL))

    // 아무 자기평가도 없으므로 먼저 본 순서의 첫 표현이다.
    const { presentation } = DEMO_SENTENCES[0]!
    const firstItem = presentation.tappable_items[0]!
    const sameItem = new Set(
      presentation.tappable_items
        .filter((item) => item.learning_item_id === firstItem.learning_item_id)
        .map((item) => item.sentence_item_id),
    )
    const expression = presentation.render_segments
      .filter((segment) => segment.sentence_item_id !== null && sameItem.has(segment.sentence_item_id))
      .map((segment) => segment.text)
      .join('')

    const probe = byClass(page.root, 'probe')
    expect(probe).toHaveLength(1)
    expect(byClass(probe[0]!, 'probe-prompt')[0]!.textContent).toBe(COPY.probePrompt)
    const shown = byClass(probe[0]!, 'probe-expression')[0]!
    expect(shown.textContent).toBe(expression)
    expect(shown.querySelectorAll('rt')).toEqual([])
    expect(byClass(probe[0]!, 'probe-option').map((button) => button.textContent)).toEqual(COPY.probeOptions)

    await answerProbe(page.root, '몰랐음')
    expect(byClass(page.root, 'probe-option')).toEqual([])
    expect(byClass(page.root, 'probe-answered')).toHaveLength(1)
  })

  it('asks for inline confirmation before resetting, then shows the first sentence and a toast', () => {
    next(page.root)

    press(page.root, COPY.reset)
    const banner = byClass(page.root, 'demo-banner')[0]!
    expect(flatText(banner)).toContain(COPY.resetQuestion)
    expect(flatText(banner)).toContain(COPY.resetDetail)
    expect(buttons(banner).map((button) => button.textContent)).toEqual([COPY.resetConfirm, COPY.resetCancel])
    // 확인은 시트가 아니다.
    expect(byClass(page.root, 'sheet')).toEqual([])
    expect(descendants(page.root).filter((node) => node.getAttribute('role') === 'dialog')).toEqual([])

    press(page.root, COPY.resetCancel)
    expect(buttons(byClass(page.root, 'demo-banner')[0]!).map((button) => button.textContent)).toEqual([COPY.reset])
    expect(progressText(page.root)).toBe(progressLabel(2, TOTAL))

    press(page.root, COPY.reset)
    press(page.root, COPY.resetConfirm)
    expect(sentenceOnScreen(page.root)).toBe(DEMO_SENTENCES[0]!.presentation.japanese)
    expect(progressText(page.root)).toBe(progressLabel(1, TOTAL))
    expect(flatText(document.body as unknown as FakeElement)).toContain(COPY.resetDone)
    expect(local.data.has(DEMO_KEY)).toBe(false)
  })

  it('flags a sentence without a request and says so', async () => {
    click(page.root, 'flag-open')
    click(page.root, 'flag-reason', 0)
    await flush()

    // demo 전용 안내. 요청을 보내지 않으므로 저장됐다고 말하지 않는다.
    expect(text()).toContain(COPY.flagSubmitted)
    expect(text()).not.toContain('이제 나오지 않아요')
  })

  it('ends on the completion screen with two actions and only 로그인 in the top bar', async () => {
    await reopen({ ...startOf(), position: TOTAL - 1, seen: TOTAL })
    expect(sentenceOnScreen(page.root)).toBe(DEMO_SENTENCES[TOTAL - 1]!.presentation.japanese)
    expect(progressText(page.root)).toBe(progressLabel(TOTAL, TOTAL))

    next(page.root)

    expect(sentenceOnScreen(page.root)).toBeNull()
    const title = screen().querySelector('h1')!
    expect(title.textContent).toBe(COPY.completeTitle)
    expect(text()).toContain(COPY.completeThanks)
    expect(text()).toContain(COPY.restartNote)
    const bar = byClass(page.root, 'topbar')[0]!
    expect(buttons(screen()).filter((button) => !descendants(bar).includes(button)).map((b) => b.textContent)).toEqual([
      COPY.learnKana,
      COPY.restart,
    ])
    // 후리가나 토글은 문장이 있는 화면에만 둔다(W3-6).
    expect(topBarRight()).toEqual([COPY.login])
    // 통계·정답률이 없다: 제목(문장 수) 밖에 숫자가 없다.
    expect(text().replace(COPY.completeTitle, '')).not.toMatch(/\d/)

    press(page.root, COPY.learnKana)
    expect(page.navigations).toEqual(['#/kana'])
  })

  it('starts over from the completion screen after deleting the demo progress', async () => {
    await reopen({ ...startOf(), position: TOTAL - 1, seen: TOTAL })
    next(page.root)
    expect(local.data.has(DEMO_KEY)).toBe(true)

    press(page.root, COPY.restart)

    expect(local.data.has(DEMO_KEY)).toBe(false)
    expect(sentenceOnScreen(page.root)).toBe(DEMO_SENTENCES[0]!.presentation.japanese)
    expect(progressText(page.root)).toBe(progressLabel(1, TOTAL))
    expect(topBarRight()).toEqual([COPY.furigana, COPY.login])
    expect(page.navigations).toEqual([])
  })

  it('shows only fixed wording when the fixture lacks an explanation', async () => {
    const explanations = modules.fixture.DEMO_SENTENCES[0]!.explanations
    const id = modules.fixture.DEMO_SENTENCES[0]!.presentation.tappable_items[0]!.sentence_item_id
    const saved = explanations[id]!
    delete explanations[id]
    try {
      click(page.root, 'token')
      await flush()

      // 예외 메시지(영어, fixture id)를 화면에 내지 않는다.
      expect(text()).toContain(MESSAGES.notFound)
      expect(byClass(page.root, 'sheet')).toEqual([])
      expect(text()).not.toMatch(/Error|undefined|fixture/)
      expect(text()).not.toContain(String(id))
    } finally {
      explanations[id] = saved
    }
  })

  it('has no logout control', () => {
    // Demo는 Login 화면을 지나지 않으므로 폐기할 세션이 없다(03_UI_UX_SPEC.md의 `로그아웃`).
    expect(text()).not.toContain('로그아웃')
    expect(byClass(page.root, 'logout')).toEqual([])
  })

  it('has 후리가나 and 로그인 in the top bar and leaves only through it', () => {
    expect(topBarRight()).toEqual([COPY.furigana, COPY.login])
    expect(byClass(page.root, 'demo-exit')).toEqual([])

    click(page.root, 'topbar-brand')
    expect(page.navigations).toEqual(['#/'])
    expect(page.logins()).toBe(0)

    // 로그인 진입은 넘겨받은 값을 상단바가 누를 때 부른다. demo가 직접 부르지 않는다.
    click(page.root, 'topbar-login')
    expect(page.logins()).toBe(1)
  })

  it('switches furigana by a document class without re-rendering the sentence', () => {
    const sentence = byClass(page.root, 'sentence')[0]
    const toggle = byClass(page.root, 'furigana-toggle')[0]!
    expect(toggle.getAttribute('aria-pressed')).toBe('false')

    toggle.click()

    expect(toggle.getAttribute('aria-pressed')).toBe('true')
    expect(document.documentElement.classList.contains('furigana-on')).toBe(true)
    expect(byClass(page.root, 'sentence')[0]).toBe(sentence)
    expect(JSON.parse(local.data.get(FURIGANA_KEY)!)).toEqual({ on: true })
  })

  it('writes nothing outside nc.demo.v1 while studying, and only when the progress moves', async () => {
    click(page.root, 'token')
    await flush()
    click(page.root, 'reveal-translation')
    await flush()
    click(page.root, 'flag-open')
    click(page.root, 'flag-reason', 0)
    await flush()
    // 탭·설명·번역·신고는 진도가 아니다.
    expect(local.writtenKeys).toEqual([])

    await selfReport(page.root, 0, '몰랐음')
    // 다시 보기 한 번이 끼므로 누르는 횟수가 아니라 진행 표시로 체크포인트를 찾는다.
    for (let presses = 0; progressText(page.root) !== progressLabel(P, TOTAL); presses += 1) {
      expect(presses).toBeLessThanOrEqual(P + R)
      next(page.root)
    }
    await answerProbe(page.root, '건너뛰기')
    expect([...local.data.keys()]).toEqual([DEMO_KEY])
    // 가리키는 것은 fixture 순번과 표현 id다. 문장·번역·설명을 옮겨 적지 않는다.
    const stored = local.data.get(DEMO_KEY)!
    expect(stored).not.toContain(DEMO_SENTENCES[0]!.presentation.japanese)
    expect(stored).not.toContain(DEMO_SENTENCES[0]!.korean_translation)

    press(page.root, COPY.reset)
    press(page.root, COPY.resetConfirm)
    expect(new Set(local.writtenKeys)).toEqual(new Set([DEMO_KEY]))
    expect([...local.data.keys()]).toEqual([])
  })
})

/** 첫 문장 진도의 저장 모양(지금 fixture). 완료 직전 값을 만들 때 쓴다. */
function startOf(): Record<string, unknown> {
  const { initialProgress, DEMO_FIXTURE } = modules.progress
  const start = initialProgress(DEMO_FIXTURE)
  expect(start.fixtureId).toBe(DEMO_FIXTURE_ID)
  return { ...start }
}
