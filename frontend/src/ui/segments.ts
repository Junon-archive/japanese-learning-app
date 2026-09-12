/**
 * `render_segments` -> DOM.
 *
 * **이 파일에 인덱스 계산이 없다.** 서버가 code point offset을 이미 적용해 segment를
 * 잘라 줬다(05_API_SPEC.md의 `Sentence Presentation Payload`). frontend가 offset을
 * 다시 계산하면 JavaScript 문자열이 UTF-16이기 때문에 서로게이트 페어(𠮟)와 결합
 * 문자에서 경계가 어긋난다 --- 그리고 그 깨짐은 그런 문자가 들어간 문장에서만 나타난다.
 * 그래서 `segment.text`를 **자르지도 이어붙이지도 않고** 그대로 넣는다.
 *
 * **tappable span은 전부 같은 모양이다**(03_UI_UX_SPEC.md의 `tappable span 표시`).
 * target과 incidental을 구분하지 않는다. payload에 그 구분이 없고, 구분해 강조하면 그
 * 문장에서 무엇이 평가 대상인지가 드러난다.
 */

import type { RenderSegment } from '../types'

/**
 * segment의 `text`를 순서대로 이은 문장. 값은 payload의 `japanese`와 같아야 한다.
 *
 * 화면에서는 문장 요소의 `aria-label`로 쓴다. span으로 쪼개 놓으면 스크린 리더가
 * 조각마다 끊어 읽기 때문이다.
 */
export function joinSegments(segments: RenderSegment[]): string {
  return segments.map((segment) => segment.text).join('')
}

/**
 * 문장 한 줄을 만든다. `sentence_item_id`가 non-null인 segment만 누를 수 있다.
 *
 * tap 대상은 `<button>`이다. 키보드와 스크린 리더에서 누를 수 있는 것이 되어야 하고,
 * `role`/`tabindex`를 직접 붙이는 것보다 빠뜨릴 것이 적다. `sentence_item_id`는 DOM
 * 속성에 적지 않고 closure로 넘긴다 --- 문자열로 왕복시키면 파싱이 한 겹 늘어난다.
 */
export function renderSentence(
  segments: RenderSegment[],
  onTapItem: (sentenceItemId: number) => void,
): HTMLElement {
  const sentence = document.createElement('p')
  sentence.className = 'sentence'
  sentence.lang = 'ja'
  sentence.setAttribute('aria-label', joinSegments(segments))

  for (const segment of segments) {
    const itemId = segment.sentence_item_id
    if (itemId === null) {
      const plain = document.createElement('span')
      plain.textContent = segment.text
      sentence.append(plain)
      continue
    }

    const tappable = document.createElement('button')
    tappable.type = 'button'
    // 모든 tappable span이 이 클래스 하나를 공유한다. 조건부 클래스를 추가하지 마라.
    tappable.className = 'token'
    tappable.textContent = segment.text
    tappable.addEventListener('click', () => {
      onTapItem(itemId)
    })
    sentence.append(tappable)
  }

  return sentence
}
