/**
 * 로그인 영역(Login, Study Screen, History). `03_UI_UX_SPEC.md`의 `로그인 진입`, ADR-022 결정 1·5.
 *
 * **`fetchMe`와 API 모듈은 여기서부터만 닿는다.** 이 모듈로 들어오는 간선은 `main.ts`의 동적 import
 * 하나이고, 그것은 상단바 `로그인`을 누를 때만 실행된다(불변식 14).
 *
 * ``` text
 * GET /api/auth/me   200        Study Screen
 *                    401        Login
 *                    403        출처 거부 문구만 (버튼 없음. 다시 불러도 같은 403이다)
 *                    그 밖      인라인 안내 + [다시 시도하기] (fetchMe만 다시 부른다)
 * ```
 *
 * -   **`signal`이 abort됐으면 새 화면 진입 요청을 시작하지 않는다.** `fetchMe` 직전과 응답 뒤에 확인한다.
 *     떠난 뒤 늦게 온 200이 학습 화면을 그리거나 study session을 만들지 못한다.
 * -   실패 화면의 상단바 오른쪽은 `로그인`이다. 누르면 로그인 진입을 처음부터 다시 한다 --- 그 동작은
 *     `openLogin`이고 여기서는 `renderTopBar`에 **값으로만** 넘긴다.
 * -   로그인 영역 안의 이동은 콜백이고 hash를 바꾸지 않는다.
 */

import { ApiError } from './api'
import { fetchMe } from './endpoints'
import { mountHistory } from './ui/history'
import { mountLogin } from './ui/login'
import { MESSAGES, renderNotice } from './ui/notice'
import { showScreen } from './ui/screen'
import { mountStudy } from './ui/study'
import { renderTopBar } from './ui/topbar'

export type PrivateContext = {
  root: HTMLElement
  signal: AbortSignal
  goHome: () => void
  /** main.ts의 로그인 진입. 실패 화면 상단바의 `로그인`에 넘기기만 한다. */
  openLogin: () => void
}

export function enterPrivate(ctx: PrivateContext): void {
  const { root, signal, goHome, openLogin } = ctx

  function showStudy(timezone: string): void {
    mountStudy(root, {
      onUnauthenticated: showLogin,
      onOpenHistory: () => {
        showHistory(timezone)
      },
      // auth session만 폐기됐다. study session은 서버에 열린 채 남는다(03_UI_UX_SPEC.md의 `로그아웃`).
      onLoggedOut: goHome,
    })
  }

  function showHistory(timezone: string): void {
    mountHistory(root, {
      timezone,
      onBack: () => {
        showStudy(timezone)
      },
      onUnauthenticated: showLogin,
    })
  }

  function showLogin(): void {
    mountLogin(root, (user) => {
      // 로그인 응답이 `timezone`을 들고 온다. `GET /me`를 다시 부르지 않는다.
      showStudy(user.timezone)
    })
  }

  function showFailure(notice: HTMLElement): void {
    const screen = document.createElement('main')
    screen.className = 'screen login-check-failure'
    screen.append(renderTopBar({ onHome: goHome, onLogin: openLogin, actions: [] }), notice)
    showScreen(root, screen, signal)
  }

  let checking = false

  async function checkLogin(): Promise<void> {
    if (checking || signal.aborted) return
    checking = true
    try {
      const user = await fetchMe()
      if (signal.aborted) return
      showStudy(user.timezone)
    } catch (error) {
      if (signal.aborted) return
      if (error instanceof ApiError && error.kind === 'Unauthenticated') {
        showLogin()
        return
      }
      if (error instanceof ApiError && error.kind === 'OriginRejected') {
        showFailure(renderNotice(MESSAGES.originRejected, 'error'))
        return
      }
      // 자동 재시도 루프를 만들지 않는다. 사용자가 누른다.
      showFailure(
        renderNotice(MESSAGES.loginCheckFailed, 'error', {
          label: MESSAGES.retry,
          onClick: () => {
            void checkLogin()
          },
        }),
      )
    } finally {
      checking = false
    }
  }

  void checkLogin()
}
