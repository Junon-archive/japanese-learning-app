/**
 * 설명 패널.
 *
 * 단정하는 것은 넷이다.
 *
 * 1.  서버가 준 **precomputed 필드를 하나도 빠뜨리지 않는다.** item 설명의 reading은 여기에만
 *     있으므로 빠지면 화면에서 영구히 사라진다.
 * 4.  머리는 **문장 속 표면형과 그 읽기의 짝**이고 기본형은 따로다. 유형 태그는 표시용 매핑이며
 *     모르는 값은 원문 그대로다.
 * 2.  self-report는 3값이고 `skip`이 없다.
 * 3.  기록된 뒤에는 **버튼이 없다.** 같은 노출에 두 번째 evidence를 만들 자리를 남기지
 *     않는다(ADR-018).
 * 5.  **`lang` 속성과 예문 재생 버튼은 호출자가 넘긴 `language`가 정한다**(ADR-025 결정 1·4). 영어
 *     문장에 `lang="ja"`를 적지 않고, 재생 버튼은 영어에만 있다. 재생 자체는 `speech.test.ts`가 본다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { SELF_REPORT_CHOICES, itemTypeLabel, renderExplanationPanel } from '../../src/ui/explanation'
import type { ExplicitSignal, Explanation } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, fakeDocument, flatText } from './fake-dom'

/** 05_API_SPEC.md의 explanation 예시 그대로. */
const EXPLANATION: Explanation = {
  sentence_item_id: 5512,
  learning_item_id: 772,
  canonical_form: '気が乗らない',
  reading: 'き が のらない',
  item_type: 'expression',
  core_meaning: '내키지 않다 / 할 마음이 나지 않다',
  meaning_in_context: '연구실에 갈 생각이었지만 마음이 내키지 않았다',
  nuance: '해야 할 이유는 있어도 의욕이 따라주지 않을 때 쓰는 일상 표현',
  example_sentence: '今日はあまり出かける気が乗らない。',
  example_translation: '오늘은 별로 나가고 싶지 않다.',
}

type Overrides = {
  reported?: ExplicitSignal | null
  alreadyRecorded?: boolean
  failure?: string | null
  onSelfReport?: (value: ExplicitSignal) => void
  explanation?: Explanation
  language?: 'ja' | 'en' | null
}

/** 문장 `…なんとなく気が乗らなくて家にいた。`의 그 segment text. */
const SURFACE = '気が乗らなくて'

function render(overrides: Overrides = {}): FakeElement {
  return renderExplanationPanel({
    explanation: overrides.explanation ?? EXPLANATION,
    surface: SURFACE,
    language: overrides.language ?? 'ja',
    signal: new AbortController().signal,
    reported: overrides.reported ?? null,
    alreadyRecorded: overrides.alreadyRecorded ?? false,
    failure: overrides.failure ?? null,
    onSelfReport: overrides.onSelfReport ?? (() => {}),
  }) as unknown as FakeElement
}

/** 영어 설명(reading이 없다, ADR-023 결정 6). */
const EN_EXPLANATION: Explanation = {
  ...EXPLANATION,
  canonical_form: 'be in the mood',
  reading: null,
  core_meaning: '~할 마음이 들다',
  example_sentence: "I'm not in the mood to go out today.",
}

