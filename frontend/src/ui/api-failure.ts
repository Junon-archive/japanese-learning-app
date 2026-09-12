/**
 * `ApiError` -> 화면 문구. **HTTP를 아는 유일한 문구 변환 지점이다.**
 *
 * `ui/notice.ts`에서 갈라냈다. 그 파일은 문구 상수와 DOM 한 조각이 전부이고, HTTP를 알면
 * static demo가 안내 문구를 쓰는 것만으로 `api.ts`를 번들에 끌어오게 된다
 * (`04_SECURITY_AND_DATA.md`: demo는 backend API를 호출하지 않는다).
 */

import { ApiError } from '../api'
import { MESSAGES } from './notice'

/** `Unauthenticated`는 여기서 문구가 되지 않는다 --- 로그인 화면으로 보낸다. */
export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return MESSAGES.unexpected
  switch (error.kind) {
    case 'OriginRejected':
      return MESSAGES.originRejected
    case 'NotFound':
      return MESSAGES.notFound
    case 'StateGate':
      return MESSAGES.sessionChanged
    case 'Invalid':
      return MESSAGES.invalid
    case 'Transient':
      return MESSAGES.transient
    default:
      return MESSAGES.unexpected
  }
}
