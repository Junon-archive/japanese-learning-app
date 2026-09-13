/**
 * Demo 진행 규칙과 진도 저장(`12_TEST_PLAN.md`의 `Demo`, 합격 기준 40·41·42, 변이 검증 18).
 *
 * 규칙의 canonical은 `03_UI_UX_SPEC.md`의 `Demo` > `진행 규칙`·`진도 저장`, 값 범위는
 * `04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`다. 메인 결정 G1·G2·W3-6도 여기서 고정한다.
 *
 * -   **숫자를 복사하지 않는다.** 간격은 `constants.ts`의 두 상수, 문장 수는 fixture 길이에서 온다.
 * -   진행 규칙은 순수 함수라서 작은 합성 fixture로 본다. 저장(`isDemoProgress`)은 지금 번들의 fixture가
 *     기준이므로 실제 fixture로 본다.
 * -   화면을 거치는 것(새로고침 뒤 이어짐, 저장이 막힌 브라우저에서 끝까지, 초기화, 신고한 문장)은 가짜 DOM에
 *     demo를 올려 본다. `fetch`는 던지는 스텁이고 모든 테스트 끝에 호출 0회를 단정한다.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { DEMO_PROBE_EVERY_SENTENCES as P, DEMO_REVIEW_AFTER_SENTENCES as R } from '../../src/demo/constants'
import type { DemoSentence } from '../../src/demo/fixture'
import { DEMO_FIXTURE_ID, DEMO_SENTENCES } from '../../src/demo/fixture'
import type { DemoFixture, DemoProgress } from '../../src/demo/progress'
import {
  DEMO_FIXTURE,
  advance,
  initialProgress,
  isComplete,
  isDemoProgress,
  nextView,
  pickProbe,
  recordProbeAnswer,
  recordSelfReport,
} from '../../src/demo/progress'
import type { ExplicitSignal } from '../../src/types'
import { byClass, fakeDocument } from './fake-dom'
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
  throwingStorage,
} from './demo-harness'
import { SRC, createProject } from './import-graph'

const DEMO_KEY = 'nc.demo.v1'
const FURIGANA_KEY = 'nc.furigana.v1'
const KANA_KEY = 'nc.kana.v1'

// ---------------------------------------------------------------------------------------------
// 합성 fixture
// ---------------------------------------------------------------------------------------------

/** 문장 하나. tappable 표현이 `items`(learning_item_id) 순서로 들어간다. */
function sentence(items: readonly number[], index: number): DemoSentence {
  const tappable = items.map((learning_item_id, k) => ({
    sentence_item_id: (index + 1) * 10 + k + 1,
    learning_item_id,
  }))
  const segments = tappable.map((item) => ({
    text: `語${item.sentence_item_id}`,
    sentence_item_id: item.sentence_item_id,
    ruby: [],
  }))
  return {
    presentation: {
      presentation_id: index + 1,
      sentence_id: index + 1,
      japanese: segments.map((segment) => segment.text).join(''),
      render_segments: segments,
      presentation_role: 'new',
      review_reason: null,
      context_stage: 'anchor',
      translation_revealed: false,
      tappable_items: tappable,
      probe: null,
    },
    korean_translation: `번역 ${index}`,
    explanations: {},
  }
}

/** 두 상수보다 넉넉히 긴 fixture. 문장마다 서로 다른 표현 하나이고 `overrides`의 문장만 바꾼다. */
const SIZE = 3 * (R + P)
const UNIQUE_ITEM_BASE = 1000

function fixtureOf(overrides: Record<number, readonly number[]> = {}, size = SIZE): DemoFixture {
  const sentences = Array.from({ length: size }, (_, index) =>
    sentence(overrides[index] ?? [UNIQUE_ITEM_BASE + index], index),
  )
  return { id: 'synthetic', sentences }
}

function itemsOf(fixture: DemoFixture, index: number): number[] {
  return fixture.sentences[index]!.presentation.tappable_items.map((item) => item.learning_item_id)
}

type Shown = { index: number; seen: number; review: boolean }

