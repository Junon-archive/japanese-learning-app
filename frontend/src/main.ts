// Nihongo Context frontend entry point.
//
// 부트와 화면 전환만 한다. 라우터 라이브러리도 상태관리 레이어도 두지 않는다 --- 화면은
// `login` / `study` / `history` / `demo` 넷이고, 전환 조건은 부트 시점의 hash와
// "`GET /api/auth/me`가 401인가" 둘뿐이다.
//
// **`#/demo`는 인증을 지나지 않는다.** demo는 static fixture이고 backend API를 호출하지
// 않으므로 로그인할 이유가 없다(`04_SECURITY_AND_DATA.md`). 그래서 `fetchMe()`보다
// **먼저** 갈린다 --- 뒤에 두면 서버가 죽었을 때 demo도 함께 막힌다.
//
// **service worker를 등록하지 않는다.** 이유는 `index.html`의 주석에 있고,
// `tests/unit/no-service-worker.test.ts`가 빌드 산출물에서 그 부재를 강제한다.
//
// **`beforeunload` / `pagehide` / `visibilitychange`에 아무것도 달지 않는다.** 이유는
// `ui/study.ts`의 모듈 주석에 있다. `hashchange`도 듣지 않는다 --- hash는 진입 경로일
// 뿐이고 화면 전환은 사용자가 누른 버튼이 직접 한다.
import './styles.css'
import './ui/screens.css'

import { ApiError } from './api'
import { mountDemo } from './demo/demo'
import { fetchMe } from './endpoints'
import { errorMessage } from './ui/api-failure'
import { mountHistory } from './ui/history'
import { mountLogin } from './ui/login'
import { MESSAGES, renderNotice } from './ui/notice'
import { mountStudy } from './ui/study'

const DEMO_ROUTE = '#/demo'

/**
 * 로그인한 사용자의 `timezone`을 화면들에 내려준다.
 *
 * 출처는 부팅의 `GET /api/auth/me`와 로그인 응답 둘뿐이다 --- **이 값을 위해 새 요청을
 * 만들지 않는다.** history 날짜가 `users.timezone` 기준이어야 하기 때문에 필요하다
 * (`04_DB_SPEC.md` 공통 규칙: 사용자 local day 경계는 `users.timezone`으로 계산한다).
 * `Asia/Seoul`을 여기 적지 않는다 --- 기본값은 서버 컬럼의 것이다.
 */
function showStudy(root: HTMLElement, timezone: string): void {
  mountStudy(root, {
    onUnauthenticated: () => {
      // 학습 중 401. 세션 cookie가 만료됐다는 뜻이므로 로그인 화면으로 돌아간다.
      showLogin(root)
    },
    onOpenHistory: () => {
      showHistory(root, timezone)
    },
    onLoggedOut: () => {
      // auth session이 폐기됐다. study session은 서버에 열린 채 남아 있고, 다시
      // 로그인하면 idle timeout 이내면 resume된다(03_UI_UX_SPEC.md의 `로그아웃`).
      showLogin(root)
    },
  })
}

function showHistory(root: HTMLElement, timezone: string): void {
  mountHistory(root, {
    timezone,
    onBack: () => {
      showStudy(root, timezone)
    },
    onUnauthenticated: () => {
      showLogin(root)
    },
  })
}

/**
 * Demo를 띄운다. 나올 때는 **들어오기 직전 화면으로 되돌린다.**
 *
 * `exitTo`가 파라미터인 이유가 이 기능의 불변식이다: **demo는 어느 경로에서도 네트워크
 * 요청을 만들지 않는다**(`04_SECURITY_AND_DATA.md`, `05_API_SPEC.md`). 종료 시
 * `GET /api/auth/me`로 인증 여부를 확인하면 그것만으로 요청이 나가고(백엔드가 없는
 * 구성에서는 재시도 정책 때문에 여러 번) 불변식이 깨진다. 그래서 **이미 가진 정보로만**
 * 돌아간다.
 *
 * -   로그인 화면에서 들어왔으면 로그인 화면으로.
 * -   인증된 화면에서 들어왔다면 그 화면으로 --- 메모리에 이미 있는 `User`(의 `timezone`)를
 *     그대로 재사용하는 `exitTo`를 넘긴다. 지금 그런 진입점은 없지만, 생기면 여기서
 *     `() => showStudy(root, timezone)`을 넘기는 것이 전부이고 요청은 여전히 0건이다.
 * -   주소창에 `#/demo`를 직접 쳐서 들어왔으면 앞선 화면이 없으므로 로그인 화면으로.
 *     인증 여부를 확인하려면 요청이 필요하므로 **확인하지 않는다.** 그 사용자는 새로고침
 *     한 번으로 자기 화면으로 복귀한다.
 *
 * 종료 콜백은 이렇게 여기서 주입한다. `demo.ts`는 자기가 무엇으로 돌아가는지 모른다 ---
 * 알면 demo가 인증 경로를 import하게 되고 격리가 깨진다.
 */
function showDemo(root: HTMLElement, exitTo: () => void): void {
  mountDemo(root, () => {
    location.hash = ''
    exitTo()
  })
}

function showLogin(root: HTMLElement): void {
  mountLogin(
    root,
    (user) => {
      // 로그인 응답이 `timezone`을 들고 온다(05_API_SPEC.md). `GET /me`를 다시 부르지 않는다.
      showStudy(root, user.timezone)
    },
    () => {
      location.hash = DEMO_ROUTE
      // 들어온 곳이 로그인 화면이므로 나가는 곳도 로그인 화면이다. 요청 없음.
      showDemo(root, () => {
        showLogin(root)
      })
    },
  )
}

async function boot(root: HTMLElement): Promise<void> {
  if (location.hash === DEMO_ROUTE) {
    // 앞선 화면이 없다. 나갈 때 인증 여부를 확인하지 않는다(그러면 요청이 나간다).
    showDemo(root, () => {
      showLogin(root)
    })
    return
  }

  let user
  try {
    user = await fetchMe()
  } catch (error) {
    if (error instanceof ApiError && error.kind === 'Unauthenticated') {
      showLogin(root)
      return
    }
    // 403(Origin 거부)과 Transient. 자동 재시도 루프를 만들지 않는다.
    root.replaceChildren(
      renderNotice(errorMessage(error), 'error', {
        label: MESSAGES.retry,
        onClick: () => {
          void boot(root)
        },
      }),
    )
    return
  }
  showStudy(root, user.timezone)
}

const app = document.querySelector<HTMLElement>('#app')
if (app !== null) {
  void boot(app)
}
