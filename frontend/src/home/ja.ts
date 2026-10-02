/**
 * 일본어 홈(`#/ja`). `03_UI_UX_SPEC.md`의 `언어별 홈`, ADR-025 결정 1·2.
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 로그인 상태도 확인하지 않는다.
 *     상단바 `로그인`에는 main.ts가 주입한 `openLogin`을 넘기기만 한다.
 * -   **카드에 문장 수 숫자를 적지 않는다.**
 * -   언어 선택 홈(`#/`)으로 돌아가는 길은 상단바 앱 이름이다. 언어별 홈이 아니다.
 */

import type { PublicScreenContext } from '../routes'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'
import type { HomeCardSpec } from './card'
import { renderHomeCard } from './card'

const MESSAGES = {
  intro: '일본어 표현을 실제 문장 속에서 익히는 앱이에요.',
} as const

const CARDS: readonly HomeCardSpec[] = [
  {
    hash: '#/ja/demo',
    title: '표현 학습 체험해 보기',
    description: '모르는 표현을 눌러 뜻을 확인해요.',
    pills: ['로그인 없이'],
  },
  {
    hash: '#/ja/kana',
    title: '글자부터 배우기',
    description: '히라가나와 가타카나를 표와 퀴즈로 익혀요.',
    pills: ['히라가나', '가타카나'],
  },
]

export function mount(ctx: PublicScreenContext): void {
  const { navigate } = ctx

  const screen = document.createElement('main')
  screen.className = 'screen home ja-home'

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
