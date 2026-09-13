/**
 * 바텀시트. **item 설명에만 쓴다.** 번역·확인·오류는 시트가 아니다(03_UI_UX_SPEC.md의
 * `설명 시트`, ADR-022 결정 4).
 *
 * -   시트는 `container`(화면 요소) 안에 붙는다. 화면이 떼어지면 시트와 리스너도 함께 사라지므로
 *     정리 코드가 없다. 문서 수준 리스너를 달지 않는다 --- Esc는 시트 요소에 단다(열 때 포커스가
 *     시트 안으로 들어가므로 키 이벤트가 거기로 온다).
 * -   `body`는 호출자가 열 때 만든 내용이다. 숨겨 둔 노드를 재사용하지 않는다.
 * -   **닫으면 논리 상태가 즉시 바뀐다.** 가림막 뒤 화면의 `inert` 해제, 포커스 복귀, `onClose`가
 *     그 자리에서 일어나고, 시트 자신은 `inert`가 되어 조작을 받지 않는다. DOM에서 떼는 시각적
 *     숨김만 `transitionend`에서 한다. 그 이벤트가 오지 않아도(reduced-motion, 테스트) 조작은
 *     막히지 않는다.
 */

export type SheetHandle = { close: () => void }

const CLOSE_LABEL = '닫기'

let opened = 0

export function openSheet(options: {
  container: HTMLElement
  title: string
  body: HTMLElement
  returnFocusTo: HTMLElement | null
  onClose?: () => void
}): SheetHandle {
  const { container, title, body, returnFocusTo, onClose } = options
  opened += 1
  const titleId = `sheet-title-${opened}`

  const scrim = document.createElement('div')
  scrim.className = 'sheet-scrim'

  const sheet = document.createElement('div')
  sheet.className = 'sheet'
  sheet.setAttribute('role', 'dialog')
  sheet.setAttribute('aria-modal', 'true')
  sheet.setAttribute('aria-labelledby', titleId)

  const heading = document.createElement('h2')
  heading.className = 'sheet-title'
  heading.setAttribute('id', titleId)
  heading.setAttribute('tabindex', '-1')
  heading.textContent = title

  const closeButton = document.createElement('button')
  closeButton.type = 'button'
  closeButton.className = 'secondary sheet-close'
  closeButton.textContent = CLOSE_LABEL

  sheet.append(heading, body, closeButton)
  scrim.append(sheet)

  // 가림막 뒤의 화면. 이미 inert였던 요소는 닫을 때도 건드리지 않는다.
  const covered = (Array.from(container.children) as HTMLElement[]).filter((child) => !child.inert)

  let closed = false
  function close(): void {
    if (closed) return
    closed = true
    scrim.inert = true
    scrim.classList.add('is-closing')
    for (const child of covered) child.inert = false
    returnFocusTo?.focus({ preventScroll: true })
    onClose?.()
  }

  closeButton.addEventListener('click', close)
  scrim.addEventListener('click', (event) => {
    if (event.target === scrim) close()
  })
  sheet.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') close()
  })
  scrim.addEventListener('transitionend', (event) => {
    if (closed && event.target === scrim) scrim.remove()
  })

  container.append(scrim)
  for (const child of covered) child.inert = true
  heading.focus({ preventScroll: true })

  return { close }
}