/** 로컬 영어 음성이 하나 있는 브라우저. 없으면 재생 버튼이 그려지지 않는다. */
function withLocalEnglishVoice(): void {
  vi.stubGlobal('speechSynthesis', {
    getVoices: () => [{ name: 'voice-1', lang: 'en-US', localService: true }],
    speak: () => {},
    cancel: () => {},
    speaking: false,
    pending: false,
    addEventListener: () => {},
  })
  vi.stubGlobal(
    'SpeechSynthesisUtterance',
    class {
      text: string
      voice: unknown = null
      constructor(text: string) {
        this.text = text
      }
    },
  )
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('renderExplanationPanel', () => {
  it('shows every precomputed field the server sent', () => {
    const text = flatText(render())

    for (const value of [
      EXPLANATION.canonical_form,
      EXPLANATION.reading,
      EXPLANATION.core_meaning,
      EXPLANATION.meaning_in_context,
      EXPLANATION.nuance,
      EXPLANATION.example_sentence,
      EXPLANATION.example_translation,
    ]) {
      expect(text).toContain(String(value))
    }
  })

  it('omits the example translation when the server has none', () => {
    const panel = render({ explanation: { ...EXPLANATION, example_translation: null } })

    // 빈 노드를 만들지 않는다. 없는 것은 없는 것으로 둔다.
    expect(flatText(panel)).not.toContain(String(EXPLANATION.example_translation))
  })

  it('omits the reading line entirely when the server has none (영어, ADR-023 결정 6)', () => {
    const panel = render({ explanation: { ...EXPLANATION, reading: null } })

    // 빈 줄이나 `-`가 아니라 줄 자체가 없다(03_UI_UX_SPEC.md, 합격 기준 24).
    expect(byClass(panel, 'reading')).toEqual([])
  })

  it('pairs the surface form in the sentence with its reading, and puts the canonical form apart', () => {
    const panel = render()

    const head = byClass(panel, 'item-head')[0]!
    expect(byClass(head, 'jp-word')[0]!.textContent).toBe(SURFACE)
    expect(byClass(head, 'reading')[0]!.textContent).toBe(EXPLANATION.reading)
    expect(byClass(head, 'canonical-form')[0]!.textContent).toBe(EXPLANATION.canonical_form)
  })

  it('labels the item type for display and keeps unknown values as they are', () => {
    expect(byClass(render(), 'tag')[0]!.textContent).toBe('표현')
    expect(itemTypeLabel('word')).toBe('단어')
    expect(itemTypeLabel('grammar')).toBe('문법')
    expect(itemTypeLabel('expression')).toBe('표현')
    expect(byClass(render({ explanation: { ...EXPLANATION, item_type: 'idiom' as never } }), 'tag')[0]!.textContent).toBe(
      'idiom',
    )
  })

  it('has no close button of its own; the sheet closes it', () => {
    expect(buttons(render()).filter((button) => button.className !== 'self-report')).toEqual([])
  })

  it('offers exactly the three self-report values, skip not among them', () => {
    const labels = buttons(render())
      .filter((button) => button.className === 'self-report')
      .map((button) => button.textContent)

    expect(labels).toEqual(SELF_REPORT_CHOICES.map((choice) => choice.label))
    expect(labels).toHaveLength(3)
    expect(labels).not.toContain('건너뛰기')
  })

  it('passes the chosen value back', () => {
    const chosen: ExplicitSignal[] = []
    const panel = render({ onSelfReport: (value) => chosen.push(value) })

    for (const button of buttons(panel).filter((b) => b.className === 'self-report')) button.click()

    expect(chosen).toEqual(SELF_REPORT_CHOICES.map((choice) => choice.value))
  })

  it('locks the buttons away once a value is recorded', () => {
    const panel = render({ reported: 'uncertain' })

    expect(buttons(panel).filter((b) => b.className === 'self-report')).toEqual([])
    expect(flatText(panel)).toContain('기록했어요 · 애매함')
  })

  it('locks the buttons away when the server already has evidence', () => {
    const panel = render({ alreadyRecorded: true })

    expect(buttons(panel).filter((b) => b.className === 'self-report')).toEqual([])
    expect(flatText(panel)).toContain('이 문장에서는 이미 기록했어요.')
  })

  it('shows a failure without pretending the report was saved', () => {
    const panel = render({ failure: MESSAGES.saveFailed })

    expect(flatText(panel)).toContain(MESSAGES.saveFailed)
    // 실패했으므로 버튼은 그대로 있다 --- 잠그면 사용자가 다시 시도할 수 없다.
    expect(buttons(panel).filter((b) => b.className === 'self-report')).toHaveLength(3)
  })

  it('has no play button in Japanese, even with a usable voice', () => {
    // 일본어에는 재생 버튼이 없다(ADR-025 결정 4). 00_SCOPE.md의 audio 금지는 영어 재생 하나만 열렸다.
    withLocalEnglishVoice()

    expect(byClass(render(), 'speak')).toEqual([])
  })
})

describe('the play button next to the example sentence (영어)', () => {
  it('is drawn only for en, and only next to the example', () => {
    withLocalEnglishVoice()

    const panel = render({ language: 'en', explanation: EN_EXPLANATION })

    const speak = byClass(panel, 'speak')
    expect(speak).toHaveLength(1)
    // 예문 칸 안이다. 머리(표면형)나 자기평가 옆이 아니다.
    const example = byClass(panel, 'explain-block')[3]!
    expect(byClass(example, 'speak')).toHaveLength(1)
  })

  it('is not drawn when the browser has no usable voice', () => {
    // `speechSynthesis`를 세우지 않았다 --- API가 없는 브라우저다. 비활성 버튼도 두지 않는다.
    expect(byClass(render({ language: 'en', explanation: EN_EXPLANATION }), 'speak')).toEqual([])
  })

  it('marks lang with the language the caller gave, never a hardcoded ja', () => {
    withLocalEnglishVoice()

    const en = render({ language: 'en', explanation: EN_EXPLANATION })
    expect(byClass(en, 'jp-word')[0]!.lang).toBe('en')
    expect(byClass(en, 'canonical-form')[0]!.lang).toBe('en')
    expect(byClass(en, 'example')[0]!.lang).toBe('en')

    const ja = render()
    expect(byClass(ja, 'jp-word')[0]!.lang).toBe('ja')
    expect(byClass(ja, 'canonical-form')[0]!.lang).toBe('ja')
    expect(byClass(ja, 'reading')[0]!.lang).toBe('ja')
    expect(byClass(ja, 'example')[0]!.lang).toBe('ja')
  })
})

describe('explanation wording', () => {
  it('names the fields and asks the optional self-report question', () => {
    const panel = render()

    expect(byClass(panel, 'explain-label').map((label) => label.textContent)).toEqual([
      '뜻',
      '이 문장에서',
      '느낌',
      '예문',
    ])
    expect(flatText(panel)).toContain('이 표현, 알고 있었나요?')
    expect(flatText(panel)).toContain('고르지 않아도 괜찮아요.')
    expect(panel.getAttribute('aria-label')).toBe('표현 설명')
  })
})
