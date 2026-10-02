/**
 * 홈 화면 셋(언어 선택 홈, 일본어 홈, 영어 홈)이 공유하는 카드 렌더러. `03_UI_UX_SPEC.md`의
 * `상단바와 홈` 표 --- 세 화면 모두 **카드에 문장 수 숫자를 적지 않는다.**
 */

export type HomeCardSpec = {
  hash: string
  title: string
  description?: string
  pills?: string[]
}

export function renderHomeCard(card: HomeCardSpec, navigate: (hash: string) => void): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'card pressable home-card'

  const title = document.createElement('h2')
  title.className = 'home-card-title'
  title.textContent = card.title
  button.append(title)

  if (card.description !== undefined) {
    const description = document.createElement('p')
    description.className = 'home-card-desc'
    description.textContent = card.description
    button.append(description)
  }

  if (card.pills !== undefined && card.pills.length > 0) {
    const pills = document.createElement('div')
    pills.className = 'pills'
    for (const text of card.pills) {
      const pill = document.createElement('span')
      pill.className = 'pill'
      pill.textContent = text
      pills.append(pill)
    }
    button.append(pills)
  }

  button.addEventListener('click', () => {
    navigate(card.hash)
  })
  return button
}
