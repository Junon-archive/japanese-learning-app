/**
 * 현재 문장 신고.
 *
 * reason 목록과 note 길이 상한은 **응답 계약 상수**이고 어떤 API 응답에도 실려 오지
 * 않는다. 그래서 두 가지를 함께 단정한다.
 *
 * 1.  화면이 그 값에서 **파생한다** --- 버튼 목록과 `maxlength`를 render 함수 안에
 *     리터럴로 다시 적으면 아래 테스트가 빨개진다.
 * 2.  그 값이 **backend와 같다** --- `backend/app/models/enums.py`의
 *     `ContentFlagReason`과 `backend/app/schemas/study.py`의 `FLAG_NOTE_MAX_LENGTH`를
 *     읽어 대조한다. backend가 reason을 하나 더하거나 상한을 바꾸면 여기서 드러난다.
 *     대조하지 않으면 "하드코딩이 아니다"는 상수 하나를 어딘가로 옮긴 것에 그친다.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { FLAG_NOTE_MAX_LENGTH, FLAG_REASONS, FLAG_SUBMITTED_TEXT, renderFlagControl } from '../../src/ui/flag'
import type { ContentFlagReason } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { FakeElement } from './fake-dom'
import { buttons, byClass, fakeDocument, flatText } from './fake-dom'

const BACKEND = fileURLToPath(new URL('../../../backend/app', import.meta.url))

type Overrides = {
  open?: boolean
  submitted?: boolean
  note?: string
  failure?: string | null
  onNoteInput?: (value: string) => void
  onSubmit?: (reason: ContentFlagReason) => void
}

function render(overrides: Overrides = {}): FakeElement {
  return renderFlagControl({
    open: overrides.open ?? false,
    submitted: overrides.submitted ?? false,
    submittedText: FLAG_SUBMITTED_TEXT,
    note: overrides.note ?? '',
    failure: overrides.failure ?? null,
    onOpen: () => {},
    onCancel: () => {},
    onNoteInput: overrides.onNoteInput ?? (() => {}),
    onSubmit: overrides.onSubmit ?? (() => {}),
  }) as unknown as FakeElement
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('flag contract constants', () => {
  it('lists exactly the backend ContentFlagReason values, in the same order', () => {
    const enums = readFileSync(`${BACKEND}/models/enums.py`, 'utf8')
    const block = /class ContentFlagReason\(enum\.StrEnum\):\n((?:\s+\w+ = "\w+"\n)+)/.exec(enums)
    const backendValues = [...(block?.[1] ?? '').matchAll(/= "(\w+)"/g)].map((match) => match[1])

    expect(backendValues).not.toEqual([])
    expect(FLAG_REASONS.map((reason) => reason.value)).toEqual(backendValues)
  })

  it('uses the backend note length limit', () => {
    const schemas = readFileSync(`${BACKEND}/schemas/study.py`, 'utf8')
    const limit = /FLAG_NOTE_MAX_LENGTH = (\d+)/.exec(schemas)?.[1]

    expect(limit).toBeDefined()
    expect(FLAG_NOTE_MAX_LENGTH).toBe(Number(limit))
  })
})

describe('renderFlagControl', () => {
  it('is collapsed by default, one control and nothing else', () => {
    const collapsed = render()

    expect(buttons(collapsed)).toHaveLength(1)
    expect(byClass(collapsed, 'flag-reason')).toEqual([])
  })

  it('derives one reason button per contract value', () => {
    const open = render({ open: true })

    expect(byClass(open, 'flag-reason').map((button) => button.textContent)).toEqual(
      FLAG_REASONS.map((reason) => reason.label),
    )
  })

  it('caps the note at the contract length', () => {
    const note = byClass(render({ open: true }), 'flag-note')[0]

    expect(note?.getAttribute('maxlength')).toBe(String(FLAG_NOTE_MAX_LENGTH))
  })

  it('keeps the typed note across renders and reports every keystroke', () => {
    const typed: string[] = []
    const open = render({
      open: true,
      note: '앞 문장과 이어지지 않는다',
      onNoteInput: (value) => typed.push(value),
    })

    // 다시 그려도 입력이 남아 있어야 한다 --- 상태에서 오기 때문이다.
    const note = byClass(open, 'flag-note')[0]!
    expect(note.value).toBe('앞 문장과 이어지지 않는다')

    note.value = '수정한 메모'
    note.fire('input')
    expect(typed).toEqual(['수정한 메모'])
  })

  it('submits the reason value, not its label', () => {
    const submitted: ContentFlagReason[] = []
    const open = render({ open: true, onSubmit: (reason) => submitted.push(reason) })

    for (const button of byClass(open, 'flag-reason')) button.click()

    expect(submitted).toEqual(FLAG_REASONS.map((reason) => reason.value))
  })

  it('says the sentence is quarantined and what to do next', () => {
    const done = render({ submitted: true })
    const text = flatText(done)

    expect(text).toBe(` ${FLAG_SUBMITTED_TEXT}`)
    expect(text).toContain('이제 나오지 않아요')
    expect(text).toContain('다음 문장')
    // 같은 문장을 두 번 신고하는 자리를 남기지 않는다.
    expect(buttons(done)).toEqual([])
  })

  it('shows a failure instead of pretending the flag was filed', () => {
    const failed = render({ open: true, failure: MESSAGES.saveFailed })

    expect(flatText(failed)).toContain(MESSAGES.saveFailed)
    expect(flatText(failed)).not.toContain(FLAG_SUBMITTED_TEXT)
  })
})

describe('flag wording', () => {
  it('uses the confirmed labels in the backend enum order', () => {
    expect(FLAG_REASONS.map((reason) => reason.label)).toEqual([
      '어색해요',
      '틀린 내용이 있어요',
      '너무 쉬워요',
      '너무 어려워요',
      '기타',
    ])
  })

  it('opens, asks and labels the note in the confirmed wording', () => {
    expect(byClass(render(), 'flag-open')[0]!.textContent).toBe('이 문장 신고하기')

    const open = render({ open: true })
    expect(byClass(open, 'flag-title')[0]!.textContent).toBe('어떤 점이 아쉬웠나요?')
    expect(flatText(open)).toContain('더 알려 주실 내용 (선택)')
    expect(byClass(open, 'flag-cancel')[0]!.textContent).toBe('취소')
  })

  it('keeps the quarantine fact in the submitted text', () => {
    expect(FLAG_SUBMITTED_TEXT).toBe(
      "알려 주셔서 고마워요. 이 문장은 이제 나오지 않아요. '다음 문장'으로 계속할 수 있어요.",
    )
  })
})
