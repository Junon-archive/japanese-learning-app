/**
 * 현재 문장 신고. **데이터 + 콜백만 받는 순수 렌더러다.**
 *
 * **지난 문장을 신고하는 화면을 만들지 않는다.** `/flag`가 닫힌 session과 완료된
 * presentation에서도 받는 것은 exposure 무효화 때문이고(05_API_SPEC.md의 상태 게이트),
 * MVP UI는 현재 문장에서만 flag를 제공한다. 목록·이력 화면은 Future다.
 *
 * 아래 두 값은 **응답 계약 상수다** --- 학습 정책값이 아니므로 config에 없고, 어떤
 * API 응답에도 실려 오지 않는다(`05_API_SPEC.md`의 `개수 상한`이 50을 두는 것과 같은
 * 취급). 그래서 backend와 같은 값을 여기 한 곳에 적고, 화면은 **전부 이 값에서
 * 파생한다.** 어긋나면 `tests/unit/flag.test.ts`가 backend 소스를 읽어 빨개진다.
 */

import type { ContentFlagReason } from '../types'

/** `backend/app/models/enums.py`의 `ContentFlagReason`. 선언 순서가 표시 순서다. */
export const FLAG_REASONS: readonly { value: ContentFlagReason; label: string }[] = [
  { value: 'unnatural', label: '자연스럽지 않다' },
  { value: 'wrong', label: '틀렸다' },
  { value: 'too_easy', label: '너무 쉽다' },
  { value: 'too_hard', label: '너무 어렵다' },
  { value: 'other', label: '기타' },
]

/** `backend/app/schemas/study.py`의 `FLAG_NOTE_MAX_LENGTH`. 넘기면 422다. */
export const FLAG_NOTE_MAX_LENGTH = 500

export type FlagControlOptions = {
  /** 신고 폼이 펼쳐져 있는가. 기본은 접힌 상태다 --- 학습 화면의 중심이 아니다. */
  open: boolean
  /** 이미 신고했다. 같은 문장을 두 번 신고하는 자리를 남기지 않는다. */
  submitted: boolean
  /** 다시 그려도 남아 있어야 하는 입력값. */
  note: string
  failure: string | null
  onOpen: () => void
  onCancel: () => void
  onNoteInput: (value: string) => void
  /** reason 하나를 고르는 것이 곧 제출이다. 한 손으로 두 번 누르면 끝난다. */
  onSubmit: (reason: ContentFlagReason) => void
}

export function renderFlagControl(options: FlagControlOptions): HTMLElement {
  const box = document.createElement('section')
  box.className = 'flag'

  if (options.submitted) {
    // 무엇이 일어났고 다음에 무엇을 하면 되는지 한 번에 적는다.
    const done = document.createElement('p')
    done.className = 'flag-done'
    done.setAttribute('role', 'status')
    done.textContent =
      '신고를 접수했습니다. 이 문장은 앞으로 학습에 사용되지 않습니다. 아래 ‘다음 문장’으로 계속할 수 있습니다.'
    box.append(done)
    return box
  }

  if (!options.open) {
    const open = document.createElement('button')
    open.type = 'button'
    open.className = 'flag-open'
    open.textContent = '이 문장 신고'
    open.addEventListener('click', options.onOpen)
    box.append(open)
    if (options.failure !== null) box.append(failureLine(options.failure))
    return box
  }

  const title = document.createElement('p')
  title.className = 'flag-title'
  title.textContent = '어떤 점이 문제였나요?'

  const noteField = document.createElement('label')
  noteField.className = 'flag-note-field'
  noteField.textContent = '덧붙일 말 (선택)'

  const note = document.createElement('textarea')
  note.className = 'flag-note'
  note.value = options.note
  // 상한을 리터럴로 적지 않는다. 위 상수 하나에서 온다.
  note.setAttribute('maxlength', String(FLAG_NOTE_MAX_LENGTH))
  note.addEventListener('input', () => {
    options.onNoteInput(note.value)
  })
  noteField.append(note)

  const reasons = document.createElement('div')
  reasons.className = 'flag-reasons'
  for (const reason of FLAG_REASONS) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'flag-reason'
    button.textContent = reason.label
    button.addEventListener('click', () => {
      options.onSubmit(reason.value)
    })
    reasons.append(button)
  }

  const cancel = document.createElement('button')
  cancel.type = 'button'
  cancel.className = 'flag-cancel'
  cancel.textContent = '취소'
  cancel.addEventListener('click', options.onCancel)

  box.append(title, noteField, reasons, cancel)
  if (options.failure !== null) box.append(failureLine(options.failure))
  return box
}

function failureLine(text: string): HTMLElement {
  const failure = document.createElement('p')
  failure.className = 'panel-failure'
  failure.setAttribute('role', 'alert')
  failure.textContent = text
  return failure
}
