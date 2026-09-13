/**
 * 화면에 나가는 안내·오류 문구와 그것을 담는 DOM 한 조각.
 *
 * 문구를 여기 모으는 이유는 두 가지다.
 *
 * 1.  **실패를 성공처럼 보이게 하지 않는다**(10_ERROR_HANDLING.md). 저장이 실패하면
 *     그 사실을 적는다. 화면마다 문구를 만들면 어느 한 곳이 조용히 넘어간다.
 * 2.  **무한 spinner를 만들지 않는다.** 오류 안내에는 사용자가 누를 수 있는 동작이
 *     함께 붙거나(수동 재시도), 누를 것이 없다는 사실이 문구에 적혀 있다(설정 오류).
 *
 * 학습 정책값(분 수, 횟수, 임계값)을 문구에 적지 않는다. 서버가 주는 숫자만 화면에
 * 쓰고(`ui/progress.ts`), 서버가 주지 않는 숫자는 문구에서 뺀다.
 *
 * **이 파일은 `api.ts`를 import하지 않는다.** 문구와 DOM 한 조각이 전부이므로 HTTP를 알
 * 필요가 없고, 알면 static demo가 문구를 쓰는 것만으로 `api.ts`를 번들에 끌어온다
 * (demo는 backend와 구조적으로 독립이다). `ApiError` -> 문구 변환은 `ui/api-failure.ts`에
 * 있다.
 */

export const MESSAGES = {
  /** 03_UI_UX_SPEC.md의 `이전 세션 종료 안내`. 경고가 아니다. */
  previousSessionTimedOut: '이전 세션은 오랫동안 활동이 없어 종료했습니다. 새 세션을 시작합니다.',
  sessionResumed: '이어서 학습합니다.',
  /** Ready Pool이 빈 상태. 자동 재시도하지 않고 사용자가 누른다. */
  emptyPool: '지금 준비된 문장이 없습니다. 잠시 후 다시 시도해 주세요.',
  /** 409. 이 화면의 상호작용을 멈추고 현재 session을 다시 얻는다. */
  sessionChanged: '이 세션은 이미 종료되어 새로 불러옵니다.',
  sessionClosedElsewhere: '열린 세션이 없습니다. 새로 시작할 수 있습니다.',
  /** 403. 배포 설정 문제이므로 재시도를 권하지 않는다. */
  originRejected: '서버 설정 문제로 요청이 거부되었습니다. 관리자에게 문의해 주세요.',
  /** 5xx / 네트워크. 재시도는 사용자가 누른다. */
  transient: '지금 서버에 연결할 수 없습니다. 잠시 후 다시 시도해 주세요.',
  notFound: '요청한 내용을 찾을 수 없습니다.',
  invalid: '요청을 처리할 수 없습니다.',
  unexpected: '알 수 없는 문제가 생겼습니다.',
  /** 저장(=상태 변경)이 실패했다. 진행한 것처럼 보이게 하지 않는다. */
  saveFailed: '저장하지 못했습니다. 다시 시도해 주세요.',
  /** 로그인 실패는 사유와 무관하게 **하나의 문구**다(05_API_SPEC.md). */
  loginFailed: '아이디 또는 비밀번호를 확인해 주세요.',
  retry: '다시 시도하기',
  startNewSession: '새 세션 시작',
  /** 상단바 `로그인`의 `fetchMe`가 403 밖의 이유로 실패했다. 재시도는 `fetchMe`만 다시 부른다. */
  loginCheckFailed: '지금은 로그인 상태를 확인할 수 없어요. 체험과 글자 배우기는 그대로 쓸 수 있어요.',
  /** 로그인 영역 코드의 동적 import 실패. 버튼을 두지 않는다 --- 다시 시도는 상단바 `로그인`이다. */
  loginAreaLoadFailed: '로그인 화면을 불러오지 못했어요. 위의 로그인을 다시 눌러 주세요.',
  /** 로그아웃 뒤 선택 홈에서 띄우는 토스트. */
  loggedOut: '로그아웃했어요.',
  /** demo route의 동적 import 실패. */
  demoLoadFailed: '체험용 문장을 불러오지 못했어요. 새로고침해 주세요.',
} as const

export type NoticeTone = 'info' | 'error'

export type NoticeAction = {
  label: string
  onClick: () => void
}

/** 한 줄 안내. `action`이 있으면 **수동** 재시도 버튼이 붙는다(자동 폴링을 하지 않는다). */
export function renderNotice(
  message: string,
  tone: NoticeTone = 'info',
  action?: NoticeAction,
): HTMLElement {
  const box = document.createElement('div')
  box.className = `notice notice-${tone}`
  box.setAttribute('role', tone === 'error' ? 'alert' : 'status')

  const text = document.createElement('p')
  text.className = 'notice-text'
  text.textContent = message
  box.append(text)

  if (action !== undefined) {
    const button = document.createElement('button')
    button.type = 'button'
    button.className = 'notice-action'
    button.textContent = action.label
    button.addEventListener('click', action.onClick)
    box.append(button)
  }

  return box
}

/** 토스트가 떠 있는 시간. 03_UI_UX_SPEC.md의 `토스트와 오류`. */
const TOAST_MS = 4000

let currentToast: HTMLElement | null = null

/**
 * 한 번 사라지는 **정보성** 안내(예: 세션 시작 안내, `기록했어요`). **오류에는 쓰지 않는다** ---
 * 사라지는 오류는 놓치고 재시도 버튼을 붙일 수 없으므로 오류는 `renderNotice`로 그 자리에 둔다.
 *
 * `#app` 밖(`document.body`)에 붙는다. 화면이 바뀌어도 안내가 끊기지 않고 학습 진행을 막지 않는다.
 * 4초 뒤, 또는 탭하면 바로 사라지기 시작한다. 한 번에 하나만 둔다. DOM에서 떼는 것은
 * `transitionend`이고, 그 이벤트가 오지 않으면 다음 토스트가 뗀다.
 */
export function showToast(message: string): void {
  currentToast?.remove()

  const toast = document.createElement('div')
  toast.className = 'toast'
  toast.setAttribute('role', 'status')
  toast.textContent = message
  currentToast = toast

  let leaving = false
  function dismiss(): void {
    if (leaving) return
    leaving = true
    clearTimeout(timer)
    toast.classList.add('is-leaving')
  }
  const timer = setTimeout(dismiss, TOAST_MS)

  toast.addEventListener('click', dismiss)
  toast.addEventListener('transitionend', (event) => {
    if (!leaving || event.target !== toast) return
    toast.remove()
    if (currentToast === toast) currentToast = null
  })

  document.body.append(toast)
}
