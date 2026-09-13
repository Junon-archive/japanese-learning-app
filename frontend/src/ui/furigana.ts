/**
 * 후리가나 설정과 토글(03_UI_UX_SPEC.md의 `Translation/Furigana`, ADR-022 결정 5).
 *
 * -   설정은 `nc.furigana.v1` 하나이고 Study Screen과 Demo가 공유한다. 저장값이 정확히 `{"on": true}`일 때만
 *     켬이고, 없거나 형식이 틀리거나 읽을 수 없으면 끔이다. 저장을 쓸 수 없어도 그 페이지 안에서는 토글이
 *     동작한다(`local-store.ts`의 메모리 기준값).
 * -   **토글은 `document.documentElement`의 class 전환뿐이다.** 문장을 다시 그리지 않고 상호작용 handle을
 *     건드리지 않는다. `<rt>`는 렌더러(`segments.ts`)가 항상 만들고 CSS(`furigana.css`)가 class로 보이거나
 *     숨긴다. CSS 기본값이 숨김이라 설정을 읽기 전에 읽기가 번쩍 보이지 않는다.
 * -   **학습 신호가 아니다.** 요청도 event도 만들지 않는다. 이 모듈은 공개 그래프(demo) 안에 있으므로 API
 *     쪽 모듈을 import하지 않는다.
 * -   부팅 hook이 없다. 문장이 있는 화면이 상단바에 토글을 넣을 때(`renderFuriganaToggle`) 저장값이 적용된다.
 */

import { localSlot } from '../local-store'
import './furigana.css'

/** documentElement에 붙는 class. 있으면 .sentence 안의 rt가 보인다. 없으면(기본) 숨긴다. */
export const FURIGANA_ON_CLASS = 'furigana-on'

const TOGGLE_LABEL = '후리가나'

type FuriganaSetting = { on: boolean }

/** `{"on": boolean}`이고 다른 키가 없다. */
function isFuriganaSetting(value: unknown): value is FuriganaSetting {
  if (typeof value !== 'object' || value === null || Array.isArray(value)) return false
  const keys = Object.keys(value)
  return keys.length === 1 && keys[0] === 'on' && typeof (value as { on: unknown }).on === 'boolean'
}

const setting = localSlot('nc.furigana.v1', isFuriganaSetting)

/** 저장값이 {"on": true}일 때만 true. 없거나 형식이 틀리거나 읽을 수 없으면 false(기본 끔). */
export function isFuriganaOn(): boolean {
  return setting.read()?.on === true
}

/** local-store에 쓰고 document.documentElement의 FURIGANA_ON_CLASS를 전환한다. 요청·event 없음. */
export function setFuriganaOn(on: boolean): void {
  setting.write({ on })
  document.documentElement.classList.toggle(FURIGANA_ON_CLASS, on)
}

/** 상단바 actions에 넣는 스위치(<button aria-pressed>). 만들 때 저장값을 문서 class에 적용한다. */
export function renderFuriganaToggle(): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'topbar-button furigana-toggle'
  button.textContent = TOGGLE_LABEL

  // 손잡이와 색만 움직이는 스위치 모양. 이름은 버튼 문구가 맡는다.
  const track = document.createElement('span')
  track.className = 'furigana-switch'
  track.setAttribute('aria-hidden', 'true')
  button.append(track)

  const show = (on: boolean): void => {
    button.setAttribute('aria-pressed', on ? 'true' : 'false')
  }

  const on = isFuriganaOn()
  document.documentElement.classList.toggle(FURIGANA_ON_CLASS, on)
  show(on)

  button.addEventListener('click', () => {
    const next = !isFuriganaOn()
    setFuriganaOn(next)
    show(next)
  })

  return button
}