/** `다음 문장`을 `times`번 누르고, 누를 때마다 보인 문장(순번, 그때의 본 문장 수, 다시 보기인가). */
function pressNext(fixture: DemoFixture, start: DemoProgress, times: number): { progress: DemoProgress; shown: Shown[] } {
  let progress = start
  const shown: Shown[] = []
  for (let i = 0; i < times; i += 1) {
    progress = advance(fixture, progress)
    const view = nextView(fixture, progress)
    if (view === null) break
    shown.push({ index: view.index, seen: progress.seen, review: view.review })
  }
  return { progress, shown }
}

/** 본 문장 수가 `seen`이 될 때까지 누른다(다시 보기도 누른다). */
function pressUntilSeen(fixture: DemoFixture, start: DemoProgress, seen: number): DemoProgress {
  let progress = start
  for (let guard = 0; progress.seen < seen || nextView(fixture, progress)?.review === true; guard += 1) {
    expect(guard, 'did not reach the wanted seen count').toBeLessThan(2 * fixture.sentences.length)
    progress = advance(fixture, progress)
  }
  expect(progress.seen).toBe(seen)
  return progress
}

const upTo = (count: number, from = 0): number[] => Array.from({ length: count }, (_, i) => from + i)

// ---------------------------------------------------------------------------------------------
// 다시 보기 (진행 규칙 2·4·5)
// ---------------------------------------------------------------------------------------------

describe('review: the same sentence once more', () => {
  it.each<ExplicitSignal>(['unknown', 'uncertain'])(
    'brings a sentence back after DEMO_REVIEW_AFTER_SENTENCES new sentences when self-reported %s',
    (value) => {
      const fixture = fixtureOf()
      const reported = recordSelfReport(fixture, initialProgress(fixture), itemsOf(fixture, 0)[0]!, value)

      const { shown } = pressNext(fixture, reported, R + 2)

      // 새 문장 R개 -> 같은 문장(다시 보기) -> 다음 새 문장.
      expect(shown.map((view) => view.index)).toEqual([...upTo(R, 1), 0, R + 1])
      expect(shown.map((view) => view.review)).toEqual([...upTo(R).map(() => false), true, false])
      // 다시 보여준 문장은 본 문장 수를 올리지 않는다.
      expect(shown.map((view) => view.seen)).toEqual([...upTo(R, 2), R + 1, R + 2])
    },
  )

  it('does not bring back a sentence self-reported known', () => {
    const fixture = fixtureOf()
    const reported = recordSelfReport(fixture, initialProgress(fixture), itemsOf(fixture, 0)[0]!, 'known')

    const { progress, shown } = pressNext(fixture, reported, R + 2)

    expect(shown.map((view) => view.index)).toEqual(upTo(R + 2, 1))
    expect(progress.queue).toEqual([])
  })

  it('queues a sentence at most once and never reviews it twice', () => {
    const fixture = fixtureOf({ 0: [1, 2] })
    let progress = initialProgress(fixture)
    progress = recordSelfReport(fixture, progress, 1, 'unknown')
    progress = recordSelfReport(fixture, progress, 2, 'uncertain')
    expect(progress.queue.map((entry) => entry.index)).toEqual([0])

    progress = pressNext(fixture, progress, R + 1).progress
    expect(nextView(fixture, progress)).toMatchObject({ index: 0, review: true })

    // 다시 보기 중의 자기평가는 값을 덮어쓰지만(W3-6) 문장을 다시 넣지 않는다.
    progress = recordSelfReport(fixture, progress, 1, 'unknown')
    progress = recordSelfReport(fixture, progress, 2, 'known')
    expect(progress.selfReports).toEqual({ '1': 'unknown', '2': 'known' })
    expect(progress.queue).toEqual([])

    const { shown } = pressNext(fixture, progress, 2 * SIZE)
    expect(shown.filter((view) => view.index === 0)).toEqual([])
  })

  it('shows what is left in the queue right away, in queue order, when the new sentences run out (G1)', () => {
    const fixture = fixtureOf()
    const last = SIZE - 1
    let progress = pressNext(fixture, initialProgress(fixture), last - 1).progress
    expect(progress.position).toBe(last - 1)

    progress = recordSelfReport(fixture, progress, itemsOf(fixture, last - 1)[0]!, 'unknown')
    progress = advance(fixture, progress)
    expect(progress.position).toBe(last)
    progress = recordSelfReport(fixture, progress, itemsOf(fixture, last)[0]!, 'uncertain')
    // probe로 앞 문장도 넣는다. 대기열 순서(넣은 순서)가 순번 순서와 다르게 한다.
    progress = recordProbeAnswer(fixture, progress, itemsOf(fixture, 0)[0]!, 'unknown')
    expect(progress.queue.map((entry) => entry.index)).toEqual([last - 1, last, 0])
    // 셋 다 아직 때가 되지 않았다. 그래도 곧바로 나온다.
    expect(progress.queue.every((entry) => entry.due > progress.seen)).toBe(true)

    const { progress: end, shown } = pressNext(fixture, progress, 4)

    expect(shown).toEqual([
      { index: last - 1, seen: SIZE, review: true },
      { index: last, seen: SIZE, review: true },
      { index: 0, seen: SIZE, review: true },
    ])
    expect(isComplete(fixture, end)).toBe(true)
    expect(end.seen).toBe(SIZE)
  })

  it('is complete only when every sentence was seen and the queue is empty', () => {
    const fixture = fixtureOf()
    let progress = initialProgress(fixture)
    const newSentences: number[] = [0]
    let reviews = 0

    for (let guard = 0; !isComplete(fixture, progress); guard += 1) {
      expect(guard).toBeLessThan(2 * SIZE)
      const view = nextView(fixture, progress)!
      // 세 문장에 한 번 몰랐음.
      if (!view.review && view.index % 3 === 0) {
        progress = recordSelfReport(fixture, progress, itemsOf(fixture, view.index)[0]!, 'unknown')
      }
      const before = progress
      progress = advance(fixture, progress)
      if (isComplete(fixture, progress)) {
        expect(before.seen).toBe(SIZE)
        expect(before.queue).toEqual([])
        break
      }
      const shown = nextView(fixture, progress)!
      if (shown.review) reviews += 1
      else newSentences.push(shown.index)
    }

    expect(newSentences).toEqual(upTo(SIZE))
    expect(reviews).toBe(Math.ceil(SIZE / 3))
    expect(nextView(fixture, progress)).toBeNull()
    expect(advance(fixture, progress)).toBe(progress)
  })

  it('starts complete for an empty fixture', () => {
    const empty: DemoFixture = { id: 'empty', sentences: [] }
    expect(isComplete(empty, initialProgress(empty))).toBe(true)
  })
})

