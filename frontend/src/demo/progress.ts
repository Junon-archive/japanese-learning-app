/**
 * demo 진행 규칙(`03_UI_UX_SPEC.md`의 `Demo` > `진행 규칙`)과 진도 저장. **진행 규칙은 순수 함수다.**
 *
 * 프론트엔드의 단순 규칙이다. Learning Engine, FSRS, mastery, context stage를 복제하지 않는다(불변식 20).
 * 쓰는 것은 `constants.ts`의 두 상수와 순번(본 문장 수)뿐이다. 값은 바꾸지 않고 새 값을 돌려준다.
 *
 * -   "표현"은 learning item이다. 자기평가의 key는 `learning_item_id`다.
 * -   문장은 fixture 안의 순번(index)으로 가리킨다. 값 안의 fixture 식별자가 같을 때만 그 순번이 뜻을 가진다.
 *
 * 진도 저장(`nc.demo.v1`)도 이 모듈이 맡는다(`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`). 서버로
 * 보내지 않고 로그인 여부·계정 값을 넣지 않는다. 형식·값 범위·소속이 맞지 않는 저장값은 조용히 없는 것으로 본다.
 */
import { localSlot } from '../local-store'
import type { ExplicitSignal } from '../types'
import { DEMO_PROBE_EVERY_SENTENCES, DEMO_REVIEW_AFTER_SENTENCES } from './constants'
import type { DemoSentence } from './fixture'
import { DEMO_FIXTURE_ID, DEMO_SENTENCES } from './fixture'

export type DemoFixture = {
  readonly id: string
  readonly sentences: readonly DemoSentence[]
}

export type DemoReviewEntry = {
  /** 다시 보여줄 문장의 fixture 순번. */
  readonly index: number
  /** `seen`이 이 값에 닿으면 보여준다. */
  readonly due: number
}

export type DemoProbeRecord = {
  readonly item: number
  /** 물었을 때의 `seen`. 같은 체크포인트에서 두 번 묻지 않기 위해 둔다. */
  readonly seen: number
}

export type DemoProgress = {
  readonly fixtureId: string
  /** 화면에 있는 문장의 fixture 순번. 문장 수와 같으면 완료 화면이다. */
  readonly position: number
  /** 본 문장 수. 새 문장은 fixture 순서로 나오므로 순번 0..seen-1이 본 문장이다. 다시 보기는 더하지 않는다. */
  readonly seen: number
  /** `learning_item_id` -> 마지막 자기평가 값. */
  readonly selfReports: Readonly<Record<string, ExplicitSignal>>
  /** probe로 물은(응답한) 표현. */
  readonly probed: readonly DemoProbeRecord[]
  /** 다시 보기 대기열. 넣은 순서다. */
  readonly queue: readonly DemoReviewEntry[]
  /** 다시 보기로 이미 보여준 문장. 한 문장은 다시 보기에 한 번까지만 들어간다. */
  readonly reviewed: readonly number[]
}

export type DemoView = {
  readonly index: number
  readonly sentence: DemoSentence
  /** 다시 보기로 다시 보여주는 문장인가. */
  readonly review: boolean
}

export type DemoProbePick = {
  readonly learningItemId: number
  /** 그 표현이 처음 나온(먼저 본) 문장의 순번. */
  readonly sentenceIndex: number
}

/** 첫 문장을 보여주는 진도. 문장이 없으면 곧바로 완료다. */
export function initialProgress(fixture: DemoFixture): DemoProgress {
  const empty = fixture.sentences.length === 0
  return {
    fixtureId: fixture.id,
    position: 0,
    seen: empty ? 0 : 1,
    selfReports: {},
    probed: [],
    queue: [],
    reviewed: [],
  }
}

export function isComplete(fixture: DemoFixture, progress: DemoProgress): boolean {
  return progress.position === fixture.sentences.length
}

/** 지금 보여줄 문장. 완료면 null. */
export function nextView(fixture: DemoFixture, progress: DemoProgress): DemoView | null {
  const sentence = fixture.sentences[progress.position]
  if (sentence === undefined) return null
  return { index: progress.position, sentence, review: progress.reviewed.includes(progress.position) }
}

/**
 * `다음 문장`. 순서: 때가 된 다시 보기 -> 다음 새 문장 -> (새 문장이 끝났으면) 대기열 순서대로 -> 완료.
 */
