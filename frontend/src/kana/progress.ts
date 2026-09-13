/**
 * 가나 진도(`nc.kana.v1`). 글자·단어별 맞음/틀림 수와 전체 마지막 학습 시각
 * (`03_UI_UX_SPEC.md`의 `가나 학습` > `진도 저장`, `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`).
 *
 * 서버로 보내지 않고 학습 신호가 아니다. 라운드 끝에 다시 묻는 문항의 응답도 센다.
 * 형식·값 범위·소속이 맞지 않는 저장값은 조용히 없는 것으로 본다.
 */
import { localSlot } from '../local-store'
import { KANA_ITEM_KEYS } from './data'

export type KanaItemProgress = {
  readonly correct: number
  readonly wrong: number
}

export type KanaProgress = {
  /** key는 `KanaItem.key`. */
  readonly items: Readonly<Record<string, KanaItemProgress>>
  /** 마지막으로 응답한 시각(ms). */
  readonly lastStudiedAt: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const own = Object.keys(value)
  return own.length === keys.length && keys.every((key) => Object.hasOwn(value, key))
}

function isCount(value: unknown): boolean {
  return Number.isSafeInteger(value) && (value as number) >= 0
}

function isKanaProgress(value: unknown): value is KanaProgress {
  if (!isRecord(value) || !hasExactKeys(value, ['items', 'lastStudiedAt'])) return false
  if (typeof value.lastStudiedAt !== 'number' || !Number.isFinite(value.lastStudiedAt)) return false
  if (!isRecord(value.items)) return false
  return Object.entries(value.items).every(
    ([key, entry]) =>
      KANA_ITEM_KEYS.has(key) &&
      isRecord(entry) &&
      hasExactKeys(entry, ['correct', 'wrong']) &&
      isCount(entry.correct) &&
      isCount(entry.wrong),
  )
}

const slot = localSlot('nc.kana.v1', isKanaProgress)

/** 기록이 없거나 저장값이 맞지 않으면 undefined. */
export function readKanaProgress(): KanaProgress | undefined {
  return slot.read()
}

/** 응답 하나를 센다. `now`는 호출자가 넘긴다. */
export function recordKanaAnswer(key: string, correct: boolean, now: number): void {
  const previous = slot.read()
  const entry = previous?.items[key] ?? { correct: 0, wrong: 0 }
  slot.write({
    items: {
      ...previous?.items,
      [key]: correct ? { ...entry, correct: entry.correct + 1 } : { ...entry, wrong: entry.wrong + 1 },
    },
    lastStudiedAt: now,
  })
}

/** 진도 초기화. 가나 진도만 지운다. */
export function resetKanaProgress(): void {
  slot.remove()
}