// ---------------------------------------------------------------------------------------------
// probe (진행 규칙 3, G2, W3-6)
// ---------------------------------------------------------------------------------------------

describe('probe', () => {
  it('is offered only on the new sentence where the seen count reaches a multiple of DEMO_PROBE_EVERY_SENTENCES', () => {
    const fixture = fixtureOf()
    let progress = initialProgress(fixture)
    const offeredAt: number[] = []
    for (let guard = 0; !isComplete(fixture, progress); guard += 1) {
      expect(guard).toBeLessThan(2 * SIZE)
      if (pickProbe(fixture, progress) !== null) offeredAt.push(progress.seen)
      progress = advance(fixture, progress)
    }

    const multiples = upTo(Math.floor(SIZE / P), 1).map((k) => k * P)
    expect(multiples.length).toBeGreaterThan(1)
    expect(offeredAt).toEqual(multiples)
  })

  it('picks expressions in the order they were first seen, skipping self-reported and asked ones', () => {
    const fixture = fixtureOf({ 0: [1, 2], 1: [3] })
    let progress = recordSelfReport(fixture, initialProgress(fixture), 1, 'known')

    progress = pressUntilSeen(fixture, progress, P)
    expect(pickProbe(fixture, progress)).toEqual({ learningItemId: 2, sentenceIndex: 0 })
    progress = recordProbeAnswer(fixture, progress, 2, 'skip')
    // 이 체크포인트에서는 다시 묻지 않는다(새로고침 뒤에도 같다).
    expect(pickProbe(fixture, progress)).toBeNull()

    progress = pressUntilSeen(fixture, progress, 2 * P)
    expect(pickProbe(fixture, progress)).toEqual({ learningItemId: 3, sentenceIndex: 1 })
    progress = recordProbeAnswer(fixture, progress, 3, 'known')

    progress = pressUntilSeen(fixture, progress, 3 * P)
    expect(pickProbe(fixture, progress)).toEqual({ learningItemId: itemsOf(fixture, 2)[0], sentenceIndex: 2 })
  })

  it('skips a checkpoint with no candidate and offers one at the next checkpoint', () => {
    const fixture = fixtureOf()
    let progress = initialProgress(fixture)
    // 체크포인트 문장보다 앞의 모든 표현에 자기평가를 남긴다.
    for (let index = 0; index < P - 1; index += 1) {
      progress = recordSelfReport(fixture, progress, itemsOf(fixture, index)[0]!, 'known')
      progress = advance(fixture, progress)
    }
    expect(progress.seen).toBe(P)
    expect(pickProbe(fixture, progress)).toBeNull()

    progress = pressUntilSeen(fixture, progress, 2 * P)
    expect(pickProbe(fixture, progress)).toEqual({ learningItemId: itemsOf(fixture, P - 1)[0], sentenceIndex: P - 1 })
  })

  it.each(['known', 'uncertain', 'unknown', 'skip'])(
    'asks an expression once, even when it appears again, after a %s answer',
    (value) => {
      const repeated = 7
      const fixture = fixtureOf({ 0: [repeated], [P]: [repeated] })
      let progress = pressUntilSeen(fixture, initialProgress(fixture), P)
      expect(pickProbe(fixture, progress)?.learningItemId).toBe(repeated)
      progress = recordProbeAnswer(fixture, progress, repeated, value)
      expect(progress.probed.map((record) => record.item)).toEqual([repeated])
      expect(recordProbeAnswer(fixture, progress, repeated, value)).toBe(progress)

      for (let checkpoint = 2; checkpoint * P <= SIZE; checkpoint += 1) {
        progress = pressUntilSeen(fixture, progress, checkpoint * P)
        const pick = pickProbe(fixture, progress)
        expect(pick?.learningItemId).not.toBe(repeated)
        if (pick !== null) progress = recordProbeAnswer(fixture, progress, pick.learningItemId, 'skip')
      }
    },
  )

  it('keeps an unanswered probe as the candidate for the next checkpoint (W3-6)', () => {
    const fixture = fixtureOf()
    let progress = pressUntilSeen(fixture, initialProgress(fixture), P)
    const first = pickProbe(fixture, progress)
    expect(first).not.toBeNull()

    progress = pressUntilSeen(fixture, progress, 2 * P)
    expect(pickProbe(fixture, progress)).toEqual(first)
  })

  it('is not offered on a review sentence', () => {
    expect(P, 'this case needs a review that becomes due at a probe checkpoint').toBeGreaterThan(R)
    const fixture = fixtureOf()
    const reportedAt = P - R - 1
    let progress = pressNext(fixture, initialProgress(fixture), reportedAt).progress
    progress = recordSelfReport(fixture, progress, itemsOf(fixture, reportedAt)[0]!, 'unknown')

    progress = pressUntilSeen(fixture, progress, P)
    expect(nextView(fixture, progress)?.review).toBe(false)
    expect(pickProbe(fixture, progress)).not.toBeNull()

    progress = advance(fixture, progress)
    expect(nextView(fixture, progress)).toMatchObject({ index: reportedAt, review: true })
    expect(progress.seen).toBe(P)
    expect(pickProbe(fixture, progress)).toBeNull()
  })

  it.each(['unknown', 'uncertain'])(
    'queues the most recently seen sentence with that expression after a %s answer',
    (value) => {
      const probed = 9
      const fixture = fixtureOf({ 0: [probed], 2: [probed] })
      let progress = pressUntilSeen(fixture, initialProgress(fixture), P)
      expect(pickProbe(fixture, progress)).toEqual({ learningItemId: probed, sentenceIndex: 0 })

      progress = recordProbeAnswer(fixture, progress, probed, value)
      expect(progress.queue).toEqual([{ index: 2, due: P + R }])

      const { shown } = pressNext(fixture, progress, R + 1)
      expect(shown.at(-1)).toEqual({ index: 2, seen: P + R, review: true })
      expect(shown.slice(0, R).every((view) => !view.review)).toBe(true)
    },
  )

  it.each(['known', 'skip'])('queues nothing after a %s answer', (value) => {
    const fixture = fixtureOf({ 0: [9], 2: [9] })
    let progress = pressUntilSeen(fixture, initialProgress(fixture), P)
    progress = recordProbeAnswer(fixture, progress, 9, value)
    expect(progress.queue).toEqual([])
    expect(progress.probed).toEqual([{ item: 9, seen: P }])
  })

  it('does not fall back to an earlier sentence when the most recent one is already queued (W3-6)', () => {
    const probed = 9
    const other = 50
    const fixture = fixtureOf({ 0: [probed], 2: [probed, other] })
    let progress = pressNext(fixture, initialProgress(fixture), 2).progress
    progress = recordSelfReport(fixture, progress, other, 'unknown')
    const queuedOrReviewed = (p: DemoProgress): number[] => [...p.queue.map((entry) => entry.index), ...p.reviewed]
    expect(queuedOrReviewed(progress)).toEqual([2])

    progress = pressUntilSeen(fixture, progress, P)
    expect(pickProbe(fixture, progress)).toEqual({ learningItemId: probed, sentenceIndex: 0 })
    const answered = recordProbeAnswer(fixture, progress, probed, 'unknown')

    expect(queuedOrReviewed(answered)).toEqual(queuedOrReviewed(progress))
    expect(answered.queue).toEqual(progress.queue)
    expect(answered.probed).toEqual([{ item: probed, seen: P }])
  })
})

