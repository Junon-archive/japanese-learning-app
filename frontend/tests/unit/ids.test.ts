/**
 * `newClientEventId()`는 **항상 UUIDv4**여야 한다. v4가 아니면 서버가 422로 거부하고
 * (05_API_SPEC.md의 `키 공간 분리`) 그 상호작용은 기록되지 않는다.
 *
 * 폴백 경로를 따로 검증하는 이유: `crypto.randomUUID`는 secure context에만 있어서
 * 개발 PC(localhost)에서는 **절대 폴백이 돌지 않는다.** 폴백이 깨져 있어도 실기
 * 테스트를 평문 HTTP LAN IP로 열기 전까지 아무도 모른다.
 */
import { afterEach, describe, expect, it } from 'vitest'

import { newClientEventId } from '../../src/ids'

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

function expectThousandValidV4(): void {
  const seen = new Set<string>()
  for (let index = 0; index < 1000; index += 1) {
    const id = newClientEventId()
    expect(id).toMatch(UUID_V4)
    expect(id[14]).toBe('4') // version nibble
    expect('89ab').toContain(id[19]) // variant 10xx
    seen.add(id)
  }
  expect(seen.size).toBe(1000)
}

const nativeRandomUUID = globalThis.crypto.randomUUID

afterEach(() => {
  Object.defineProperty(globalThis.crypto, 'randomUUID', {
    value: nativeRandomUUID,
    configurable: true,
    writable: true,
  })
})

describe('newClientEventId', () => {
  it('produces UUIDv4 via crypto.randomUUID', () => {
    expect(typeof globalThis.crypto.randomUUID).toBe('function')
    expectThousandValidV4()
  })

  it('produces UUIDv4 via the getRandomValues fallback (non-secure context)', () => {
    Object.defineProperty(globalThis.crypto, 'randomUUID', {
      value: undefined,
      configurable: true,
      writable: true,
    })
    expect(globalThis.crypto.randomUUID).toBeUndefined()
    expectThousandValidV4()
  })
})
