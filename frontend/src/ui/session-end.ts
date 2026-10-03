/**
 * 세션 종료 선택과 종료 후 화면.
 *
 * **연장 버튼 문구에 숫자를 적지 않는다.** 연장 길이는 `extra_session_minutes`이고 그
 * 값은 어떤 응답에도 실려 오지 않는다. `+5분 더`라고 적으면 그것은 정책값 하드코딩이고,
 * config를 바꾼 배포에서 버튼이 거짓을 말한다. 연장한 뒤에는 `extended_minutes`가 응답에
 * 실려 오므로 그때부터는 진행 표시가 실제 숫자를 보여준다(`ui/progress.ts`).
 *
 * 도달은 세션의 종료가 아니다(05_API_SPEC.md). 그래서 이 선택은 문장을 치우지 않고
 * 화면에 **덧붙는다** --- 둘 다 누르지 않으면 계속 읽을 수 있다. streak·overdue 압박
 * 문구를 두지 않는다(03_UI_UX_SPEC.md의 `Session End`).
 *
 * **도달이 가르는 것은 종료 버튼의 유무가 아니다.** `오늘 학습 완료`는 도달 전에도 항상
 * 보이고(`renderFinishButton`), 도달 전에 없는 것은 안내 문구와 `더 학습하기`뿐이다 ---
 * 도달 전에 세션을 끝낼 UI가 하나도 없으면 사용자가 그 세션에 갇힌다(03_UI_UX_SPEC.md의
 * `도달 전과 도달 후`, ADR-025 결정 2의 `개정 2 (2026-10-03)`).
 */

import type { StudySession } from '../types'

const FINISH_LABEL = '오늘 학습 완료'

export type SessionEndActions = {
  onFinish: () => void
  onExtend: () => void
}

/**
 * 도달 **전**의 종료 버튼. 진행 표시 바로 아래에 이것 하나만 둔다(03_UI_UX_SPEC.md의
 * `도달 전과 도달 후`).
 *
 * -   문구는 도달 후와 같다. 같은 동작(`/finish`)에 두 이름을 두지 않는다.
 * -   `오늘 목표한 시간을 채웠어요.`와 `더 학습하기`는 **없다** --- 둘 다 "도달했다"는
 *     뜻이라 도달 전에는 거짓이다.
 * -   **확인 단계를 두지 않는다.** `/finish`는 exposure·mastery·SRS를 하나도 지우지
 *     않으므로 파괴적 동작이 아니고(`로그아웃`과 같은 근거), 도달 후의 같은 버튼에도
 *     확인이 없다 --- 붙이면 같은 버튼이 상태에 따라 다르게 동작한다.
 */
export function renderFinishButton(onFinish: () => void): HTMLElement {
  const finish = document.createElement('button')
  finish.type = 'button'
  // 오탭은 자리와 위계로 막는다. 문장·`다음 문장`에서 떨어진 자리에 `secondary`로 둔다.
  finish.className = 'secondary session-finish'
  finish.textContent = FINISH_LABEL
  finish.addEventListener('click', onFinish)
  return finish
}

export function renderSessionEndChoice(actions: SessionEndActions): HTMLElement {
  const box = document.createElement('section')
  box.className = 'session-end'

  const text = document.createElement('p')
  text.className = 'session-end-text'
  text.textContent = '오늘 목표한 시간을 채웠어요.'

  const finish = document.createElement('button')
  finish.type = 'button'
  finish.className = 'primary'
  finish.textContent = FINISH_LABEL
  finish.addEventListener('click', actions.onFinish)

  const extend = document.createElement('button')
  extend.type = 'button'
  extend.className = 'secondary'
  // 03_UI_UX_SPEC.md의 `Session End`가 확정한 문구. 숫자를 넣지 않는다 ---
  // `extra_session_minutes`는 `/extend`를 부르기 전 어떤 응답에도 실려 있지 않다.
  extend.textContent = '더 학습하기'
  extend.addEventListener('click', actions.onExtend)

  const buttons = document.createElement('div')
  buttons.className = 'session-end-actions'
  buttons.append(finish, extend)

  box.append(text, buttons)
  return box
}

/** `/finish` 뒤의 화면. 여기서는 학습이 끝났으므로 문장도 Next도 없다. */
export function renderSessionFinished(session: StudySession): HTMLElement {
  const box = document.createElement('section')
  box.className = 'session-finished'

  const title = document.createElement('h1')
  title.className = 'session-finished-title'
  title.textContent = '오늘 학습을 마쳤어요.'

  const summary = document.createElement('p')
  summary.className = 'session-finished-summary'
  // 서버가 준 `active_seconds`만 쓴다. streak도 연속 일수도 계산하지 않는다.
  summary.textContent = `학습 시간 ${Math.floor(session.active_seconds / 60)}분`

  box.append(title, summary)
  return box
}
