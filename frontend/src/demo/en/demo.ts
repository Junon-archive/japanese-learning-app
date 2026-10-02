/**
 * 영어 Public Demo(`#/en/demo`) placeholder. **이 레인(home-route)은 route 연결만 책임진다** ---
 * 실제 화면(fixture, 탭, 설명 시트, 재생 버튼)은 `demo-en` 레인이 이어서 만든다(ADR-025 결정 1·3).
 *
 * 지금은 공개 route가 가리킬 자리만 있다. 그래도 공개 화면의 규칙은 그대로 지킨다 ---
 * **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13).
 */

import type { PublicScreenContext } from '../../routes'
import { showScreen } from '../../ui/screen'
import { renderTopBar } from '../../ui/topbar'

export function mount(ctx: PublicScreenContext): void {
  const screen = document.createElement('main')
  screen.className = 'screen demo en-demo-placeholder'

  const title = document.createElement('h1')
  title.className = 'visually-hidden'
  title.textContent = '표현 학습 체험'

  screen.append(
    renderTopBar({ onHome: () => ctx.navigate('#/'), onLogin: ctx.openLogin, actions: [] }),
    title,
  )
  showScreen(ctx.root, screen, ctx.signal)
}
