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
 */

import type { StudySession } from '../types'

export type SessionEndActions = {
  onFinish: () => void
  onExtend: () => void
}

export function renderSessionEndChoice(actions: SessionEndActions): HTMLElement {
  const box = document.createElement('section')
  box.className = 'session-end'

  const text = document.createElement('p')
  text.className = 'session-end-text'
  text.textContent = '오늘 목표한 학습 시간을 채웠습니다.'

  const finish = document.createElement('button')
  finish.type = 'button'
  finish.className = 'primary'
  finish.textContent = '오늘 학습 완료'
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
  title.textContent = '오늘 학습을 마쳤습니다.'

  const summary = document.createElement('p')
  summary.className = 'session-finished-summary'
  // 서버가 준 `active_seconds`만 쓴다. streak도 연속 일수도 계산하지 않는다.
  summary.textContent = `학습 시간 ${Math.floor(session.active_seconds / 60)}분`

  box.append(title, summary)
  return box
}
