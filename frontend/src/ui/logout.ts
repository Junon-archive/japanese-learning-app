/**
 * 로그아웃 버튼 하나. `03_UI_UX_SPEC.md`의 `로그아웃` --- **새 화면을 만들지 않는다.**
 *
 * -   **확인 대화상자를 두지 않는다.** 잃는 것이 없다(학습 기록은 서버에 남는다) 되돌리는
 *     비용이 로그인 한 번이므로 파괴적 동작이 아니다.
 * -   **진행 중인 study session을 닫지 않는다.** 폐기되는 것은 auth session이고 다시
 *     로그인하면 idle timeout 이내인 세션은 resume된다. 그래서 여기서 `/finish`를 부르지
 *     않는다.
 * -   **실패하면 선택 홈으로 보내지 않는다.** 쿠키가 살아 있는데 화면만 로그아웃된
 *     상태를 만들면 그것은 거짓 표시다(`10_ERROR_HANDLING.md`). 그 자리에 문구만 띄우고
 *     버튼을 다시 눌 수 있게 둔다.
 * -   **401만 예외로 성공과 같다.** 폐기할 세션이 이미 없다는 뜻이므로 로그아웃한 결과(선택
 *     홈)가 옳다.
 * -   **계정 관리·설정 화면을 만들지 않는다.** 버튼 하나가 전부다.
 * -   **Demo에는 두지 않는다.** Demo는 Login 화면을 지나지 않아 폐기할 세션이 없다. 그래서
 *     이 모듈은 로그인 영역(`ui/study.ts`, `ui/history.ts`)의 상단바 메뉴로만 쓰인다. `ui/topbar.ts`와
 *     `demo/`는 import하지 않는다 --- 그러면 공개 화면의 import 그래프가 API에 닿는다.
 */

import { ApiError } from '../api'
import { logout } from '../endpoints'
import { errorMessage } from './api-failure'

export type LogoutActions = {
  /** 폐기됐다(또는 이미 없었다). 호출부가 선택 홈으로 보낸다. */
  onLoggedOut: () => void
  /** 폐기하지 못했다. 화면은 그대로 두고 문구만 띄운다. */
  onFailure: (message: string) => void
}

export function renderLogoutButton(actions: LogoutActions): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'topbar-button logout'
  button.textContent = '로그아웃'

  button.addEventListener('click', () => {
    if (button.disabled) return
    button.disabled = true

    logout()
      .then(() => {
        actions.onLoggedOut()
      })
      .catch((error: unknown) => {
        if (error instanceof ApiError && error.kind === 'Unauthenticated') {
          // 폐기할 세션이 이미 없다. 성공과 같은 결과다.
          actions.onLoggedOut()
          return
        }
        // 세션이 아직 살아 있을 수 있다. 다시 누를 수 있게 되돌린다.
        button.disabled = false
        actions.onFailure(errorMessage(error))
      })
  })

  return button
}