// ---------------------------------------------------------------------------------------------
// 상수 위치
// ---------------------------------------------------------------------------------------------

describe('demo constants', () => {
  it('are defined in demo/constants.ts only', () => {
    for (const name of ['DEMO_REVIEW_AFTER_SENTENCES', 'DEMO_PROBE_EVERY_SENTENCES']) {
      const definition = new RegExp(`\\b(?:const|let|var)\\s+${name}\\b`)
      const files = createProject().files.filter((file) => definition.test(readFileSync(join(SRC, file), 'utf8')))
      expect(files, name).toEqual(['demo/constants.ts'])
    }
  })
})

// ---------------------------------------------------------------------------------------------
// 저장값 검증 (isDemoProgress, 변이 검증 18)
// ---------------------------------------------------------------------------------------------

/** 지금 fixture 위의 유효한 진도. 자기평가·probe·대기열·다시 본 문장이 모두 차 있다. */
function busyProgress(): DemoProgress {
  const fixture = DEMO_FIXTURE
  let progress = initialProgress(fixture)
  progress = recordSelfReport(fixture, progress, itemsOf(fixture, 0)[0]!, 'unknown')
  progress = pressUntilSeen(fixture, progress, P)
  const pick = pickProbe(fixture, progress)
  expect(pick).not.toBeNull()
  progress = recordProbeAnswer(fixture, progress, pick!.learningItemId, 'skip')
  progress = recordSelfReport(fixture, progress, itemsOf(fixture, progress.position)[0]!, 'uncertain')

  expect(Object.keys(progress.selfReports)).toHaveLength(2)
  expect(progress.probed).toHaveLength(1)
  expect(progress.queue).toHaveLength(1)
  expect(progress.reviewed).toHaveLength(1)
  return progress
}

