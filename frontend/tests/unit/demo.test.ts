/**
 * Demo를 **끝까지 돌려 본다.** 문장 3개 주파, 탭, 번역, probe, 같은 item의 재등장까지.
 *
 * 그동안 단정하는 것 둘:
 *
 * 1.  **`fetch`가 한 번도 불리지 않는다.** 스텁이 던지도록 해 두었으므로 어느 경로에서든
 *     호출되면 그 자리에서 실패한다. 정적 검사(`demo-isolation.test.ts`)는 "코드에
 *     없다"까지고, 이 테스트가 "그래서 아무것도 안 나간다"를 말한다.
 * 2.  **어떤 저장소에도 쓰지 않는다.** localStorage·sessionStorage·cookie 쓰기를 전부
 *     던지게 해 두었다.
 *
 * fixture 상태기계도 같이 본다 --- 같은 `learning_item_id`가 `anchor`에서 `new_context`로
 * 다시 나오는 것이 demo의 요점이기 때문이다(contextual review).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { mount as mountDemo } from '../../src/demo/demo'
import { DEMO_SENTENCES, DEMO_SESSION } from '../../src/demo/fixture'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn(() => {
  throw new Error('demo must not make network requests')
})

function throwingStorage(name: string): Storage {
  const fail = (): never => {
    throw new Error(`demo must not write to ${name}`)
  }
  return {
    length: 0,
    clear: fail,
    getItem: () => null,
    key: () => null,
    removeItem: fail,
    setItem: fail,
  } as unknown as Storage
}

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

let root: FakeElement
let navigations: string[]
let logins: number

function mount(): void {
  root = createFakeElement('div')
  navigations = []
  logins = 0
  mountDemo({
    root: root as unknown as HTMLElement,
    signal: new AbortController().signal,
    subpath: '',
    navigate: (hash) => navigations.push(hash),
    openLogin: () => {
      logins += 1
    },
  })
}

function text(): string {
  return flatText(root)
}

function click(className: string, index = 0): void {
  const target = byClass(root, className)[index]
  expect(target, `no .${className}[${index}] on screen`).toBeDefined()
  target!.click()
}

/** 읽으면 빈 문자열, 쓰면 던지는 cookie jar. demo가 손대면 그 자리에서 실패한다. */
function documentWithCookieTrap(): object {
  const doc: Record<string, unknown> = { ...fakeDocument() }
  Object.defineProperty(doc, 'cookie', {
    get: () => '',
    set: () => {
      throw new Error('demo must not write cookies')
    },
  })
  return doc
}

beforeEach(() => {
  fetchMock.mockClear()
  vi.stubGlobal('document', documentWithCookieTrap())
  vi.stubGlobal('fetch', fetchMock)
  vi.stubGlobal('localStorage', throwingStorage('localStorage'))
  vi.stubGlobal('sessionStorage', throwingStorage('sessionStorage'))
  mount()
})

afterEach(() => {
  // **모든** 테스트에 걸린다. 어느 경로가 요청을 보내든 그 테스트에서 직접 드러난다
  // --- 개별 단정만 두면 아직 안 지나간 분기가 조용히 빠진다.
  expect(fetchMock).not.toHaveBeenCalled()
  vi.unstubAllGlobals()
})

