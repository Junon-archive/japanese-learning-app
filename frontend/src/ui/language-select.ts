/**
 * 언어 선택 화면(로그인 영역). `03_UI_UX_SPEC.md`의 `언어 선택 화면 (MVP-03)`, ADR-025 결정 2.
 *
 * 로그인 영역에 열린 study session이 없을 때만 보여준다 --- `GET /api/study/session`으로
 * 미리 가르는 것은 `private.ts`다. 고른 언어로 Study Screen에 들어가면 그 화면의 `begin()`이
 * `POST /api/study/session`을 부른다(이 화면은 직접 호출하지 않는다).
 *
 * **hash가 없다**(ADR-022). 상단바 오른쪽은 `로그아웃`뿐이다 --- 로그인 영역 안이고 문장이
 * 없어 후리가나 토글도 없다.
 */

import type { Language } from '../types'
import { renderLogoutButton } from './logout'
import { MESSAGES, renderNotice } from './notice'
import { showScreen } from './screen'
import { renderTopBar } from './topbar'

export type LanguageSelectActions = {
  /** 상단바 앱 이름. */
  onHome: () => void
  onSelect: (language: Language) => void
  /** 폐기됐다(또는 이미 없었다). 호출부가 선택 홈으로 보낸다. */
  onLoggedOut: () => void
}

const LANGUAGE_BUTTONS: readonly { language: Language; label: string }[] = [
  { language: 'ja', label: MESSAGES.languageJa },
  { language: 'en', label: MESSAGES.languageEn },
]

export function mountLanguageSelect(
  root: HTMLElement,
  signal: AbortSignal,
  actions: LanguageSelectActions,
): void {
  const screen = document.createElement('main')
  screen.className = 'screen language-select'

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  const logoutButton = renderLogoutButton({
    onLoggedOut: actions.onLoggedOut,
    onFailure: (message) => {
      noticeSlot.replaceChildren(renderNotice(message, 'error'))
    },
  })

  const title = document.createElement('h1')
  title.className = 'language-select-title'
  title.textContent = MESSAGES.languageSelectTitle

  const cards = document.createElement('div')
  cards.className = 'home-cards'
  cards.append(
    ...LANGUAGE_BUTTONS.map(({ language, label }) => {
      const button = document.createElement('button')
      button.type = 'button'
      button.className = 'card pressable home-card'
      button.textContent = label
      button.addEventListener('click', () => {
        actions.onSelect(language)
      })
      return button
    }),
  )

  screen.append(
    renderTopBar({ onHome: actions.onHome, actions: [logoutButton] }),
    title,
    noticeSlot,
    cards,
  )
  showScreen(root, screen, signal)
}
