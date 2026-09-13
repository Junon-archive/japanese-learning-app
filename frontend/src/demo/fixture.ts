/**
 * Public Demo의 **전부**. static fixture다.
 *
 * `04_SECURITY_AND_DATA.md`와 `05_API_SPEC.md`가 불변식으로 둔 것: **demo는 backend
 * API를 호출하지 않고 demo 전용 endpoint·DB·provider도 없다.** 그래서 "서버가 줄 값"을
 * fixture로 두고, demo 화면은 그것만 읽는다. 이 파일에 fetch도 import되는 API client도
 * 없다.
 *
 * 모양은 **API payload와 같다**(`src/types.ts`). 그래야 같은 렌더러가 demo와 실제 학습
 * 화면에서 똑같이 동작한다.
 *
 * -   `Presentation`에 번역이 없다. 실제 payload에 그 필드가 없기 때문이고, demo도
 *     `문장 뜻 보기`를 누른 뒤에야 `korean_translation`을 건넨다.
 * -   설명은 `sentence_item_id`별이다. 같은 `learning_item_id`가 두 문장에 나오면 문맥
 *     뜻이 서로 다른 두 설명이 된다 --- 서버가 그렇게 저장한다.
 * -   문장 데이터는 seed에서 생성한 `fixture-data.ts`에 있다(`scripts/build_demo_fixture.py`).
 *     이 파일은 타입과 re-export만 둔다.
 */

import type { Explanation, Presentation } from '../types'

/** 한 문장 몫의 fixture. 서버 응답 세 개(`/next`, `/click`, `/translation/reveal`)에 대응한다. */
export type DemoSentence = {
  presentation: Presentation
  /** `POST /translation/reveal`의 응답 값. payload에는 없다. */
  korean_translation: string
  /** `sentence_item_id` -> `POST /click`의 응답. */
  explanations: Record<number, Explanation>
}

export { DEMO_FIXTURE_ID, DEMO_SENTENCES } from './fixture-data'
