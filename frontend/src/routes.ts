/**
 * 공개 route 표와 라우터. `03_UI_UX_SPEC.md`의 `화면 이동`, ADR-022 결정 1·5, ADR-025 결정 1.
 *
 * ``` text
 * hash                        화면              적재        언어
 * ''  '#/'                    언어 선택 홈      정적        -
 * '#/ja'                      일본어 홈         정적        ja
 * '#/ja/demo'                 일본어 demo       동적        ja
 * '#/ja/kana'  '#/ja/kana/<s>' 가나 학습        동적        ja
 * '#/en'                      영어 홈           정적        en
 * '#/en/demo'                 영어 demo         동적        en
 * '#/demo'                    -> '#/ja/demo'    replaceState 뒤 그 route를 적용한다
 * '#/kana' '#/kana/<s>'       -> '#/ja/kana...' 같다
 * 그 밖의 hash                 언어 선택 홈      replaceState로 '#/'
 * (hash 없음)                 로그인 영역        main.ts의 로그인 진입만 들어간다
 * ```
 *
 * -   **route 표가 언어를 들고 있다.** 화면 모듈은 `ctx.language`를 받고, 자기가 어느 언어인지
 *     문자열을 스스로 정하지 않는다(ADR-025 결정 1). 언어 선택 홈은 언어가 없으므로 `null`이다.
 * -   **이 파일은 API에 닿지 않는다.** 공개 화면은 서버 요청 0건이고(불변식 13) 로그인 상태도 확인하지
 *     않는다(불변식 14). 로그인 진입(`openLogin`)은 `main.ts`가 주입하고, 여기서는 화면에 **값으로만**
 *     넘긴다. 부르지 않는다.
 * -   **`hashchange` 리스너와 지금 화면의 `AbortController`는 이 파일에만 있다.** 화면이 바뀌면 옛
 *     화면의 signal을 abort한다. 늦게 온 응답·늦게 끝난 동적 import가 새 화면을 덮지 못한다.
 * -   **URL 값은 비교만 한다.** hash와 하위 경로를 화면에 출력하지 않는다. 하위 경로는 그것을 허용한다고
 *     선언한 route만 받고, 그 이름이 맞는지는 화면 모듈이 자기 허용 목록과 비교한다.
 * -   history state 인자는 `null`뿐이다.
 * -   **옛 경로 리다이렉트**(`#/demo`, `#/kana`, `#/kana/<하위>`)는 route 적용 **전에**
 *     `history.replaceState`로 URL만 바꾸고(pushState 아님. 뒤로 가기에 옛 경로를 남기지 않는다)
 *     그 자리에서 새 경로를 적용한다. 한 단계다 --- 새 경로가 또 리다이렉트 대상이 되는 표를
 *     만들지 않는다.
 */

import { mount as mountEnHome } from './home/en'
import { mount as mountJaHome } from './home/ja'
import { mount as mountLanguageSelectHome } from './home/language-select'
import type { Language } from './types'
import { MESSAGES, renderNotice } from './ui/notice'
import { showScreen } from './ui/screen'
import { renderTopBar } from './ui/topbar'

export type PublicScreenContext = {
  root: HTMLElement
  /** 다른 화면으로 가면 abort된다. */
  signal: AbortSignal
  /** `'#/ja/kana/hiragana'` -> `'hiragana'`. 없으면 `''`. 화면에 출력하지 않는다. */
  subpath: string
  navigate: (hash: string) => void
  /** main.ts가 주입한다. 공개 화면은 `renderTopBar`의 `onLogin`으로 넘기기만 한다. */
  openLogin: () => void
  /** 이 route의 언어. 언어 선택 홈(`#/`)은 언어가 없으므로 `null`이다(ADR-025 결정 1). */
  language: Language | null
}

export type PublicScreenModule = { mount: (ctx: PublicScreenContext) => void }

export type PublicRoute = {
  prefix: string
  load: () => Promise<PublicScreenModule>
  /** 동적 import가 실패했을 때 화면에 남기는 문구. 정적으로 번들된 route(언어별 홈)는 실패하지
   * 않으므로 이 값을 쓰지 않는다. */
  loadFailure: string
  /** `prefix/<하위>`를 이 route로 받는가. 받지 않으면 하위 경로가 붙은 hash는 모르는 hash다. */
  acceptsSubpath: boolean
  language: Language
}

export const HOME_HASH = '#/'
export const JA_HOME_HASH = '#/ja'
export const EN_HOME_HASH = '#/en'

