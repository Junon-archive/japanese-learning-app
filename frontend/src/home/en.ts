/**
 * 영어 홈(`#/en`). `03_UI_UX_SPEC.md`의 `언어별 홈`, ADR-025 결정 1·2.
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 로그인 상태도 확인하지 않는다.
 *     상단바 `로그인`에는 main.ts가 주입한 `openLogin`을 넘기기만 한다.
 * -   **카드에 문장 수 숫자를 적지 않는다.**
 * -   **카드가 하나뿐이다.** 가나 학습에 대응하는 영어 보조 화면(파닉스, 발음기호 표)을 두지
 *     않는다 --- 범위 밖이고, 필요한 것은 글자가 아니다(ADR-025 결정 2).
 * -   언어 선택 홈(`#/`)으로 돌아가는 길은 상단바 앱 이름이다. 언어별 홈이 아니다.
 */

import type { PublicScreenContext } from '../routes'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'
import type { HomeCardSpec } from './card'
import { renderHomeCard } from './card'

const MESSAGES = {
  intro: '아는 단어인데 안 들리는 표현을 문장 속에서 익혀요.',
} as const

const CARDS: readonly HomeCardSpec[] = [
  {
    hash: '#/en/demo',
    title: '표현 학습 체험해 보기',
    description: '모르는 표현을 눌러 뜻을 확인해요.',
    pills: ['로그인 없이'],
  },
]

export function mount(ctx: PublicScreenContext): void {
  const { navigate } = ctx

  const screen = document.createElement('main')
  screen.className = 'screen home en-home'

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