type Loose = Record<string, unknown> & {
  selfReports: Record<string, unknown>
  probed: Record<string, unknown>[]
  queue: Record<string, unknown>[]
  reviewed: unknown[]
}

function edited(edit: (value: Loose) => void): unknown {
  const value = JSON.parse(JSON.stringify(busyProgress())) as Loose
  edit(value)
  return value
}

describe('isDemoProgress', () => {
  const total = DEMO_SENTENCES.length
  const fixtureItems = DEMO_SENTENCES.flatMap((s) => s.presentation.tappable_items.map((t) => t.learning_item_id))
  const missingItem = Math.max(...fixtureItems) + 1

  it('accepts the first sentence, a busy progress, and the last sentence before completion', () => {
    expect(isDemoProgress(initialProgress(DEMO_FIXTURE))).toBe(true)
    expect(isDemoProgress(JSON.parse(JSON.stringify(busyProgress())))).toBe(true)
    const beforeEnd = { ...initialProgress(DEMO_FIXTURE), position: total - 1, seen: total }
    expect(isDemoProgress(beforeEnd)).toBe(true)
    expect(isDemoProgress(advance(DEMO_FIXTURE, beforeEnd))).toBe(true)
    expect(DEMO_FIXTURE.id).toBe(DEMO_FIXTURE_ID)
  })

  const REJECTED: [string, () => unknown][] = [
    ['null', () => null],
    ['an array', () => []],
    ['a string', () => DEMO_FIXTURE_ID],
    ['a number', () => 1],
    ['a missing key', () => edited((v) => delete (v as Record<string, unknown>).reviewed)],
    ['an extra key', () => edited((v) => (v.loggedIn = true))],
    ['another fixture id', () => edited((v) => (v.fixtureId = '0000000000000000'))],
    ['a numeric fixture id', () => edited((v) => (v.fixtureId = 1))],
    ['a negative position', () => edited((v) => (v.position = -1))],
    ['a fractional position', () => edited((v) => (v.position = 0.5))],
    ['a string position', () => edited((v) => (v.position = '0'))],
    ['a position past the fixture', () => edited((v) => (v.position = total + 1))],
    ['a position on a sentence not seen yet', () => edited((v) => (v.position = v.seen))],
    ['a negative seen count', () => edited((v) => (v.seen = -1))],
    ['a fractional seen count', () => edited((v) => (v.seen = 7.5))],
    ['a string seen count', () => edited((v) => (v.seen = String(v.seen)))],
    ['a seen count past the fixture', () => edited((v) => (v.seen = total + 1))],
    ['completion with sentences left unseen', () => edited((v) => ((v.position = total), (v.seen = total - 1), (v.queue = [])))],
    ['completion with a non-empty queue', () => edited((v) => ((v.position = total), (v.seen = total)))],
    ['a self-report for an expression not in the fixture', () => edited((v) => (v.selfReports[String(missingItem)] = 'known'))],
    ['a self-report value outside the allowed values', () => edited((v) => (v.selfReports[String(fixtureItems[0])] = 'skip'))],
    ['a non-string self-report value', () => edited((v) => (v.selfReports[String(fixtureItems[0])] = 1))],
    ['self-reports as an array', () => edited((v) => (v.selfReports = [] as unknown as Record<string, unknown>))],
    ['probed as an object', () => edited((v) => (v.probed = {} as unknown as Record<string, unknown>[]))],
    ['a probed expression not in the fixture', () => edited((v) => (v.probed[0]!.item = missingItem))],
    ['a probed expression as a string', () => edited((v) => (v.probed[0]!.item = String(v.probed[0]!.item)))],
    ['a probed record with an extra key', () => edited((v) => (v.probed[0]!.value = 'skip'))],
    ['a probed record without seen', () => edited((v) => delete v.probed[0]!.seen)],
    ['a probed record asked at seen 0', () => edited((v) => (v.probed[0]!.seen = 0))],
    ['a probed record asked after the seen count', () => edited((v) => (v.probed[0]!.seen = (v.seen as number) + 1))],
    ['the same expression probed twice', () => edited((v) => v.probed.push({ ...v.probed[0]! }))],
    ['a queue that is not an array', () => edited((v) => (v.queue = {} as unknown as Record<string, unknown>[]))],
    ['a queued sentence not seen yet', () => edited((v) => (v.queue[0]!.index = v.seen))],
    ['a queued sentence at a negative index', () => edited((v) => (v.queue[0]!.index = -1))],
    ['a queued sentence past the fixture', () => edited((v) => (v.queue[0]!.index = total))],
    ['the same sentence queued twice', () => edited((v) => v.queue.push({ ...v.queue[0]! }))],
    ['a negative due', () => edited((v) => (v.queue[0]!.due = -1))],
    ['a fractional due', () => edited((v) => (v.queue[0]!.due = 1.5))],
    ['a queue entry with an extra key', () => edited((v) => (v.queue[0]!.item = fixtureItems[0]))],
    ['reviewed that is not an array', () => edited((v) => (v.reviewed = {} as unknown as unknown[]))],
    ['a reviewed sentence not seen yet', () => edited((v) => (v.reviewed[0] = v.seen))],
    ['a reviewed sentence as a string', () => edited((v) => (v.reviewed[0] = String(v.reviewed[0])))],
    ['the same sentence reviewed twice', () => edited((v) => v.reviewed.push(v.reviewed[0]))],
    ['a sentence both queued and reviewed', () => edited((v) => v.reviewed.push(v.queue[0]!.index))],
  ]

  it.each(REJECTED)('rejects %s', (_name, make) => {
    expect(isDemoProgress(make())).toBe(false)
  })
})