export function advance(fixture: DemoFixture, progress: DemoProgress): DemoProgress {
  const total = fixture.sentences.length
  if (progress.position === total) return progress

  const due = progress.queue.findIndex((entry) => entry.due <= progress.seen)
  if (due >= 0) return showReview(progress, due)
  if (progress.seen < total) return { ...progress, position: progress.seen, seen: progress.seen + 1 }
  if (progress.queue.length > 0) return showReview(progress, 0)
  return { ...progress, position: total }
}

function showReview(progress: DemoProgress, queueIndex: number): DemoProgress {
  const entry = progress.queue[queueIndex]!
  return {
    ...progress,
    position: entry.index,
    queue: progress.queue.filter((_, i) => i !== queueIndex),
    reviewed: [...progress.reviewed, entry.index],
  }
}

/** 문장을 대기열에 넣는다. 이미 들어갔거나 다시 보기로 보여준 문장이면 그대로다. */
function enqueue(progress: DemoProgress, index: number): DemoProgress {
  if (progress.reviewed.includes(index) || progress.queue.some((entry) => entry.index === index)) {
    return progress
  }
  return {
    ...progress,
    queue: [...progress.queue, { index, due: progress.seen + DEMO_REVIEW_AFTER_SENTENCES }],
  }
}

/** 화면에 있는 문장의 표현에 자기평가를 남긴다. 같은 표현의 앞선 값은 덮어쓴다. */
export function recordSelfReport(
  fixture: DemoFixture,
  progress: DemoProgress,
  learningItemId: number,
  value: ExplicitSignal,
): DemoProgress {
  if (isComplete(fixture, progress)) return progress
  const next = { ...progress, selfReports: { ...progress.selfReports, [String(learningItemId)]: value } }
  return value === 'known' ? next : enqueue(next, progress.position)
}

/**
 * probe 응답(건너뛰기 포함)을 "물었음"으로 기록한다. "몰랐음/애매함"이면 그 표현이 나온 문장 중 가장 최근에 본
 * 문장(본 문장 중 순번이 가장 큰 것)을 대기열에 넣는다.
 */
export function recordProbeAnswer(
  fixture: DemoFixture,
  progress: DemoProgress,
  learningItemId: number,
  value: string,
): DemoProgress {
  if (progress.probed.some((record) => record.item === learningItemId)) return progress
  const next = { ...progress, probed: [...progress.probed, { item: learningItemId, seen: progress.seen }] }
  if (value !== 'unknown' && value !== 'uncertain') return next

  for (let index = Math.min(progress.seen, fixture.sentences.length) - 1; index >= 0; index -= 1) {
    if (hasItem(fixture.sentences[index]!, learningItemId)) return enqueue(next, index)
  }
  return next
}

/**
 * 지금 화면에 붙일 probe. 본 문장 수가 `DEMO_PROBE_EVERY_SENTENCES`의 배수가 된 새 문장에서만, 그 체크포인트에서
 * 아직 묻지 않았을 때 고른다. 후보는 앞에서 본 문장의 표현 중 자기평가하지 않았고 묻지 않은 것, 먼저 본 순서다.
 */
export function pickProbe(fixture: DemoFixture, progress: DemoProgress): DemoProbePick | null {
  const view = nextView(fixture, progress)
  if (view === null || view.review || view.index !== progress.seen - 1) return null
  if (progress.seen % DEMO_PROBE_EVERY_SENTENCES !== 0) return null
  if (progress.probed.some((record) => record.seen === progress.seen)) return null

  const probed = new Set(progress.probed.map((record) => record.item))
  for (let index = 0; index < view.index; index += 1) {
    for (const item of fixture.sentences[index]!.presentation.tappable_items) {
      const id = item.learning_item_id
      if (Object.hasOwn(progress.selfReports, String(id)) || probed.has(id)) continue
      return { learningItemId: id, sentenceIndex: index }
    }
  }
  return null
}

function hasItem(sentence: DemoSentence, learningItemId: number): boolean {
  return sentence.presentation.tappable_items.some((item) => item.learning_item_id === learningItemId)
}

// ----------------------------------------------------------------------
// 저장 (`nc.demo.v1`)
// ----------------------------------------------------------------------

/** 지금 번들에 들어 있는 fixture. */
export const DEMO_FIXTURE: DemoFixture = { id: DEMO_FIXTURE_ID, sentences: DEMO_SENTENCES }

