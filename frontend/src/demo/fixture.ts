/**
 * Public Demo의 **전부**. static fixture다.
 *
 * `04_SECURITY_AND_DATA.md`와 `05_API_SPEC.md`가 불변식으로 둔 것: **demo는 backend
 * API를 호출하지 않고 demo 전용 endpoint·DB·provider도 없다.** 그래서 "서버가 줄 값"을
 * 여기 적어 두고, demo 화면은 그것만 읽는다. 이 파일에 fetch도 import되는 API client도
 * 없다.
 *
 * 모양은 **API payload와 같다**(`src/types.ts`). 그래야 같은 렌더러가 demo와 실제 학습
 * 화면에서 똑같이 동작한다.
 *
 * -   `Presentation`에 번역이 없다. 실제 payload에 그 필드가 없기 때문이고, demo도
 *     `문장 뜻 보기`를 누른 뒤에야 `korean_translation`을 건넨다.
 * -   설명은 `sentence_item_id`별이다. 같은 `learning_item_id`가 두 문장에 나오면 문맥
 *     뜻이 서로 다른 두 설명이 된다 --- 서버가 그렇게 저장한다.
 * -   **같은 item이 `anchor`에서 `new_context`로 다시 나온다**(`気が乗らない`,
 *     `learning_item_id: 772`). contextual review가 이 제품의 요점이므로 demo가 그것을
 *     체험시켜야 한다.
 */

import type { Explanation, Presentation, StudySession } from '../types'

/** 한 문장 몫의 fixture. 서버 응답 세 개(`/next`, `/click`, `/translation/reveal`)에 대응한다. */
export type DemoSentence = {
  presentation: Presentation
  /** `POST /translation/reveal`의 응답 값. payload에는 없다. */
  korean_translation: string
  /** `sentence_item_id` -> `POST /click`의 응답. */
  explanations: Record<number, Explanation>
}

/**
 * demo 세션. 숫자는 **서버가 보낸 payload 자리**이며 config를 읽은 것이 아니다.
 * 화면은 이 값만 보고 진행률과 "종료 도달"을 계산한다(`ui/progress.ts`).
 */
export const DEMO_SESSION: StudySession = {
  session_id: 1,
  started_at: '2026-09-12T09:00:00Z',
  last_activity_at: '2026-09-12T09:00:00Z',
  ended_at: null,
  active_seconds: 0,
  target_minutes: 12,
  extended_minutes: 0,
}

/** 문장 하나를 마칠 때 `active_seconds`가 늘어나는 폭. 세 문장이면 목표에 닿는다. */
export const DEMO_SECONDS_PER_SENTENCE = 240

/** `더 학습하기`를 눌렀을 때 서버가 돌려줄 `extended_minutes`. */
export const DEMO_EXTENDED_MINUTES = 5

const NANTONAKU: Explanation = {
  sentence_item_id: 1101,
  learning_item_id: 771,
  canonical_form: 'なんとなく',
  reading: 'なんとなく',
  item_type: 'expression',
  core_meaning: '왠지 / 특별한 이유 없이',
  meaning_in_context: '뚜렷한 이유를 말하기 어려운 기분을 앞에 둔다',
  nuance: '이유를 굳이 설명하지 않을 때 쓰는 일상 표현',
  example_sentence: 'なんとなく今日は家にいたい。',
  example_translation: '왠지 오늘은 집에 있고 싶다.',
}

/** anchor 문장에서의 `気が乗らない`. */
const KI_GA_NORANAI_ANCHOR: Explanation = {
  sentence_item_id: 1102,
  learning_item_id: 772,
  canonical_form: '気が乗らない',
  reading: 'き が のらない',
  item_type: 'expression',
  core_meaning: '내키지 않다 / 할 마음이 나지 않다',
  meaning_in_context: '나갈 생각은 있었지만 마음이 따라주지 않았다',
  nuance: '해야 할 이유는 있어도 의욕이 따라주지 않을 때 쓰는 일상 표현',
  example_sentence: '今日はあまり出かける気が乗らない。',
  example_translation: '오늘은 별로 나가고 싶지 않다.',
}

/** 같은 `learning_item_id`(772)가 **새 문맥**에서 다시 나온다. 문맥 뜻만 다르다. */
const KI_GA_NORANAI_NEW_CONTEXT: Explanation = {
  ...KI_GA_NORANAI_ANCHOR,
  sentence_item_id: 1301,
  meaning_in_context: '권유를 받았지만 응할 마음이 나지 않아 거절했다',
}

