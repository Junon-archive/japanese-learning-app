/**
 * 가나 진도 저장(`12_TEST_PLAN.md`의 `가나 학습` > 진도 저장, `localStorage` > 값 범위, 합격 기준 34).
 *
 * `progress.ts`는 import 시점에 `localSlot('nc.kana.v1')`을 만들고 `local-store.ts`는 같은 key를 두 번
 * 만들면 던진다. 그래서 테스트마다 모듈을 새로 불러온다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { KANA_ITEMS } from '../../src/kana/data'
import { createKanaRound } from '../../src/kana/quiz'

type ProgressModule = typeof import('../../src/kana/progress')

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
  const fail = () => {
    throw new DOMException('quota', 'QuotaExceededError')
  }
  return { getItem: vi.fn(fail), setItem: vi.fn(fail), removeItem: vi.fn(fail) }
}

async function freshProgress(): Promise<ProgressModule> {
  vi.resetModules()
  return import('../../src/kana/progress')
}

function seeded(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0
    return state / 4294967296
  }
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('recordKanaAnswer', () => {
  it('counts correct and wrong per item and stores the last study time in nc.kana.v1', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    const { readKanaProgress, recordKanaAnswer } = await freshProgress()

    expect(readKanaProgress()).toBeUndefined()
    recordKanaAnswer('あ', true, 1000)
    recordKanaAnswer('あ', false, 2000)
    recordKanaAnswer('コーヒー', true, 3000)

    const expected = {
      items: { あ: { correct: 1, wrong: 1 }, コーヒー: { correct: 1, wrong: 0 } },
      lastStudiedAt: 3000,
    }
    expect(readKanaProgress()).toEqual(expected)
    expect(JSON.parse(storage.data.get('nc.kana.v1')!)).toEqual(expected)
    expect([...storage.data.keys()]).toEqual(['nc.kana.v1'])
  })

  it('continues from a valid stored value', async () => {
    vi.stubGlobal(
      'localStorage',
      memoryStorage({ 'nc.kana.v1': '{"items":{"か":{"correct":2,"wrong":3}},"lastStudiedAt":5}' }),
    )
    const { readKanaProgress, recordKanaAnswer } = await freshProgress()
    recordKanaAnswer('か', false, 10)
    expect(readKanaProgress()).toEqual({ items: { か: { correct: 2, wrong: 4 } }, lastStudiedAt: 10 })
  })

  it('counts every answer of a round including retried questions', async () => {
    vi.stubGlobal('localStorage', memoryStorage())
    const { readKanaProgress, recordKanaAnswer } = await freshProgress()
    const round = createKanaRound(KANA_ITEMS.katakana.gairaigo, seeded(4))

    let answers = 0
    let now = 0
    for (let question = round.current(); question !== undefined; question = round.current()) {
      const correct = question.retry // 처음엔 전부 틀리고 다시 나오면 맞힌다
      recordKanaAnswer(question.item.key, correct, (now += 1))
      round.answer(correct)
      answers += 1
    }

    const progress = readKanaProgress()!
    const entries = Object.values(progress.items)
    expect(answers).toBe(2 * round.result().total)
    expect(entries.reduce((sum, entry) => sum + entry.correct + entry.wrong, 0)).toBe(answers)
    for (const entry of entries) expect(entry).toEqual({ correct: 1, wrong: 1 })
    expect(progress.lastStudiedAt).toBe(now)
    expect(round.result().firstTryCorrect).toBe(0)
  })
})

describe('without usable storage', () => {
  it('finishes a round with a throwing localStorage and keeps progress in memory', async () => {
    const storage = throwingStorage()
    vi.stubGlobal('localStorage', storage)
    const { readKanaProgress, recordKanaAnswer, resetKanaProgress } = await freshProgress()
    const round = createKanaRound(KANA_ITEMS.hiragana.seion, seeded(8))

    let answers = 0
    expect(() => {
      for (let question = round.current(); question !== undefined; question = round.current()) {
        const correct = answers % 3 !== 0
        recordKanaAnswer(question.item.key, correct, 100 + answers)
        round.answer(correct)
        answers += 1
      }
    }).not.toThrow()

    expect(round.current()).toBeUndefined()
    expect(storage.setItem).toHaveBeenCalled()
    const progress = readKanaProgress()!
    expect(Object.values(progress.items).reduce((sum, e) => sum + e.correct + e.wrong, 0)).toBe(answers)
    expect(() => resetKanaProgress()).not.toThrow()
    expect(readKanaProgress()).toBeUndefined()
  })
})

describe('stored value validation', () => {
  const invalid: [string, string][] = [
    ['not JSON', '{items:'],
    ['null', 'null'],
    ['array', '[]'],
    ['missing lastStudiedAt', '{"items":{}}'],
    ['extra top-level key', '{"items":{},"lastStudiedAt":1,"loginId":"x"}'],
    ['items is an array', '{"items":[],"lastStudiedAt":1}'],
    ['unknown character key', '{"items":{"x":{"correct":1,"wrong":0}},"lastStudiedAt":1}'],
    ['negative count', '{"items":{"あ":{"correct":-1,"wrong":0}},"lastStudiedAt":1}'],
    ['fractional count', '{"items":{"あ":{"correct":1.5,"wrong":0}},"lastStudiedAt":1}'],
    ['unsafe integer count', '{"items":{"あ":{"correct":9007199254740992,"wrong":0}},"lastStudiedAt":1}'],
    ['string count', '{"items":{"あ":{"correct":"1","wrong":0}},"lastStudiedAt":1}'],
    ['missing wrong', '{"items":{"あ":{"correct":1}},"lastStudiedAt":1}'],
    ['extra item key', '{"items":{"あ":{"correct":1,"wrong":0,"last":1}},"lastStudiedAt":1}'],
    ['non-finite time', '{"items":{},"lastStudiedAt":1e999}'],
    ['string time', '{"items":{},"lastStudiedAt":"1"}'],
  ]

  it.each(invalid)('treats %s as no progress and starts over silently', async (_name, raw) => {
    vi.stubGlobal('localStorage', memoryStorage({ 'nc.kana.v1': raw }))
    const { readKanaProgress, recordKanaAnswer } = await freshProgress()

    expect(readKanaProgress()).toBeUndefined()
    recordKanaAnswer('あ', true, 7)
    expect(readKanaProgress()).toEqual({ items: { あ: { correct: 1, wrong: 0 } }, lastStudiedAt: 7 })
  })

  it('accepts an empty item map and zero counts', async () => {
    vi.stubGlobal(
      'localStorage',
      memoryStorage({ 'nc.kana.v1': '{"items":{"ヲ":{"correct":0,"wrong":0}},"lastStudiedAt":0}' }),
    )
    const { readKanaProgress } = await freshProgress()
    expect(readKanaProgress()).toEqual({ items: { ヲ: { correct: 0, wrong: 0 } }, lastStudiedAt: 0 })
  })

  it('does not store an answer for a key that is not in the kana data', async () => {
    const storage = memoryStorage()
    vi.stubGlobal('localStorage', storage)
    const { readKanaProgress, recordKanaAnswer } = await freshProgress()
    recordKanaAnswer('あ', true, 1)
    recordKanaAnswer('login_id', true, 2)
    expect(readKanaProgress()).toEqual({ items: { あ: { correct: 1, wrong: 0 } }, lastStudiedAt: 1 })
    expect(storage.data.get('nc.kana.v1')).not.toContain('login_id')
  })
})

describe('resetKanaProgress', () => {
  it('removes only the kana progress', async () => {
    const storage = memoryStorage({
      'nc.furigana.v1': '{"on":true}',
      'nc.demo.v1': '{"fixture":"abc"}',
    })
    vi.stubGlobal('localStorage', storage)
    const { readKanaProgress, recordKanaAnswer, resetKanaProgress } = await freshProgress()

    recordKanaAnswer('ん', false, 50)
    expect(storage.data.has('nc.kana.v1')).toBe(true)
    resetKanaProgress()

    expect(readKanaProgress()).toBeUndefined()
    expect(storage.data.has('nc.kana.v1')).toBe(false)
    expect(storage.data.get('nc.furigana.v1')).toBe('{"on":true}')
    expect(storage.data.get('nc.demo.v1')).toBe('{"fixture":"abc"}')
  })
})