// ---------------------------------------------------------------------------------------------
// 화면을 거치는 저장
// ---------------------------------------------------------------------------------------------

describe('progress on the demo screen', () => {
  const total = DEMO_SENTENCES.length
  const fetchMock = vi.fn(() => {
    throw new Error('the demo must not make requests')
  })

  beforeEach(() => {
    fetchMock.mockClear()
    vi.stubGlobal('document', fakeDocument())
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    expect(fetchMock).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  it('saves to nc.demo.v1 and continues after a reload, also in the middle of a review', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)

    const page = mountDemo(await freshDemo())
    const first = sentenceOnScreen(page.root)
    await selfReport(page.root, 0, '몰랐음')
    for (let i = 0; i < R; i += 1) next(page.root)
    expect(progressText(page.root)).toBe(progressLabel(R + 1, total))
    expect([...storage.data.keys()]).toEqual([DEMO_KEY])

    const stored = JSON.parse(storage.data.get(DEMO_KEY)!) as DemoProgress
    expect(Object.keys(stored).sort()).toEqual(['fixtureId', 'position', 'probed', 'queue', 'reviewed', 'seen', 'selfReports'])
    expect(stored.fixtureId).toBe(DEMO_FIXTURE_ID)

    // 새로고침: 같은 문장, 같은 진행 표시.
    const beforeReload = sentenceOnScreen(page.root)
    const reloaded = mountDemo(await freshDemo())
    expect(sentenceOnScreen(reloaded.root)).toBe(beforeReload)
    expect(progressText(reloaded.root)).toBe(progressLabel(R + 1, total))

    // 다시 보기 문장에서 새로고침해도 그 문장이다.
    next(reloaded.root)
    expect(sentenceOnScreen(reloaded.root)).toBe(first)
    expect(progressText(reloaded.root)).toBe(progressLabel(R + 1, total))
    const again = mountDemo(await freshDemo())
    expect(sentenceOnScreen(again.root)).toBe(first)
    expect(progressText(again.root)).toBe(progressLabel(R + 1, total))
  })

  it.each<[string, string]>([
    ['not JSON', '{'],
    ['another fixture id', JSON.stringify({ ...initialProgress(DEMO_FIXTURE), fixtureId: '0000000000000000', position: 3, seen: 4 })],
    ['a position past the fixture', JSON.stringify({ ...initialProgress(DEMO_FIXTURE), position: total + 1, seen: total })],
  ])('starts quietly from the first sentence when the stored value is %s', async (_name, raw) => {
    vi.stubGlobal('localStorage', memoryStorage({ [DEMO_KEY]: raw }))

    const page = mountDemo(await freshDemo())

    expect(sentenceOnScreen(page.root)).toBe(DEMO_SENTENCES[0]!.presentation.japanese)
    expect(progressText(page.root)).toBe(progressLabel(1, total))
    expect(byClass(page.root, 'notice')).toEqual([])
    expect(byClass(page.root, 'panel-failure')).toEqual([])
  })

  it('runs to the completion screen in memory when localStorage throws', async () => {
    vi.stubGlobal('localStorage', throwingStorage())
    const page = mountDemo(await freshDemo())

    const first = sentenceOnScreen(page.root)
    await selfReport(page.root, 0, '몰랐음')

    const shown = [first]
    let probes = 0
    for (let presses = 0; sentenceOnScreen(page.root) !== null; presses += 1) {
      expect(presses, 'the demo did not reach its completion screen').toBeLessThanOrEqual(2 * total)
      if (byClass(page.root, 'probe-option').length > 0) {
        await answerProbe(page.root, '건너뛰기')
        probes += 1
      }
      next(page.root)
      shown.push(sentenceOnScreen(page.root))
    }

    expect(flatTextOfTitle(page.root)).toBe(`${total}문장을 모두 봤어요.`)
    const sentences = shown.filter((s): s is string => s !== null)
    expect(new Set(sentences)).toEqual(new Set(DEMO_SENTENCES.map((s) => s.presentation.japanese)))
    // 첫 문장은 한 번 더(다시 보기) 나왔다. 메모리만으로 대기열이 이어졌다.
    expect(sentences.filter((s) => s === first)).toHaveLength(2)
    expect(sentences).toHaveLength(total + 1)
    expect(probes).toBeGreaterThan(0)
  })

  it('resets only the demo progress after the inline confirmation and keeps nc.furigana.v1', async () => {
    const furigana = JSON.stringify({ on: true })
    const kana = '{"items":{},"lastStudiedAt":1}'
    const storage = memoryStorage({ [FURIGANA_KEY]: furigana, [KANA_KEY]: kana })
    vi.stubGlobal('localStorage', storage)

    const page = mountDemo(await freshDemo())
    await selfReport(page.root, 0, '몰랐음')
    next(page.root)
    next(page.root)
    const saved = storage.data.get(DEMO_KEY)
    expect(saved).toBeDefined()

    // 취소하면 아무것도 바뀌지 않는다.
    press(page.root, '진도 초기화')
    press(page.root, '취소')
    expect(progressText(page.root)).toBe(progressLabel(3, total))
    expect(storage.data.get(DEMO_KEY)).toBe(saved)

    press(page.root, '진도 초기화')
    press(page.root, '초기화하기')

    expect(sentenceOnScreen(page.root)).toBe(DEMO_SENTENCES[0]!.presentation.japanese)
    expect(progressText(page.root)).toBe(progressLabel(1, total))
    expect(storage.data.has(DEMO_KEY)).toBe(false)
    expect(storage.data.get(FURIGANA_KEY)).toBe(furigana)
    expect(storage.data.get(KANA_KEY)).toBe(kana)
    expect(document.documentElement.classList.contains('furigana-on')).toBe(true)

    // 새로고침해도 처음부터다. 대기열도 없다: 첫 문장이 다시 보기로 끼어들지 않는다.
    const reloaded = mountDemo(await freshDemo())
    expect(progressText(reloaded.root)).toBe(progressLabel(1, total))
    for (let i = 0; i <= R; i += 1) next(reloaded.root)
    expect(sentenceOnScreen(reloaded.root)).toBe(DEMO_SENTENCES[R + 1]!.presentation.japanese)
  })

  it('reviews a flagged sentence exactly as an unflagged one', async () => {
    async function run(flag: boolean): Promise<{ shown: (string | null)[]; stored: string | undefined }> {
      const storage = memoryStorage()
      vi.stubGlobal('localStorage', storage)
      const page = mountDemo(await freshDemo())
      if (flag) {
        click(page.root, 'flag-open')
        click(page.root, 'flag-reason', 0)
        await flush()
        expect(byClass(page.root, 'flag-done')).toHaveLength(1)
      }
      await selfReport(page.root, 0, '몰랐음')
      const shown = [sentenceOnScreen(page.root)]
      for (let i = 0; i <= R; i += 1) {
        next(page.root)
        shown.push(sentenceOnScreen(page.root))
      }
      return { shown, stored: storage.data.get(DEMO_KEY) }
    }

    const plain = await run(false)
    const flagged = await run(true)

    expect(flagged).toEqual(plain)
    expect(flagged.shown.at(-1)).toBe(flagged.shown[0])
  })
})

function flatTextOfTitle(root: Parameters<typeof byClass>[0]): string | undefined {
  return root.children[0]?.querySelector('h1')?.textContent
}