const TSUMORI: Explanation = {
  sentence_item_id: 1201,
  learning_item_id: 773,
  canonical_form: 'つもりだった',
  reading: 'つもり だった',
  item_type: 'grammar',
  core_meaning: '~할 생각이었다 (그러지 못했다)',
  meaning_in_context: '일찍 일어날 생각이었지만 그러지 못했다',
  nuance: '계획과 결과가 어긋났을 때 뒤에 아쉬움이 붙는다',
  example_sentence: '早く寝るつもりだったのに。',
  example_translation: '일찍 잘 생각이었는데.',
}

const YOFUKASHI: Explanation = {
  sentence_item_id: 1202,
  learning_item_id: 774,
  canonical_form: '夜更かし',
  reading: 'よふかし',
  item_type: 'word',
  core_meaning: '밤늦게까지 안 자는 것',
  meaning_in_context: '또 밤늦게까지 깨어 있었다',
  nuance: '스스로의 습관을 가볍게 말할 때 자주 쓴다',
  example_sentence: '夜更かしは体に悪い。',
  example_translation: '밤을 늦게까지 새우는 것은 몸에 좋지 않다.',
}

export const DEMO_SENTENCES: DemoSentence[] = [
  {
    presentation: {
      presentation_id: 101,
      sentence_id: 11,
      japanese: 'なんとなく気が乗らなくて、今日は家にいた。',
      render_segments: [
        { text: 'なんとなく', sentence_item_id: 1101, ruby: [] },
        { text: '気が乗らなくて', sentence_item_id: 1102, ruby: [] },
        { text: '、今日は家にいた。', sentence_item_id: null, ruby: [] },
      ],
      presentation_role: 'new',
      review_reason: null,
      context_stage: 'anchor',
      translation_revealed: false,
      tappable_items: [
        { sentence_item_id: 1101, learning_item_id: 771 },
        { sentence_item_id: 1102, learning_item_id: 772 },
      ],
      probe: null,
    },
    korean_translation: '왠지 마음이 내키지 않아서, 오늘은 집에 있었다.',
    explanations: { 1101: NANTONAKU, 1102: KI_GA_NORANAI_ANCHOR },
  },
  {
    presentation: {
      presentation_id: 102,
      sentence_id: 12,
      japanese: '明日は早く起きるつもりだったのに、また夜更かししてしまった。',
      render_segments: [
        { text: '明日は早く', sentence_item_id: null, ruby: [] },
        { text: '起きるつもりだった', sentence_item_id: 1201, ruby: [] },
        { text: 'のに、また', sentence_item_id: null, ruby: [] },
        { text: '夜更かし', sentence_item_id: 1202, ruby: [] },
        { text: 'してしまった。', sentence_item_id: null, ruby: [] },
      ],
      presentation_role: 'review',
      review_reason: 'fsrs_due',
      context_stage: 'near_original',
      translation_revealed: false,
      tappable_items: [
        { sentence_item_id: 1201, learning_item_id: 773 },
        { sentence_item_id: 1202, learning_item_id: 774 },
      ],
      // probe는 한 번만 나온다. 세션의 중심 UI가 아니다.
      probe: {
        probe_id: 9001,
        learning_item_id: 773,
        prompt: '이 표현을 알고 계세요?',
        expression: 'つもりだった',
        options: ['known', 'uncertain', 'unknown', 'skip'],
      },
    },
    korean_translation: '내일은 일찍 일어날 생각이었는데, 또 밤늦게까지 깨어 있었다.',
    explanations: { 1201: TSUMORI, 1202: YOFUKASHI },
  },
  {
    presentation: {
      presentation_id: 103,
      sentence_id: 13,
      japanese: '誘われたけど、なんだか気が乗らないので断った。',
      render_segments: [
        { text: '誘われたけど、なんだか', sentence_item_id: null, ruby: [] },
        { text: '気が乗らない', sentence_item_id: 1301, ruby: [] },
        { text: 'ので断った。', sentence_item_id: null, ruby: [] },
      ],
      presentation_role: 'review',
      review_reason: 'reinforcement',
      // 같은 item(772)이 anchor에서 여기로 왔다. demo의 요점이다.
      context_stage: 'new_context',
      translation_revealed: false,
      tappable_items: [{ sentence_item_id: 1301, learning_item_id: 772 }],
      probe: null,
    },
    korean_translation: '권유를 받았지만, 왠지 마음이 내키지 않아서 거절했다.',
    explanations: { 1301: KI_GA_NORANAI_NEW_CONTEXT },
  },
]