const PROGRESS_KEYS = ['fixtureId', 'position', 'seen', 'selfReports', 'probed', 'queue', 'reviewed']
const SELF_REPORT_VALUES: readonly string[] = ['known', 'uncertain', 'unknown']

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const own = Object.keys(value)
  return own.length === keys.length && keys.every((key) => Object.hasOwn(value, key))
}

function isIntIn(value: unknown, min: number, max: number): value is number {
  return Number.isSafeInteger(value) && (value as number) >= min && (value as number) <= max
}

function isDistinct(values: readonly unknown[]): boolean {
  return new Set(values).size === values.length
}

/**
 * 형식, 값 범위, 소속을 본다: fixture 식별자가 같고, 위치·본 문장 수가 문장 수 안이며 서로 맞고, 자기평가·probe가
 * 가리키는 표현이 fixture에 있고, 대기열·다시 본 문장이 본 문장이며 중복이 없다. 다른 키는 없다.
 */
function isProgressOf(fixture: DemoFixture, value: unknown): value is DemoProgress {
  if (!isRecord(value) || !hasExactKeys(value, PROGRESS_KEYS)) return false
  if (value.fixtureId !== fixture.id) return false

  const total = fixture.sentences.length
  const { position, seen } = value
  if (!isIntIn(seen, 0, total) || !isIntIn(position, 0, total)) return false

  const { selfReports, probed, queue, reviewed } = value
  if (!Array.isArray(queue) || !Array.isArray(reviewed) || !Array.isArray(probed) || !isRecord(selfReports)) {
    return false
  }
  // 완료면 모든 문장을 봤고 대기열이 비었다. 아니면 화면의 문장은 본 문장 중 하나다.
  if (position === total ? seen !== total || queue.length > 0 : position >= seen) return false

  const items = new Set(
    fixture.sentences.flatMap((sentence) => sentence.presentation.tappable_items.map((item) => String(item.learning_item_id))),
  )
  // 원소마다 fixture 문장·표현을 가리키고 중복이 없으므로 길이 상한은 규칙을 좁히지 않는다. 조작된 거대 배열을
  // 원소 검사 전에 거른다. 아래 검사는 거짓이 나오는 즉시 끝나고 모두 선형 시간이다.
  if (queue.length > total || reviewed.length > total || probed.length > items.size) return false

  const reportsValid = Object.entries(selfReports).every(
    ([key, report]) => items.has(key) && typeof report === 'string' && SELF_REPORT_VALUES.includes(report),
  )
  if (!reportsValid) return false

  const probedValid =
    probed.every(
      (record) =>
        isRecord(record) &&
        hasExactKeys(record, ['item', 'seen']) &&
        Number.isSafeInteger(record.item) &&
        items.has(String(record.item)) &&
        isIntIn(record.seen, 1, seen),
    ) && isDistinct(probed.map((record: { item: unknown }) => record.item))
  if (!probedValid) return false

  const queueValid =
    queue.every(
      (entry) =>
        isRecord(entry) &&
        hasExactKeys(entry, ['index', 'due']) &&
        isIntIn(entry.index, 0, seen - 1) &&
        Number.isSafeInteger(entry.due) &&
        (entry.due as number) >= 0,
    ) && isDistinct(queue.map((entry: { index: unknown }) => entry.index))
  if (!queueValid) return false

  if (!reviewed.every((index) => isIntIn(index, 0, seen - 1)) || !isDistinct(reviewed)) return false

  const reviewedSet = new Set<unknown>(reviewed)
  return !queue.some((entry: { index: unknown }) => reviewedSet.has(entry.index))
}

/** 지금 fixture의 진도인가(`localSlot`의 isValid). */
export function isDemoProgress(value: unknown): value is DemoProgress {
  return isProgressOf(DEMO_FIXTURE, value)
}

const slot = localSlot('nc.demo.v1', isDemoProgress)

/** 저장된 진도. 없거나, 읽을 수 없거나, 다른 fixture의 값이거나, 형식이 맞지 않으면 undefined. */
export function readDemoProgress(): DemoProgress | undefined {
  return slot.read()
}

/** 저장을 시도한다. 저장할 수 없어도 이 페이지 안에서는 이어진다. 던지지 않는다. */
export function writeDemoProgress(progress: DemoProgress): void {
  slot.write(progress)
}

/** 진도 초기화. demo 진도만 지운다. */
export function resetDemoProgress(): void {
  slot.remove()
}
