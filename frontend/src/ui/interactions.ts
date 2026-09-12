/**
 * 한 문장의 상호작용 네 가지: 설명 패널(F3), 번역 reveal(F4), probe(F5), 신고(F8).
 *
 * **이 파일은 `api.ts`도 `endpoints.ts`도 import하지 않는다.** 호출은 전부 `ops`로
 * 주입받는다. 그래서 테스트가 fetch를 흉내내지 않고 호출 순서를 단정할 수 있고, 같은
 * 렌더러를 static fixture 위에서도 쓸 수 있다(호출부는 `ui/study.ts`다).
 *
 * 지키는 것들. 전부 화면에서는 정상으로 보이기 때문에 주석으로 남긴다.
 *
 * 1.  **번역 노드는 reveal 응답을 받은 뒤에 만든다.** 미리 만들어 두고 `hidden`으로
 *     토글하면 "호출 후 공개"가 거짓이 된다 --- 번역 문자열이 이미 화면 DOM에 있으므로
 *     `translation_revealed` event가 "사용자가 번역을 봤다"를 뜻하지 못한다. payload에
 *     번역 필드 자체가 없으므로(`types.ts`의 `Presentation`) 만들 재료도 없다.
 * 2.  **`explanation_revealed`는 패널이 실제로 렌더된 뒤에 보낸다.** 탭과 동시에 보내면
 *     두 event가 항상 1:1이 되어 "탭했지만 표시되지 않은 경우"를 구분할 수 없다. click이
 *     실패하면 `item_clicked`만 남아야 하므로 **그 경로에서는 보내지 않는다**
 *     (05_API_SPEC.md의 `explanation_revealed를 언제 보내는가`).
 * 3.  **같은 item의 패널을 접었다 펴도 event가 늘지 않는다.** 다시 열 때 `/click`도
 *     부르지 않는다 --- 캐시한 설명을 그대로 그린다. client key는 UUIDv4라 매번 보내면
 *     그때마다 새 event가 쌓여 raw history가 UI 조작 횟수를 세게 된다.
 * 4.  **self-report와 probe는 선택이다.** 둘 다 잠기거나 실패해도 문장 진행을 막지
 *     않는다. probe는 세션의 중심 UI가 아니므로 `skip`으로 즉시 지나갈 수 있다.
 * 5.  **실패를 성공처럼 보이지 않게 한다.** 실패한 자리에 문구를 남기고, 번역이 오지
 *     않으면 빈 번역 노드를 만들지 않는다(10_ERROR_HANDLING.md).
 * 6.  타이머도 주기 호출도 없다. 사용자가 누른 것만 나간다.
 */

import type { ContentFlagReason, ExplicitSignal, Explanation, Presentation } from '../types'
import { renderExplanationPanel } from './explanation'
import { renderFlagControl } from './flag'
import { renderProbe } from './probe'

/** 호출부가 실패를 처리한 결과. 컨트롤러는 이것으로 화면에 무엇을 남길지 정한다. */
export type InteractionFailure =
  /** 호출부가 복구를 시작했다(세션 재획득 / 로그인 이동). 이 자리에 문구를 남기지 않는다. */
  | { kind: 'handled' }
  /** 서버가 이 노출의 evidence를 이미 갖고 있다. 잠그고 끝낸다 --- 재시도는 성공하지 못한다. */
  | { kind: 'alreadyRecorded' }
  | { kind: 'message'; text: string }

/**
 * 상호작용 하나당 함수 하나. 전부 실패하면 reject한다.
 *
 * `reportFailure`는 실패를 호출부에 넘기고 **무엇이었는지**를 돌려준다. 분류를 이 파일에
 * 두지 않는 이유는 그것이 HTTP 사정(409 사유 문구)이기 때문이다.
 */
export type InteractionOps = {
  clickItem: (sentenceItemId: number) => Promise<Explanation>
  markExplanationRevealed: (sentenceItemId: number) => Promise<void>
  revealTranslation: () => Promise<string>
  selfReport: (sentenceItemId: number, value: ExplicitSignal) => Promise<void>
  /** 서버가 기록한 값을 돌려준다. 같은 probe에 이미 응답이 있으면 그 값이다. */
  respondToProbe: (probeId: number, value: string) => Promise<string>
  flagContent: (reason: ContentFlagReason, note: string | null) => Promise<void>
  reportFailure: (error: unknown) => InteractionFailure
}

export type InteractionsHandle = {
  /** 호출부가 슬롯에 붙이는 노드. 이 컨트롤러는 자기 노드 안만 고친다. */
  element: HTMLElement
  /** 문장의 tappable span이 눌렸다. */
  tapItem: (sentenceItemId: number) => void
  /** 상태를 그대로 다시 그린다. 잠금(비활성) 상태를 복원하는 용도다. */
  refresh: () => void
}

const ALREADY_RECORDED = '이미 기록했습니다.'
const TRANSLATION_FAILED = '문장 뜻을 표시하지 못했습니다.'

