/**
 * 로그인 화면. 03_UI_UX_SPEC.md의 `Login` --- **두 필드와 버튼 하나가 전부다.**
 *
 * -   실패 문구는 사유와 무관하게 **하나**다. 서버가 없는 아이디와 틀린 password를
 *     같은 401로 감추므로(05_API_SPEC.md), 화면이 그것을 갈라 적으면 서버가 감춘 것을
 *     UI가 알려주게 된다.
 * -   회원가입·비밀번호 재설정·소셜 로그인 진입점을 두지 않는다. 누를 endpoint가 MVP에
 *     없다. Demo 진입 버튼은 예외가 아니다 --- demo는 endpoint를 부르지 않는 static
 *     fixture이므로 로그인 없이 열린다(`03_UI_UX_SPEC.md`의 `Demo`).
 * -   **password에 `maxlength`를 걸지 않는다.** `04_SECURITY_AND_DATA.md`가 최대 길이를
 *     정하지 않기로 확정했고, 계정 생성 경로(`scripts/create_user.py`)에도 상한이 없다.
 *     화면에만 상한을 두면 "만들 수는 있는데 로그인은 안 되는" password가 생긴다.
 *     길이 규칙 안내도 적지 않는다 --- login은 검증하지 않는다.
 */

import { ApiError } from '../api'
import { login } from '../endpoints'
import type { User } from '../types'
import { errorMessage } from './api-failure'
import { MESSAGES, renderNotice } from './notice'

export function mountLogin(
  root: HTMLElement,
  onAuthenticated: (user: User) => void,
  onOpenDemo: () => void,
): void {
  const screen = document.createElement('main')
  screen.className = 'screen login'

  const title = document.createElement('h1')
  title.className = 'login-title'
  title.textContent = 'Nihongo Context'

  const form = document.createElement('form')
  form.className = 'login-form'
  form.noValidate = true

  const loginIdField = field('login-id', '아이디', 'text', 'username')
  const passwordField = field('password', '비밀번호', 'password', 'current-password')

  const submit = document.createElement('button')
  submit.type = 'submit'
  submit.className = 'primary'
  submit.textContent = '로그인'

  const noticeSlot = document.createElement('div')
  noticeSlot.className = 'notice-slot'

  form.append(loginIdField.wrap, passwordField.wrap, submit, noticeSlot)

  // Demo 진입. 로그인 없이 볼 수 있고(static fixture) 계정을 만들 필요가 없다.
  const demo = document.createElement('button')
  demo.type = 'button'
  demo.className = 'secondary demo-enter'
  demo.textContent = '로그인 없이 데모 보기'
  demo.addEventListener('click', onOpenDemo)

  screen.append(title, form, demo)
  root.replaceChildren(screen)
  loginIdField.input.focus()

  let submitting = false

  form.addEventListener('submit', (event) => {
    event.preventDefault()
    if (submitting) return
    submitting = true
    submit.disabled = true
    noticeSlot.replaceChildren()

    login({ login_id: loginIdField.input.value, password: passwordField.input.value })
      .then((user) => {
        onAuthenticated(user)
      })
      .catch((error: unknown) => {
        // 401은 자격 증명 문제다. 여기서 `Unauthenticated`를 로그인 화면으로 보내는
        // 일반 처리를 타면 화면만 다시 그려지고 이유가 사라진다.
        const message =
          error instanceof ApiError && error.kind === 'Unauthenticated'
            ? MESSAGES.loginFailed
            : errorMessage(error)
        noticeSlot.replaceChildren(renderNotice(message, 'error'))
        passwordField.input.value = ''
        passwordField.input.focus()
      })
      .finally(() => {
        submitting = false
        submit.disabled = false
      })
  })
}

type Field = {
  wrap: HTMLElement
  input: HTMLInputElement
}

function field(id: string, labelText: string, type: string, autocomplete: AutoFill): Field {
  const wrap = document.createElement('div')
  wrap.className = 'field'

  const label = document.createElement('label')
  label.htmlFor = id
  label.textContent = labelText

  const input = document.createElement('input')
  input.id = id
  input.type = type
  input.autocomplete = autocomplete
  input.required = true

  wrap.append(label, input)
  return { wrap, input }
}
