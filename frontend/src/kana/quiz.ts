/**
 * 가나 퀴즈 라운드와 보고 고르기 선택지(`03_UI_UX_SPEC.md`의 `가나 학습` > `퀴즈`, `라운드`).
 *
 * 스케줄링은 "틀린 문항을 라운드 끝에 한 번 더 묻기"까지다. SRS·간격 반복은 없다.
 * 난수는 주입한다. 테스트가 문항과 선택지를 고정할 수 있어야 한다.
 * 진도 저장은 이 모듈이 하지 않는다(`progress.ts`, 화면이 응답마다 기록한다).
 */
import type { KanaItem } from './data'

/** 한 라운드에서 처음 묻는 문항 수의 상한. */
export const KANA_ROUND_MAX_QUESTIONS = 10

/** 보고 고르기의 로마자 선택지 수. */
export const KANA_CHOICE_COUNT = 4

/** [0, 1) 균등 난수. 기본은 `Math.random`을 넘긴다. */
export type RandomSource = () => number

export type KanaQuestion = {
  readonly item: KanaItem
  /** 라운드 끝에 다시 묻는 문항이면 true. */
  readonly retry: boolean
}

export type KanaRoundResult = {
  /** 처음 물은 문항 수(다시 묻는 문항 제외). */
  readonly total: number
  /** 처음에 바로 맞힌 수. */
  readonly firstTryCorrect: number
  /** 한 번 더 풀어 본 글자·단어. */
  readonly retried: readonly KanaItem[]
}

export type KanaRound = {
  /** 지금 물을 문항. 라운드가 끝났으면 undefined. */
  current: () => KanaQuestion | undefined
  /** 지금 문항의 응답. 처음 틀린 문항이면 끝에 다시 넣고 true를 돌려준다. */
  answer: (correct: boolean) => { willRetry: boolean }
  /** 지금까지 쌓인 문항 수(다시 묻는 문항 포함). 진행 표시용. */
  length: () => number
  position: () => number
  result: () => KanaRoundResult
}

function shuffle<T>(list: readonly T[], random: RandomSource): T[] {
  const copy = [...list]
  for (let index = copy.length - 1; index > 0; index -= 1) {
    const swap = Math.floor(random() * (index + 1))
    ;[copy[index], copy[swap]] = [copy[swap]!, copy[index]!]
  }
  return copy
}

/** `pool`은 지금 고른 문자 체계·범위의 문항 전체다. */
export function createKanaRound(pool: readonly KanaItem[], random: RandomSource): KanaRound {
  const questions: KanaQuestion[] = shuffle(pool, random)
    .slice(0, KANA_ROUND_MAX_QUESTIONS)
    .map((item) => ({ item, retry: false }))
  const total = questions.length
  const retried: KanaItem[] = []
  let position = 0
  let firstTryCorrect = 0

  return {
    current: () => questions[position],
    answer(correct) {
      const question = questions[position]
      if (question === undefined) throw new Error('kana round is already finished')
      position += 1
      if (question.retry) return { willRetry: false }
      if (correct) {
        firstTryCorrect += 1
        return { willRetry: false }
      }
      questions.push({ item: question.item, retry: true })
      retried.push(question.item)
      return { willRetry: true }
    },
    length: () => questions.length,
    position: () => position,
    result: () => ({ total, firstTryCorrect, retried: [...retried] }),
  }
}

/**
 * 보고 고르기의 로마자 선택지. 정답 하나와 같은 범위(`pool`)의 오답으로 채우고 섞는다.
 * 정답과 로마자가 같은 항목(ぢ/じ, づ/ず, を/お)은 오답이 될 수 없고, 오답끼리도 로마자가 겹치지 않는다.
 */
export function createKanaChoices(item: KanaItem, pool: readonly KanaItem[], random: RandomSource): string[] {
  const distractors = [...new Set(pool.map((candidate) => candidate.romaji))].filter(
    (romaji) => romaji !== item.romaji,
  )
  if (distractors.length < KANA_CHOICE_COUNT - 1) {
    throw new Error(`not enough distinct romaji for choices of ${item.key}`)
  }
  const picked = shuffle(distractors, random).slice(0, KANA_CHOICE_COUNT - 1)
  return shuffle([item.romaji, ...picked], random)
}
