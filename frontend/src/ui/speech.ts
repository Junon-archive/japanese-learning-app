/**
 * 영어 문장 재생(ADR-025 결정 4). **`speechSynthesis` / `SpeechSynthesisUtterance` 식별자가 나오는
 * 유일한 모듈이다** --- `tests/unit/speech-scope.test.ts`가 AST로 단정한다.
 *
 * 지키는 것들. 전부 화면에서는 잘 도는 것처럼 보이기 때문에 주석으로 남긴다.
 *
 * 1.  **`localService === true`인 음성만 쓴다.** Web Speech API의 음성 중 일부는 브라우저가 외부
 *     서버에 요청해서 합성한다(`localService === false`). 공개 화면의 격리 검사 (f)는 frontend
 *     origin 밖 요청을 **전부** 세므로, 네트워크 음성을 허용하면 영어 demo의 e2e가 깨지거나 그
 *     검사를 느슨하게 고쳐야 한다. 검사가 지금 격리를 지탱하므로 음성 쪽을 좁힌다.
 * 2.  **쓸 수 있는 음성이 없으면 버튼을 그리지 않는다.** 비활성 버튼으로 두지 않는다 --- 누를 수
 *     없는 버튼이 왜 있는지 화면마다 설명해야 한다.
 * 3.  **`getVoices()`는 처음 호출에서 빈 배열일 수 있다.** `voiceschanged`를 **한 번** 기다리고
 *     그때 그린다. **타임아웃을 두지 않는다** --- 이벤트가 영영 안 오는 브라우저는 음성이 없는
 *     브라우저다.
 * 4.  **음성 이름을 하드코딩하지 않는다**(`Samantha`, `Google US English` 등). 기기마다 다르고,
 *     하드코딩하면 그 기기 밖에서 조용히 동작하지 않는다. `rate`·`pitch`는 기본값이다.
 * 5.  **겹쳐 나오지 않는다.** 새 재생 전에 항상 `cancel()`을 부르고, 같은 버튼을 다시 누르면
 *     멈춘다(toggle). 화면(문장)의 `signal`이 abort되면 멈춘다 --- 안 하면 다음 화면에서 이전
 *     문장이 계속 들린다.
 * 6.  **재생은 학습 신호가 아니다**(불변식 25). event·exposure·mastery를 만들지 않고, 서버로
 *     아무것도 보내지 않으며, 재생 여부를 브라우저에 저장하지도 않는다. 그래서 이 모듈은
 *     `api.ts`·`endpoints.ts`·`local-store.ts`에 닿지 않고 공개 그래프(demo) 안에 있어도 된다.
 * 7.  **재생 실패를 사용자에게 알리지 않는다.** `speechSynthesis`는 실패를 조용히 삼키는 경우가
 *     많고, 그 실패에 사용자가 할 수 있는 일이 없다(ADR-025의 `알려진 한계`).
 *
 * 일본어 화면에는 재생 버튼이 없고, 상단바에도 두지 않는다(문장마다 읽을 대상이 다르므로 전역
 * 메뉴가 아니다). 어느 언어인지는 호출부(`ui/study.ts`, `ui/explanation.ts`, `demo/demo.ts`)가
 * 자기가 받은 language로 가른다.
 */

import './speech.css'

const SPEAK_LABEL = '재생'

/** 지금 재생을 시작한 버튼. 같은 버튼을 다시 눌렀는지 판단하는 데만 쓴다. */
let playing: HTMLElement | null = null

/** 브라우저에 Web Speech API가 있는가. Node(테스트)와 일부 브라우저에는 없다. */
function hasApi(): boolean {
  return typeof speechSynthesis !== 'undefined' && typeof SpeechSynthesisUtterance !== 'undefined'
}

/**
 * 쓸 음성. `localService === true`이고 `lang`이 `en`으로 시작하는 것 중 `en-US`를 먼저,
 * 없으면 목록 순서 첫 번째. 하나도 없으면 null이고 재생 기능 전체가 꺼진다.
 */
function pickVoice(): SpeechSynthesisVoice | null {
  if (!hasApi()) return null
  const english = speechSynthesis
    .getVoices()
    .filter((voice) => voice.localService && voice.lang.startsWith('en'))
  return english.find((voice) => voice.lang === 'en-US') ?? english[0] ?? null
}

/** 지금 재생할 수 있는가. false면 버튼을 그리지 않는다. */
export function isSpeechAvailable(): boolean {
  return pickVoice() !== null
}

/** 진행 중인 재생을 멈춘다. 음성이 없거나 재생 중이 아니어도 안전하다. */
function stop(): void {
  if (!hasApi()) return
  speechSynthesis.cancel()
  playing = null
}

/** 읽는다. 쓸 음성이 없으면 아무것도 하지 않는다(실패를 알리지 않는다). */
export function speak(text: string): void {
  const voice = pickVoice()
  if (voice === null) return
  // 두 문장이 겹쳐 나오지 않게 항상 먼저 멈춘다.
  speechSynthesis.cancel()
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.voice = voice
  speechSynthesis.speak(utterance)
}

function speakButton(text: string): HTMLElement {
  const button = document.createElement('button')
  button.type = 'button'
  button.className = 'speak'
  button.textContent = SPEAK_LABEL
  button.addEventListener('click', () => {
    // 같은 버튼을 다시 누르면 멈춘다. 다 읽은 뒤의 누름은 다시 재생이다 --- 그래서 "이 버튼이
    // 시작했다"만 보지 않고 아직 읽고 있는지(speaking/pending)도 본다.
    if (playing === button && (speechSynthesis.speaking || speechSynthesis.pending)) {
      stop()
      return
    }
    playing = button
    // `speak`가 먼저 `cancel()`한다. 다른 버튼이 읽고 있었으면 거기서 끊긴다(겹치지 않는다).
    speak(text)
  })
  return button
}

/**
 * `text`를 읽는 버튼이 들어갈 자리. **쓸 음성이 없으면 자리만 비어 있다**(비활성 버튼이 아니다).
 *
 * `signal`은 이 버튼이 붙은 문장의 수명이다. abort되면(문장이 바뀌거나 화면을 떠났다) 재생을
 * 멈추고, 늦게 온 `voiceschanged`로 버튼을 그리지도 않는다.
 */
export function renderSpeakButton(text: string, signal: AbortSignal): HTMLElement {
  const slot = document.createElement('span')
  slot.className = 'speak-slot'
  if (!hasApi()) return slot

  signal.addEventListener('abort', stop)

  if (isSpeechAvailable()) {
    slot.append(speakButton(text))
    return slot
  }
  // 아직 목록이 비어 있다. 한 번만 기다린다. 타임아웃을 두지 않는다.
  speechSynthesis.addEventListener(
    'voiceschanged',
    () => {
      if (signal.aborted || !isSpeechAvailable()) return
      slot.append(speakButton(text))
    },
    { once: true },
  )
  return slot
}
