// Nihongo Context frontend entry point.
//
// 부팅은 라우터를 시작하는 것뿐이다. **어떤 경우에도 API를 부르지 않는다**(불변식 14, ADR-022).
// 이 파일의 정적 import 그래프에는 api.ts·endpoints.ts·env.ts·private.ts가 없다. 로그인 영역은
// 아래 `enterLoginArea`의 동적 import 한 곳으로만 들어가고, 그 함수는 상단바 `로그인` 버튼의 click
// 리스너가 부르는 `openLogin`에서만 실행된다. 여기와 공개 화면은 `openLogin`을 값으로 넘기기만 한다.
//
// **service worker를 등록하지 않는다.** 이유는 `index.html`의 주석에 있고,
// `tests/unit/no-service-worker.test.ts`가 빌드 산출물에서 그 부재를 강제한다.
//
// **`beforeunload` / `pagehide` / `visibilitychange`에 아무것도 달지 않는다.** 이유는
// `ui/study.ts`의 모듈 주석에 있다. 문서 수준 리스너는 `routes.ts`의 `hashchange` 하나다.
import './styles.css'
import './ui/screens.css'

import { HOME_HASH, startRouter } from './routes'
import { MESSAGES, renderNotice } from './ui/notice'
import { showScreen } from './ui/screen'
import { renderTopBar } from './ui/topbar'

function boot(root: HTMLElement): void {
  const router = startRouter({ root, openLogin })

  function goHome(): void {
    router.navigate(HOME_HASH)
  }

  /** 상단바 `로그인`의 click 리스너만 부른다. */
  function openLogin(): void {
    void enterLoginArea()
  }

  /**
   * 로그인 진입(`03_UI_UX_SPEC.md`의 `로그인 진입`).
   *
   * 1. 지금 화면을 떠난다(signal abort)
   * 2. hash가 있으면 replaceState로 지운다 --- hashchange가 오지 않고, 로그인 영역에서 새로고침하면 홈이다
   * 3. 로그인 영역 모듈을 동적 import한다. 실패하면 버튼 없는 안내만 둔다(다시 시도는 상단바 `로그인`)
   * 4. 그사이 떠났으면 멈춘다. 아니면 enterPrivate
   */
  async function enterLoginArea(): Promise<void> {
    const signal = router.handOver()
    if (location.hash !== '') {
      history.replaceState(null, '', location.pathname + location.search)
    }

    // 청크 적재 실패, 오프라인, 배포로 옛 청크가 사라짐.
    const privateModule = await import('./private').catch(() => null)
    if (privateModule === null) {
      const screen = document.createElement('main')
      screen.className = 'screen load-failure'
      screen.append(
        renderTopBar({ onHome: goHome, onLogin: openLogin, actions: [] }),
        renderNotice(MESSAGES.loginAreaLoadFailed, 'error'),
      )
      showScreen(root, screen, signal)
      return
    }

    if (signal.aborted) return
    privateModule.enterPrivate({ root, signal, goHome, openLogin })
  }
}

const app = document.querySelector<HTMLElement>('#app')
if (app !== null) {
  boot(app)
}
