/**
 * 언어 선택 홈(`#/`). `03_UI_UX_SPEC.md`의 `언어 선택 홈`, ADR-025 결정 1·2.
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 로그인 상태도 확인하지 않는다.
 *     상단바 `로그인`에는 main.ts가 주입한 `openLogin`을 넘기기만 한다.
 * -   **카드에 문장 수 숫자를 적지 않는다.**
 * -   로그인·계정 관리·통계로 가는 카드를 두지 않는다. 카드는 둘(일본어, 영어)이다.
 */

import type { PublicScreenContext } from '../routes'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'
import type { HomeCardSpec } from './card'
import { renderHomeCard } from './card'

const MESSAGES = {
  intro: '실제 문장 속에서 표현을 익히는 앱이에요.',
} as const

const CARDS: readonly HomeCardSpec[] = [
  { hash: '#/ja', title: '일본어', description: '문장 속 표현과 한자 읽기를 익혀요.' },
  { hash: '#/en', title: '영어', description: '드라마와 대화에서 실제로 쓰는 표현을 익혀요.' },
]

export function mount(ctx: PublicScreenContext): void {
  const { navigate } = ctx

  const screen = document.createElement('main')
  screen.className = 'screen home language-select-home'

  const intro = document.createElement('h1')
  intro.className = 'home-intro'
  intro.textContent = MESSAGES.intro

  const cards = document.createElement('div')
  cards.className = 'home-cards'
  cards.append(...CARDS.map((card) => renderHomeCard(card, navigate)))

  screen.append(
    renderTopBar({ onHome: () => navigate('#/'), onLogin: ctx.openLogin, actions: [] }),
    intro,
    cards,
  )
  showScreen(ctx.root, screen, ctx.signal)
}