type ItemState = {
  explanation: Explanation
  reported: ExplicitSignal | null
  alreadyRecorded: boolean
  failure: string | null
}

export function createInteractions(
  presentation: Presentation,
  ops: InteractionOps,
): InteractionsHandle {
  const box = document.createElement('div')
  box.className = 'interactions'

  const items = new Map<number, ItemState>()
  /** 이미 `explanation_revealed`를 **시도한** item. presentation당 1회다. */
  const revealAttempted = new Set<number>()
  const pending = new Set<string>()

  let openItemId: number | null = null
  let itemFailure: string | null = null
  /** reveal 응답을 받기 전에는 **문자열 자체가 없다.** */
  let translation: string | null = null
  let translationFailure: string | null = null
  let probeAnswered: string | null = null
  let probeAlreadyRecorded = false
  let probeFailure: string | null = null
  let flagOpen = false
  let flagSubmitted = false
  let flagNote = ''
  let flagFailure: string | null = null

  // ----------------------------------------------------------------------
  // 렌더
  // ----------------------------------------------------------------------

  function render(): void {
    const parts: HTMLElement[] = [renderTranslationArea()]

    const open = openItemId === null ? undefined : items.get(openItemId)
    if (openItemId !== null && open !== undefined) {
      const itemId = openItemId
      parts.push(
        renderExplanationPanel({
          explanation: open.explanation,
          reported: open.reported,
          alreadyRecorded: open.alreadyRecorded,
          failure: open.failure,
          onSelfReport: (value) => {
            sendSelfReport(itemId, value)
          },
          onClose: () => {
            openItemId = null
            render()
          },
        }),
      )
    }
    if (itemFailure !== null) parts.push(failureLine(itemFailure))

    if (presentation.probe !== null) {
      const probe = presentation.probe
      parts.push(
        renderProbe({
          probe,
          answered: probeAnswered,
          alreadyRecorded: probeAlreadyRecorded,
          failure: probeFailure,
          onRespond: (value) => {
            sendProbeResponse(value)
          },
        }),
      )
    }

    parts.push(
      renderFlagControl({
        open: flagOpen,
        submitted: flagSubmitted,
        note: flagNote,
        failure: flagFailure,
        onOpen: () => {
          flagOpen = true
          render()
        },
        onCancel: () => {
          flagOpen = false
          render()
        },
        onNoteInput: (value) => {
          // 다시 그려도 입력이 사라지지 않게 상태에 둔다. 여기서 render하지 않는다.
          flagNote = value
        },
        onSubmit: (reason) => {
          sendFlag(reason)
        },
      }),
    )

    box.replaceChildren(...parts)
  }

  /**
   * 번역 자리. `translation`이 null이면 **버튼 하나뿐이고 번역 노드가 없다.**
   *
   * 숨겨 둔 노드를 토글하는 구조로 바꾸지 마라(모듈 주석 1).
   */
  function renderTranslationArea(): HTMLElement {
    const area = document.createElement('div')
    area.className = 'translation-area'

    if (translation === null) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'secondary reveal-translation'
      button.textContent = '문장 뜻 보기'
      button.addEventListener('click', () => {
        revealTranslation()
      })
      area.append(button)
      // 실패했으면 그 사실을 적는다. 빈 번역 노드를 만들지 않는다.
      if (translationFailure !== null) area.append(failureLine(translationFailure))
      return area
    }

    const text = document.createElement('p')
    text.className = 'translation'
    text.textContent = translation
    area.append(text)
    return area
  }

  function failureLine(text: string): HTMLElement {
    const node = document.createElement('p')
    node.className = 'panel-failure'
    node.setAttribute('role', 'alert')
    node.textContent = text
    return node
  }

  // ----------------------------------------------------------------------
  // 동작
  // ----------------------------------------------------------------------

  /** 같은 동작이 진행 중이면 새로 시작하지 않는다. 연타가 event를 늘리지 않는다. */
  async function perform(
    key: string,
    task: () => Promise<void>,
    onFailure: (failure: InteractionFailure) => void,
  ): Promise<void> {
    if (pending.has(key)) return
    pending.add(key)
    try {
      await task()
    } catch (error) {
      onFailure(ops.reportFailure(error))
      render()
    } finally {
      pending.delete(key)
    }
  }

  /** `handled`는 문구를 남기지 않는다 --- 호출부가 화면을 이미 바꾸고 있다. */
  function failureText(failure: InteractionFailure): string | null {
    if (failure.kind === 'handled') return null
    return failure.kind === 'alreadyRecorded' ? ALREADY_RECORDED : failure.text
  }

  function tapItem(sentenceItemId: number): void {
    itemFailure = null

    if (openItemId === sentenceItemId) {
      // 접기. event를 보내지 않는다.
      openItemId = null
      render()
      return
    }

    if (items.has(sentenceItemId)) {
      // 다시 펴기. `/click`도 `explanation-revealed`도 보내지 않는다(모듈 주석 3).
      openItemId = sentenceItemId
      render()
      return
    }

    void perform(
      `click:${sentenceItemId}`,
      async () => {
        const explanation = await ops.clickItem(sentenceItemId)
        items.set(sentenceItemId, {
          explanation,
          reported: null,
          alreadyRecorded: false,
          failure: null,
        })
        openItemId = sentenceItemId
        // **먼저 렌더한다.** 다음 줄의 event는 "설명이 표시됐다"를 뜻한다.
        render()
        // **이 task 안에서 await하지 않는다.** 아래 `sendExplanationRevealed` 참조.
        sendExplanationRevealed(sentenceItemId)
      },
      (failure) => {
        // click이 실패한 경로만 여기로 온다. `explanation_revealed`는 자기 실패를
        // 스스로 삼키므로 이 핸들러에 닿지 않는다.
        itemFailure = failureText(failure)
      },
    )
  }

  /**
   * `explanation_revealed`. **auxiliary signal이므로 실패를 삼킨다.**
   *
   * click의 task와 분리되어 있다. 한 task에 두면 이 event의 실패가 click 경로의 실패
   * 처리를 타고, 게이트 409일 때 `reportFailure`가 세션 재획득을 시작해 **이미 올바르게
   * 렌더된 문장이 화면에서 치워진다.** 보조 신호가 정상 표시를 무너뜨리는 것이고,
   * "보내지 않아도 학습 진행은 막히지 않는다"(05_API_SPEC.md)와 어긋난다. 그래서 실패해도
   * 화면을 건드리지 않는다 --- 설명은 이미 표시됐고 사용자가 할 일도 없다.
   *
   * `revealAttempted`를 **await 전에** 표시한다. 실패한 전송을 재시도하지 않는다는 뜻이고,
   * 의도된 보수적 선택이다: 명세가 "한 presentation에서 1회만 보낸다"를 요구하므로 시도
   * 기준으로 세는 쪽이 그 규칙을 어길 수 없다. 대가는 실패한 event가 영구 부재라는 것이며,
   * auxiliary signal이라 mastery도 FSRS도 그것에 기대지 않는다.
   */
  function sendExplanationRevealed(sentenceItemId: number): void {
    if (revealAttempted.has(sentenceItemId)) return
    revealAttempted.add(sentenceItemId)
    void ops.markExplanationRevealed(sentenceItemId).catch(() => {
      // 의도적으로 비어 있다. `ops.reportFailure`를 부르지 않는다 --- 그 경로가 위
      // 주석의 세션 재획득을 일으킨다.
    })
  }

  function revealTranslation(): void {
    if (translation !== null) return
    translationFailure = null
    void perform(
      'translation',
      async () => {
        const korean = await ops.revealTranslation()
        translation = korean
        render()
      },
      (failure) => {
        const text = failureText(failure)
        // 성공처럼 보이게 하지 않는다. 버튼은 남아 있어 사용자가 다시 누를 수 있다.
        translationFailure = text === null ? null : `${TRANSLATION_FAILED} ${text}`
      },
    )
  }

  function sendSelfReport(sentenceItemId: number, value: ExplicitSignal): void {
    const item = items.get(sentenceItemId)
    if (item === undefined || item.reported !== null || item.alreadyRecorded) return
    item.failure = null
    void perform(
      `self-report:${sentenceItemId}`,
      async () => {
        await ops.selfReport(sentenceItemId, value)
        item.reported = value
        render()
      },
      (failure) => {
        if (failure.kind === 'alreadyRecorded') {
          // 게이트 409와 다르다. 세션을 다시 얻지 않고 잠그고 끝낸다(ADR-018).
          item.alreadyRecorded = true
          return
        }
        item.failure = failureText(failure)
      },
    )
  }

  function sendProbeResponse(value: string): void {
    const probe = presentation.probe
    if (probe === null || probeAnswered !== null || probeAlreadyRecorded) return
    probeFailure = null
    void perform(
      'probe',
      async () => {
        // 서버가 돌려준 값을 쓴다. 같은 probe에 이미 응답이 있으면 그것이 기존 값이다.
        probeAnswered = await ops.respondToProbe(probe.probe_id, value)
        render()
      },
      (failure) => {
        if (failure.kind === 'alreadyRecorded') {
          // 이 노출의 evidence는 **다른 경로로** 기록됐을 수 있다(같은 item의
          // self-report). 사용자가 보낸 값이 기록됐다고 말하지 않는다.
          probeAlreadyRecorded = true
          return
        }
        probeFailure = failureText(failure)
      },
    )
  }

  function sendFlag(reason: ContentFlagReason): void {
    if (flagSubmitted) return
    flagFailure = null
    void perform(
      'flag',
      async () => {
        await ops.flagContent(reason, flagNote === '' ? null : flagNote)
        flagSubmitted = true
        flagOpen = false
        render()
      },
      (failure) => {
        flagFailure = failureText(failure)
      },
    )
  }

  render()
  return { element: box, tapItem, refresh: render }
}
