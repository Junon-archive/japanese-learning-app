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
 * -   로그인 영역 안의 이동은 콜백이고 hash를 바꾸지 않는다. **그래도 화면마다 signal이 따로다.** 학습 ->
 *     기록처럼 영역 안에서 화면을 바꾸면 이전 화면의 signal을 abort한다. 떠난 학습 화면에 늦게 온
 *     `/click` 응답이 시트를 열거나 `explanation_revealed`를 보내지 못한다(05_API_SPEC.md).
 */

import { ApiError } from './api'
import { fetchMe } from './endpoints'
import { mountHistory } from './ui/history'
import { mountLogin } from './ui/login'
import { MESSAGES, renderNotice, showToast } from './ui/notice'
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

  /** 지금 로그인 영역 화면의 수명. */
  let screenController: AbortController | null = null

  /**
   * 다음 화면의 signal. 이전 화면의 signal을 abort하고, 로그인 영역을 떠나면(ctx.signal abort) 함께
   * abort된다. 이미 떠났으면 처음부터 abort된 signal이다.
   */
  function nextScreenSignal(): AbortSignal {
    screenController?.abort()
    const controller = new AbortController()
    screenController = controller
    if (signal.aborted) {
      controller.abort()
    } else {
      signal.addEventListener('abort', () => {
        controller.abort()
      })
    }
    return controller.signal
  }

  /**
   * auth session만 폐기됐다. study session은 서버에 열린 채 남고, 다시 로그인하면 resume된다
   * (03_UI_UX_SPEC.md의 `로그아웃`). 선택 홈으로 가고 한 번 사라지는 안내를 띄운다. 로그인 영역을 이미
   * 떠났으면(다른 공개 화면) 화면을 가로채지 않고 안내도 띄우지 않는다.
   */
  function loggedOut(): void {
    if (signal.aborted) return
    goHome()
    showToast(MESSAGES.loggedOut)
  }

  function showStudy(timezone: string): void {
    mountStudy(root, nextScreenSignal(), {
      onHome: goHome,
      onUnauthenticated: showLogin,
      onOpenHistory: () => {
        showHistory(timezone)
      },
      onLoggedOut: loggedOut,
    })
  }

  function showHistory(timezone: string): void {
    mountHistory(root, nextScreenSignal(), {
      timezone,
      onHome: goHome,
      onBack: () => {
        showStudy(timezone)
      },
      onUnauthenticated: showLogin,
      onLoggedOut: loggedOut,
    })
  }

  function showLogin(): void {
    mountLogin(root, nextScreenSignal(), {
      onHome: goHome,
      onAuthenticated: (user) => {
        // 로그인 응답이 `timezone`을 들고 온다. `GET /me`를 다시 부르지 않는다. 그사이 떠났으면
        // mountStudy가 그리지도 study session을 시작하지도 않는다.
        showStudy(user.timezone)
      },
    })
  }

  function showFailure(notice: HTMLElement): void {
    const screen = document.createElement('main')
    screen.className = 'screen login-check-failure'
    screen.append(renderTopBar({ onHome: goHome, onLogin: openLogin, actions: [] }), notice)
    showScreen(root, screen, nextScreenSignal())
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
