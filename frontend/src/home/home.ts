/**
 * 선택 홈. `03_UI_UX_SPEC.md`의 `선택 홈` --- 방문자가 무슨 앱인지 바로 알 수 있어야 한다.
 *
 * -   **서버 요청 0건이고 API 모듈을 import하지 않는다**(불변식 13). 로그인 상태도 확인하지 않는다.
 *     상단바 `로그인`에는 main.ts가 주입한 `openLogin`을 넘기기만 한다.
 * -   **카드에 문장 수 숫자를 적지 않는다.**
 * -   로그인·계정 관리·통계로 가는 카드를 두지 않는다. 카드는 둘이다.
 */

import type { PublicScreenContext } from '../routes'
import { showScreen } from '../ui/screen'
import { renderTopBar } from '../ui/topbar'

const HOME_MESSAGES = {
  intro: '일본어 표현을 실제 문장 속에서 익히는 앱이에요.',
} as const

type HomeCard = { hash: string; title: string; description: string; pills: string[] }

const CARDS: readonly HomeCard[] = [
  {
    hash: '#/demo',
    title: '표현 학습 체험해 보기',
    description: '모르는 표현을 눌러 뜻을 확인해요.',
    pills: ['로그인 없이'],
  },
  {
    hash: '#/kana',
    title: '글자부터 배우기',
    description: '히라가나와 가타카나를 표와 퀴즈로 익혀요.',
    pills: ['히라가나', '가타카나'],
  },
]

function renderCard(card: HomeCard, navigate: (hash: string) => void): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'card pressable home-card'

  const title = document.createElement('h2')
  title.className = 'home-card-title'
  title.textContent = card.title

  const description = document.createElement('p')
  description.className = 'home-card-desc'
  description.textContent = card.description

  const pills = document.createElement('div')
  pills.className = 'pills'
  for (const text of card.pills) {
    const pill = document.createElement('span')
    pill.className = 'pill'
    pill.textContent = text
    pills.append(pill)
  }

  button.append(title, description, pills)
  button.addEventListener('click', () => {
    navigate(card.hash)
  })
  return button
}

export function mount(ctx: PublicScreenContext): void {
  const { navigate } = ctx

  const screen = document.createElement('main')
  screen.className = 'screen home'

  const intro = document.createElement('h1')
  intro.className = 'home-intro'
  intro.textContent = HOME_MESSAGES.intro

  const cards = document.createElement('div')
  cards.className = 'home-cards'
  cards.append(...CARDS.map((card) => renderCard(card, navigate)))

  screen.append(
    renderTopBar({ onHome: () => navigate('#/'), onLogin: ctx.openLogin, actions: [] }),
    intro,
    cards,
  )
  showScreen(ctx.root, screen, ctx.signal)
}
