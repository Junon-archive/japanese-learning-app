/**
 * 상단바 레이아웃. **동작은 주입받는다**(03_UI_UX_SPEC.md의 `상단바`, ADR-022 결정 4).
 *
 * -   왼쪽은 앱 이름이고 누르면 `onHome`.
 * -   오른쪽은 각 영역이 만든 `actions`(학습 기록, 로그아웃, 후리가나 토글)를 순서대로 둔다.
 *     이 모듈은 로그아웃 코드를 import하지 않는다 --- 그러면 공개 화면의 import 그래프가 API에
 *     닿는다.
 * -   `onLogin`이 있으면 맨 오른쪽에 `로그인` 버튼을 만든다. **`onLogin`은 그 버튼의 `click`
 *     리스너 안에서만 부른다**(불변식 14). 누르면 버튼을 비활성으로 두고 `확인 중`으로 적은 뒤
 *     부른다. 두 번 눌러도 한 번이다. 다시 누를 수 있는 상태는 로그인 진입이 그리는 다음 화면의
 *     새 상단바가 만든다.
 */

const APP_NAME = 'Nihongo Context'
const LOGIN_LABEL = '로그인'
const LOGIN_CHECKING_LABEL = '확인 중'

export function renderTopBar(options: {
  onHome: () => void
  onLogin?: () => void
  actions: HTMLElement[]
}): HTMLElement {
  const bar = document.createElement('header')
  bar.className = 'topbar'

  const home = document.createElement('button')
  home.type = 'button'
  home.className = 'topbar-button topbar-brand'
  home.textContent = APP_NAME
  const { onHome } = options
  home.addEventListener('click', () => {
    onHome()
  })

  const right = document.createElement('div')
  right.className = 'topbar-actions'
  right.append(...options.actions)

  const { onLogin } = options
  if (onLogin !== undefined) {
    const login = document.createElement('button')
    login.type = 'button'
    login.className = 'topbar-button topbar-login'
    login.textContent = LOGIN_LABEL
    login.addEventListener('click', () => {
      if (login.disabled) return
      login.disabled = true
      login.textContent = LOGIN_CHECKING_LABEL
      onLogin()
    })
    right.append(login)
  }

  bar.append(home, right)
  return bar
}