export const PUBLIC_ROUTES: readonly PublicRoute[] = [
  {
    // 정적 적재(ADR-025 결정 1) --- 동적 import 실패가 있을 수 없으므로 `load`가 바로
    // resolve하는 Promise를 돌려준다. 번들은 `mountJaHome`을 평범한 static import로 받는다.
    prefix: JA_HOME_HASH,
    load: () => Promise.resolve({ mount: mountJaHome }),
    loadFailure: '',
    acceptsSubpath: false,
    language: 'ja',
  },
  {
    prefix: '#/ja/demo',
    load: () => import('./demo/demo'),
    loadFailure: MESSAGES.demoLoadFailed,
    acceptsSubpath: false,
    language: 'ja',
  },
  {
    prefix: '#/ja/kana',
    load: () => import('./kana/screen'),
    loadFailure: MESSAGES.kanaLoadFailed,
    acceptsSubpath: true,
    language: 'ja',
  },
  {
    prefix: EN_HOME_HASH,
    load: () => Promise.resolve({ mount: mountEnHome }),
    loadFailure: '',
    acceptsSubpath: false,
    language: 'en',
  },
  {
    prefix: '#/en/demo',
    load: () => import('./demo/en/demo'),
    loadFailure: MESSAGES.demoLoadFailed,
    acceptsSubpath: false,
    language: 'en',
  },
]

/** 옛 평면 route -> 새 중첩 route(ADR-025 결정 1의 `옛 경로 리다이렉트`). */
const LEGACY_REDIRECTS: readonly { prefix: string; to: string }[] = [
  { prefix: '#/demo', to: '#/ja/demo' },
  { prefix: '#/kana', to: '#/ja/kana' },
]

/** 옛 경로면 새 경로를 돌려준다. 하위 경로가 있으면 그대로 옮긴다(`#/kana/hiragana` -> `#/ja/kana/hiragana`). */
function redirectLegacyHash(hash: string): string | null {
  for (const { prefix, to } of LEGACY_REDIRECTS) {
    if (hash === prefix) return to
    if (hash.startsWith(`${prefix}/`)) return `${to}${hash.slice(prefix.length)}`
  }
  return null
}

export type ResolvedHash =
  | { kind: 'home' }
  | { kind: 'unknown' }
  | { kind: 'route'; route: PublicRoute; subpath: string }

/** hash -> 화면. 순수 함수다. 허용 목록(route 표)과 비교만 한다. */
export function resolveHash(
  hash: string,
  routes: readonly PublicRoute[] = PUBLIC_ROUTES,
): ResolvedHash {
  if (hash === '' || hash === HOME_HASH) return { kind: 'home' }
  for (const route of routes) {
    if (hash === route.prefix) return { kind: 'route', route, subpath: '' }
    if (route.acceptsSubpath && hash.startsWith(`${route.prefix}/`)) {
      return { kind: 'route', route, subpath: hash.slice(route.prefix.length + 1) }
    }
  }
  return { kind: 'unknown' }
}

function isHome(hash: string): boolean {
  return hash === '' || hash === HOME_HASH
}

export type Router = {
  navigate: (hash: string) => void
  /**
   * 지금 화면을 떠나고(그 signal을 abort) 다음 화면의 signal을 준다. 로그인 진입이 hash 없이 화면을
   * 넘겨받을 때 쓴다.
   */
  handOver: () => AbortSignal
}

export function startRouter(options: { root: HTMLElement; openLogin: () => void }): Router {
  const { root, openLogin } = options
  let current = new AbortController()

  function handOver(): AbortSignal {
    current.abort()
    current = new AbortController()
    return current.signal
  }

  function navigate(hash: string): void {
    if (hash === location.hash || (isHome(hash) && isHome(location.hash))) {
      // hash가 그대로면 hashchange가 오지 않는다. 직접 적용한다.
      applyRoute(hash)
      return
    }
    location.hash = hash
  }

  function context(signal: AbortSignal, subpath: string, language: Language | null): PublicScreenContext {
    return { root, signal, subpath, navigate, openLogin, language }
  }

  function showLoadFailure(message: string, signal: AbortSignal): void {
    const screen = document.createElement('main')
    screen.className = 'screen load-failure'
    screen.append(
      renderTopBar({ onHome: () => navigate(HOME_HASH), onLogin: openLogin, actions: [] }),
      renderNotice(message, 'error'),
    )
    showScreen(root, screen, signal)
  }

  function applyRoute(hash: string): void {
    const redirectTo = redirectLegacyHash(hash)
    if (redirectTo !== null) {
      history.replaceState(null, '', redirectTo)
      applyRoute(redirectTo)
      return
    }

    const signal = handOver()
    const resolved = resolveHash(hash)

    if (resolved.kind !== 'route') {
      if (resolved.kind === 'unknown') history.replaceState(null, '', HOME_HASH)
      mountLanguageSelectHome(context(signal, '', null))
      return
    }

    const { route, subpath } = resolved
    route.load().then(
      (module) => {
        if (signal.aborted) return
        module.mount(context(signal, subpath, route.language))
      },
      () => {
        showLoadFailure(route.loadFailure, signal)
      },
    )
  }

  window.addEventListener('hashchange', () => {
    applyRoute(location.hash)
  })
  applyRoute(location.hash)

  return { navigate, handOver }
}