describe('demo fixture', () => {
  it('has three sentences, all tappable items explained, and one probe', () => {
    expect(DEMO_SENTENCES.length).toBeGreaterThanOrEqual(3)

    for (const entry of DEMO_SENTENCES) {
      expect(entry.korean_translation).not.toBe('')
      for (const item of entry.presentation.tappable_items) {
        const explanation = entry.explanations[item.sentence_item_id]
        expect(explanation, `no explanation for ${item.sentence_item_id}`).toBeDefined()
        // 8개 precomputed 필드가 전부 있어야 실제 패널과 같은 화면이 된다.
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
      expect(entry.presentation.render_segments.map((s) => s.text).join('')).toBe(
        entry.presentation.japanese,
      )
    }

    const probes = DEMO_SENTENCES.filter((entry) => entry.presentation.probe !== null)
    expect(probes).toHaveLength(1)
  })

  it('brings the same item back from anchor to new_context', () => {
    const anchor = DEMO_SENTENCES.find((e) => e.presentation.context_stage === 'anchor')
    const newContext = DEMO_SENTENCES.find((e) => e.presentation.context_stage === 'new_context')

    expect(anchor).toBeDefined()
    expect(newContext).toBeDefined()

    const anchorItems = anchor!.presentation.tappable_items.map((i) => i.learning_item_id)
    const recurring = newContext!.presentation.tappable_items.filter((i) =>
      anchorItems.includes(i.learning_item_id),
    )

    // contextual review를 체험시키는 것이 demo의 요점이다.
    expect(recurring.length).toBeGreaterThanOrEqual(1)
    // 같은 item이지만 sentence_item은 다르고 문맥 뜻도 다르다 --- 서버가 그렇게 준다.
    const first = anchor!.explanations[
      anchor!.presentation.tappable_items.find(
        (i) => i.learning_item_id === recurring[0]!.learning_item_id,
      )!.sentence_item_id
    ]!
    const again = newContext!.explanations[recurring[0]!.sentence_item_id]!
    expect(again.sentence_item_id).not.toBe(first.sentence_item_id)
    expect(again.canonical_form).toBe(first.canonical_form)
    expect(again.meaning_in_context).not.toBe(first.meaning_in_context)
  })
})

describe('demo run', () => {
  it('walks the whole session without a single request', async () => {
    const [first, second, third] = DEMO_SENTENCES

    // 1. 첫 문장. 일본어가 먼저고 번역은 없다.
    expect(text()).toContain(first!.presentation.render_segments[0]!.text)
    expect(text()).not.toContain(first!.korean_translation)
    expect(byClass(root, 'translation')).toEqual([])
    expect(flatText(byClass(root, 'sentence-box')[0]!)).toContain(MESSAGES.sentenceHint)

    // 2. 탭 -> 설명. reading은 여기에만 있다.
    click('token')
    await flush()
    const firstExplanation = Object.values(first!.explanations)[0]!
    expect(text()).toContain(firstExplanation.core_meaning)
    expect(text()).toContain(firstExplanation.reading)

    // 3. 자가보고는 선택이다. 눌러도 진행을 막지 않는다.
    click('self-report', 1)
    await flush()
    expect(byClass(root, 'self-report')).toEqual([])

    // 4. 번역은 누른 뒤에 생긴다.
    click('reveal-translation')
    await flush()
    expect(text()).toContain(first!.korean_translation)

    // 5. 다음 문장 -> probe가 있는 문장.
    click('next')
    expect(text()).toContain(second!.presentation.probe!.prompt)
    expect(byClass(root, 'probe-option')).toHaveLength(second!.presentation.probe!.options.length)

    // 6. probe는 언제나 건너뛸 수 있고 즉시 지나간다.
    click('probe-option', 3)
    await flush()
    expect(text()).toContain('건너뛰었어요.')
    expect(byClass(root, 'probe-option')).toEqual([])

    // 7. 다음 문장 -> 같은 표현이 새 문맥으로 돌아온다.
    click('next')
    const again = Object.values(third!.explanations)[0]!
    click('token')
    await flush()
    expect(text()).toContain(again.meaning_in_context)

    // 8. 마지막 문장을 마치면 목표에 닿아 선택지가 뜬다. 세션이 닫힌 것은 아니다.
    click('next')
    expect(text()).toContain('오늘 학습 완료')
    expect(text()).toContain('더 학습하기')

    // 9. 종료.
    click('primary')
    expect(text()).toContain('오늘 학습을 마쳤어요.')

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('flags a sentence without leaving the demo', async () => {
    click('flag-open')
    click('flag-reason', 0)
    await flush()

    // demo 전용 안내. 요청을 보내지 않으므로 저장됐다고 말하지 않는다.
    expect(text()).toContain('체험에서는 신고가 저장되지 않아요.')
    expect(text()).not.toContain('이제 나오지 않아요')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('keeps the session numbers the fixture gave it', () => {
    // 정책값을 화면이 만들지 않는다. `오늘 약 12분`의 출처는 fixture payload다.
    expect(text()).toContain(`오늘 약 ${DEMO_SESSION.target_minutes}분`)
  })

  it('extends and restarts instead of ending on an empty screen', () => {
    click('next')
    click('next')
    click('next')

    // `더 학습하기`는 두 번째 버튼이다(`오늘 학습 완료`가 첫 번째).
    const buttons = byClass(root, 'secondary')
    buttons[0]!.click()

    expect(text()).toContain('처음부터 다시')
    expect(text()).toContain(DEMO_SENTENCES[0]!.presentation.render_segments[0]!.text)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('leaves through the top bar only', () => {
    expect(byClass(root, 'demo-exit')).toEqual([])

    click('topbar-brand')
    expect(navigations).toEqual(['#/'])
    expect(logins).toBe(0)

    // 로그인 진입은 넘겨받은 값을 상단바가 누를 때 부른다. demo가 직접 부르지 않는다.
    click('topbar-login')
    expect(logins).toBe(1)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('leaves no trace in any browser store', async () => {
    // demo 상태는 browser memory/session 수준에서만 유지한다(04_SECURITY_AND_DATA.md).
    click('token')
    await flush()
    click('reveal-translation')
    await flush()
    click('next')
    click('probe-option', 0)
    await flush()

    expect(localStorage.length).toBe(0)
    expect(sessionStorage.length).toBe(0)
    expect(document.cookie).toBe('')
  })

  it('shows only fixed wording when the fixture lacks an explanation', async () => {
    const explanations = DEMO_SENTENCES[0]!.explanations
    const [id, saved] = Object.entries(explanations)[0]!
    delete explanations[Number(id)]
    try {
      mount()
      click('token')
      await flush()

      // 예외 메시지(영어, fixture id)를 화면에 내지 않는다.
      expect(text()).toContain(MESSAGES.notFound)
      expect(text()).not.toContain('demo fixture')
      expect(text()).not.toContain(id)
    } finally {
      explanations[Number(id)] = saved
    }
  })

  it('has no logout control', () => {
    // Demo는 Login 화면을 지나지 않으므로 폐기할 세션이 없다(03_UI_UX_SPEC.md의 `로그아웃`).
    expect(text()).not.toContain('로그아웃')
    expect(byClass(root, 'logout')).toEqual([])
  })

  it('says it is a demo', () => {
    expect(root.children[0]!.querySelector('h1')!.textContent).toBe('표현 학습 체험')
    expect(text()).toContain('체험 중이에요. 기록은 이 브라우저에만 남아요.')
  })
})
