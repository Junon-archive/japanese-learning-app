/**
 * 진행 표시와 "세션 종료 도달" 판정.
 *
 * **판정에 쓰는 숫자는 전부 session payload에서 온다**(05_API_SPEC.md의
 * `진행 상태의 갱신과 세션 종료 판정`).
 *
 * ``` text
 * 분모 = (target_minutes + extended_minutes) * 60
 * 분자 = active_seconds
 * 도달 = 분자 >= 분모
 * ```
 *
 * `default_session_minutes`(12)와 `extra_session_minutes`(5)를 이 파일에 적지 않는다.
 * 적으면 config를 바꾼 배포에서 화면이 거짓말을 하고, 그 거짓말은 진행바가 잘 움직이는
 * 것처럼 보이기 때문에 눈에 띄지 않는다. 서버에 "도달" 플래그가 없어 client가 파생하는
 * 것과 정책값을 복사하는 것은 다른 이야기다 --- 파생에 쓰는 값이 전부 서버 것이다.
 *
 * **주기적 갱신이 없다.** 진행은 `/complete` 직후 `GET /api/study/session` 한 번으로만
 * 움직인다(`ui/study.ts`). 문장을 읽는 동안 진행바가 멈춰 있는 것은 `active_seconds`의
 * 정의 그대로다.
 */

import type { StudySession } from '../types'

const SECONDS_PER_MINUTE = 60

export type SessionProgress = {
  /** 분자. */
  activeSeconds: number
  /** 분모. */
  totalSeconds: number
  /** 0~1로 자른 비율. 진행바 너비에만 쓴다. */
  ratio: number
  /** `오늘 학습 완료 / 더 학습하기` 를 띄울 시점. 세션이 닫혔다는 뜻이 **아니다**. */
  reached: boolean
}

export function sessionProgress(session: StudySession): SessionProgress {
  const totalSeconds = (session.target_minutes + session.extended_minutes) * SECONDS_PER_MINUTE
  const activeSeconds = session.active_seconds
  return {
    activeSeconds,
    totalSeconds,
    ratio: Math.min(1, Math.max(0, activeSeconds / totalSeconds)),
    reached: activeSeconds >= totalSeconds,
  }
}

/** `오늘 약 12분` 의 출처는 `target_minutes`, 연장분은 `extended_minutes`다. */
export function progressLabel(session: StudySession): string {
  const base = `오늘 약 ${session.target_minutes}분`
  return session.extended_minutes > 0 ? `${base} (+${session.extended_minutes}분 연장)` : base
}

/** `2분 / 7분`. 두 숫자 모두 payload에서 온다. */
export function progressReadout(session: StudySession): string {
  const done = Math.floor(session.active_seconds / SECONDS_PER_MINUTE)
  const total = session.target_minutes + session.extended_minutes
  return `${done}분 / ${total}분`
}

export function renderProgress(session: StudySession): HTMLElement {
  const progress = sessionProgress(session)

  const wrap = document.createElement('div')
  wrap.className = 'progress'

  const label = document.createElement('span')
  label.className = 'progress-label'
  label.textContent = progressLabel(session)

  const readout = document.createElement('span')
  readout.className = 'progress-readout'
  readout.textContent = progressReadout(session)

  const bar = document.createElement('div')
  bar.className = 'progress-bar'
  bar.setAttribute('role', 'progressbar')
  bar.setAttribute('aria-valuemin', '0')
  bar.setAttribute('aria-valuemax', String(progress.totalSeconds))
  bar.setAttribute('aria-valuenow', String(Math.min(progress.activeSeconds, progress.totalSeconds)))
  bar.setAttribute('aria-label', progressLabel(session))

  const fill = document.createElement('span')
  fill.className = 'progress-fill'
  fill.style.width = `${progress.ratio * 100}%`
  bar.append(fill)

  wrap.append(label, readout, bar)
  return wrap
}
