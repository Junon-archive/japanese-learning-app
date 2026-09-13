/**
 * 화면 교체. 화면 모듈은 root를 직접 비우지 않고 이 함수를 쓴다(03_UI_UX_SPEC.md의
 * `화면 전환과 시트`, ADR-022 결정 4).
 *
 * -   **`signal`이 abort됐으면 아무것도 하지 않는다.** 다른 화면으로 떠난 뒤 늦게 온 응답이
 *     지금 화면을 덮지 못하게 한다.
 * -   **DOM은 즉시 바뀐다.** 나가는 화면은 애니메이션하지 않고, 들어오는 화면의 진입 움직임은
 *     CSS(`.screen-enter`)뿐이다. 애니메이션 이벤트를 기다리는 논리가 없다.
 * -   맨 위로 즉시 스크롤하고 화면의 첫 `h1`에 포커스를 둔다. `h1`이 없는 화면은 포커스를
 *     옮기지 않는다.
 */

const ENTER_CLASS = 'screen-enter'

export function showScreen(root: HTMLElement, screen: HTMLElement, signal: AbortSignal): void {
  if (signal.aborted) return

  root.replaceChildren(screen)
  screen.classList.add(ENTER_CLASS)
  document.documentElement.scrollTop = 0

  const title = screen.querySelector('h1')
  if (title === null) return
  if (title.getAttribute('tabindex') === null) title.setAttribute('tabindex', '-1')
  title.focus({ preventScroll: true })
}
