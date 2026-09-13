/**
 * 가나 퀴즈 로직(`12_TEST_PLAN.md`의 `가나 학습` > 보고 고르기·라운드, 합격 기준 32·33).
 * 문항 수 상한과 선택지 수는 상수를 참조한다.
 */
import { describe, expect, it } from 'vitest'

import { KANA_ITEMS, KANA_RANGES, KANA_SCRIPTS, type KanaItem } from '../../src/kana/data'
import {
  KANA_CHOICE_COUNT,
  KANA_ROUND_MAX_QUESTIONS,
  createKanaChoices,
  createKanaRound,
  type KanaRound,
} from '../../src/kana/quiz'

/** 결정적 난수(mulberry32). */
function seeded(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6d2b79f5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function find(pool: readonly KanaItem[], text: string): KanaItem {
  return pool.find((item) => item.text === text)!
}

/** 라운드를 끝까지 풀고 물은 문항 순서를 돌려준다. */
function play(round: KanaRound, isCorrect: (text: string, retry: boolean) => boolean) {
  const asked: { text: string; retry: boolean }[] = []
  for (let question = round.current(); question !== undefined; question = round.current()) {
    asked.push({ text: question.item.text, retry: question.retry })
    round.answer(isCorrect(question.item.text, question.retry))
  }
  return asked
}

describe('constants', () => {
  it('match 03_UI_UX_SPEC.md', () => {
    expect(KANA_ROUND_MAX_QUESTIONS).toBe(10)
    expect(KANA_CHOICE_COUNT).toBe(4)
  })
})

describe('createKanaChoices', () => {
  it('gives distinct romaji with exactly one correct answer from the same range, for every item', () => {
    for (const script of KANA_SCRIPTS) {
      for (const range of KANA_RANGES) {
        const pool = KANA_ITEMS[script][range]
        const poolRomaji = new Set(pool.map((item) => item.romaji))
        for (const item of pool) {
          const choices = createKanaChoices(item, pool, seeded(item.text.codePointAt(0)!))
          expect(choices).toHaveLength(KANA_CHOICE_COUNT)
          expect(new Set(choices).size).toBe(KANA_CHOICE_COUNT)
          expect(choices.filter((romaji) => romaji === item.romaji)).toHaveLength(1)
          for (const romaji of choices) expect(poolRomaji.has(romaji)).toBe(true)
        }
      }
    }
  })

  it('never offers a same-romaji twin as a wrong answer', () => {
    const dakuon = KANA_ITEMS.hiragana.dakuon
    const seion = KANA_ITEMS.hiragana.seion
    const cases: [readonly KanaItem[], string][] = [
      [dakuon, 'ぢ'],
      [dakuon, 'じ'],
      [dakuon, 'づ'],
      [dakuon, 'ず'],
      [seion, 'を'],
      [seion, 'お'],
    ]
    for (const [pool, text] of cases) {
      const item = find(pool, text)
      for (let seed = 0; seed < 200; seed += 1) {
        const choices = createKanaChoices(item, pool, seeded(seed))
        expect(choices.filter((romaji) => romaji === item.romaji)).toHaveLength(1)
        expect(new Set(choices).size).toBe(KANA_CHOICE_COUNT)
      }
    }
  })

  it('does not duplicate romaji among wrong answers when the pool has twins', () => {
    // あ의 오답 후보에 お(o)와 を(o)가 함께 있다.
    const seion = KANA_ITEMS.hiragana.seion
    for (let seed = 0; seed < 200; seed += 1) {
      const choices = createKanaChoices(find(seion, 'あ'), seion, seeded(seed))
      expect(new Set(choices).size).toBe(KANA_CHOICE_COUNT)
    }
  })

  it('is fixed by the injected random source', () => {
    const pool = KANA_ITEMS.katakana.gairaigo
    const item = pool[0]!
    expect(createKanaChoices(item, pool, seeded(7))).toEqual(createKanaChoices(item, pool, seeded(7)))
  })

  it('places the correct answer at different positions depending on random', () => {
    const pool = KANA_ITEMS.hiragana.seion
    const item = find(pool, 'か')
    const positions = new Set<number>()
    for (let seed = 0; seed < 50; seed += 1) {
      positions.add(createKanaChoices(item, pool, seeded(seed)).indexOf('ka'))
    }
    expect(positions.size).toBe(KANA_CHOICE_COUNT)
  })
})

describe('createKanaRound', () => {
  it('asks at most the round limit, all distinct, from the pool', () => {
    for (const script of KANA_SCRIPTS) {
      for (const range of KANA_RANGES) {
        const pool = KANA_ITEMS[script][range]
        const round = createKanaRound(pool, seeded(1))
        const asked = play(round, () => true)
        expect(asked.length).toBe(Math.min(KANA_ROUND_MAX_QUESTIONS, pool.length))
        expect(new Set(asked.map((q) => q.text)).size).toBe(asked.length)
        for (const q of asked) expect(pool.some((item) => item.text === q.text)).toBe(true)
      }
    }
  })

  it('uses a smaller pool entirely when it has fewer items than the limit', () => {
    const pool = KANA_ITEMS.hiragana.handakuon
    expect(pool.length).toBeLessThan(KANA_ROUND_MAX_QUESTIONS)
    const asked = play(createKanaRound(pool, seeded(3)), () => true)
    expect(asked.map((q) => q.text).sort()).toEqual(pool.map((item) => item.text).sort())
  })

  it('is fixed by the injected random source', () => {
    const pool = KANA_ITEMS.hiragana.seion
    const first = play(createKanaRound(pool, seeded(42)), () => true)
    const second = play(createKanaRound(pool, seeded(42)), () => true)
    expect(first).toEqual(second)
  })

  it('asks a missed question once more at the end, and never a third time', () => {
    const pool = KANA_ITEMS.hiragana.seion
    const round = createKanaRound(pool, seeded(5))
    const firstPass = round.length()
    expect(firstPass).toBe(KANA_ROUND_MAX_QUESTIONS)

    let missed: string[] = []
    const asked = play(round, (text, retry) => {
      if (retry) return false // 다시 나온 문항도 틀린다
      const wrong = missed.length < 3
      if (wrong) missed = [...missed, text]
      return !wrong
    })

    expect(asked).toHaveLength(firstPass + 3)
    expect(asked.slice(0, firstPass).every((q) => !q.retry)).toBe(true)
    expect(asked.slice(firstPass)).toEqual(missed.map((text) => ({ text, retry: true })))
    expect(round.current()).toBeUndefined()
  })

  it('reports whether the answer will come back', () => {
    const round = createKanaRound(KANA_ITEMS.katakana.choon, seeded(9))
    expect(round.answer(false)).toEqual({ willRetry: true })
    expect(round.answer(true)).toEqual({ willRetry: false })
    while (round.current()?.retry === false) round.answer(true)
    expect(round.current()?.retry).toBe(true)
    expect(round.answer(false)).toEqual({ willRetry: false })
    expect(round.current()).toBeUndefined()
  })

  it('result counts only first-try correct answers', () => {
    const pool = KANA_ITEMS.hiragana.yoon
    const round = createKanaRound(pool, seeded(11))
    let index = 0
    // 처음 10문항 중 짝수 번째만 맞히고, 다시 나온 문항은 전부 맞힌다.
    play(round, (_text, retry) => {
      if (retry) return true
      const correct = index % 2 === 0
      index += 1
      return correct
    })

    const result = round.result()
    expect(result.total).toBe(KANA_ROUND_MAX_QUESTIONS)
    expect(result.firstTryCorrect).toBe(KANA_ROUND_MAX_QUESTIONS / 2)
    expect(result.retried).toHaveLength(KANA_ROUND_MAX_QUESTIONS / 2)
  })

  it('throws when answering after the round has finished', () => {
    const round = createKanaRound(KANA_ITEMS.hiragana.handakuon, seeded(2))
    play(round, () => true)
    expect(() => round.answer(true)).toThrow()
  })
})
