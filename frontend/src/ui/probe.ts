/**
 * Mastery probe. **데이터 + 콜백만 받는 순수 렌더러다.**
 *
 * 세 가지를 여기서 못 박는다.
 *
 * 1.  **`prompt`와 `options`는 payload에서 온다.** 문구를 상수로 복사하거나 버튼을
 *     고정 배열로 만들지 않는다 --- 그러면 서버가 문구/순서를 바꿔도 화면이 옛 것을
 *     계속 보여주고, 그 불일치를 잡을 방법이 없다(05_API_SPEC.md의 probe payload).
 * 2.  **모르는 option 값은 원문 그대로 노출한다.** 조용히 버리면 서버가 값을 추가한
 *     날 버튼 하나가 화면에서 사라지고 아무도 모른다. 라벨 매핑은 표시용이며
 *     `options`의 **필터가 아니다.**
 * 3.  **객관식 의미 문제가 아니다.** 선택지는 `알고 있었음 / 애매함 / 몰랐음 /
 *     건너뛰기` 하나로 고정이고(03_UI_UX_SPEC.md) 사용자는 언제나 건너뛸 수 있다.
 *
 * probe는 세션의 중심 UI가 아니다. 그래서 문장·설명·번역을 가리지 않고 화면 아래에
 * 한 조각으로 붙으며, 답하지 않아도 다음 문장으로 넘어갈 수 있다.
 */

import type { Probe, ProbeResponseValue } from '../types'

/**
 * 값 -> 라벨. **프론트가 가진 것은 이 매핑뿐이다.** 순서도 목록도 payload가 정한다.
 *
 * 키 타입이 `ProbeResponseValue`인 쪽이 **지금 아는 4값의 라벨을 빠뜨리지 못하게** 하고,
 * `string` 쪽이 **모르는 값을 조회할 수 있게** 한다. 둘이 다 필요하다 --- 앞엣것만 두면
 * 모르는 값을 찾을 수 없고, 뒤엣것만 두면 union에 값이 늘어도 라벨을 잊은 것이 드러나지
 * 않는다.
 *
 * `skip`도 여기 있지만 그것은 evidence가 아니다 --- 서버가 `mastery_probe_skipped`로
 * 기록하고 mastery도 FSRS도 건드리지 않는다(02_LEARNING_POLICY.md의 `Skip`).
 */
export const PROBE_LABELS: Readonly<Record<ProbeResponseValue, string>> &
  Readonly<Record<string, string | undefined>> = {
  known: '알고 있었음',
  uncertain: '애매함',
  unknown: '몰랐음',
  skip: '건너뛰기',
}

/** 모르는 값이면 원문을 돌려준다. 버튼이 사라지는 것보다 낫다. */
export function probeOptionLabel(value: string): string {
  return PROBE_LABELS[value] ?? value
}

export type ProbeOptions = {
  probe: Probe
  /** 이미 응답한 값. non-null이면 버튼을 잠근다. */
  answered: string | null
  /**
   * 서버가 이 노출의 evidence를 이미 갖고 있다(409). **무엇으로 기록됐는지는 모른다**
   * --- self-report가 먼저 기록했을 수 있다. 그래서 값을 말하지 않고 잠그기만 한다.
   */
  alreadyRecorded: boolean
  failure: string | null
  onRespond: (value: string) => void
}

export function renderProbe(options: ProbeOptions): HTMLElement {
  const { probe } = options

  const box = document.createElement('section')
  box.className = 'probe'
  box.setAttribute('aria-label', '이해도 확인')

  const prompt = document.createElement('p')
  prompt.className = 'probe-prompt'
  // 서버 문구 그대로다. 한국어 문장을 여기서 다시 쓰지 않는다.
  prompt.textContent = probe.prompt

  const expression = document.createElement('p')
  expression.className = 'probe-expression'
  expression.lang = 'ja'
  expression.textContent = probe.expression

  box.append(prompt, expression)

  if (options.answered !== null || options.alreadyRecorded) {
    const done = document.createElement('p')
    done.className = 'probe-answered'
    done.textContent = answeredText(options)
    box.append(done)
  } else {
    const buttons = document.createElement('div')
    buttons.className = 'probe-options'
    // payload 순서 그대로다. 정렬하거나 `skip`을 옮기지 않는다.
    for (const value of probe.options) {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'probe-option'
      button.textContent = probeOptionLabel(value)
      button.addEventListener('click', () => {
        options.onRespond(value)
      })
      buttons.append(button)
    }
    box.append(buttons)
  }

  if (options.failure !== null) {
    const failure = document.createElement('p')
    failure.className = 'panel-failure'
    failure.setAttribute('role', 'alert')
    failure.textContent = options.failure
    box.append(failure)
  }

  return box
}

/** 답한 값을 지어내지 않는다. 모르면 "이미 기록했습니다"로 끝낸다. */
function answeredText(options: ProbeOptions): string {
  if (options.answered === null) return '이미 기록했습니다.'
  if (options.answered === 'skip') return '건너뛰었습니다.'
  return `기록했습니다: ${probeOptionLabel(options.answered)}`
}
