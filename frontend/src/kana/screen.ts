/**
 * 가나 학습 화면(`#/kana`). `03_UI_UX_SPEC.md`의 `가나 학습`.
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 상단바 `로그인`에는 main.ts가 주입한
 *     `openLogin`을 넘기기만 한다.
 */

import type { PublicScreenContext } from '../routes'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'

export function mount(ctx: PublicScreenContext): void {
  const screen = document.createElement('main')
  screen.className = 'screen kana'

  const title = document.createElement('h1')
  title.className = 'kana-title'
  title.textContent = '글자 배우기'

  screen.append(
    renderTopBar({ onHome: () => ctx.navigate('#/'), onLogin: ctx.openLogin, actions: [] }),
    title,
  )
  showScreen(ctx.root, screen, ctx.signal)
}
