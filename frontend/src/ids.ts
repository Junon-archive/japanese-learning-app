/**
 * client 발급 `client_event_id` 생성 (05_API_SPEC.md의 `키 공간 분리`).
 *
 * 서버는 client key로 **UUIDv4만** 받는다. version nibble이 4가 아니면 body 검증
 * 실패로 422이고 event는 기록되지 않는다.
 */

/**
 * UUIDv4 문자열 하나.
 *
 * `crypto.randomUUID()`는 **secure context에만 존재한다.** localhost는 secure로
 * 취급되지만, 평문 HTTP + LAN IP(172.16.x.x 같은)로 실기 테스트를 하면 `undefined`다.
 * 폴백이 없으면 그 환경에서 모든 상호작용 POST가 깨진 문자열을 보내 422로 거부된다.
 * `crypto.getRandomValues`는 secure context를 요구하지 않으므로 폴백은 거기서 만든다.
 */
export function newClientEventId(): string {
  const webCrypto = globalThis.crypto
  if (typeof webCrypto.randomUUID === 'function') {
    return webCrypto.randomUUID()
  }

  const bytes = new Uint8Array(16)
  webCrypto.getRandomValues(bytes)
  // RFC 4122: version nibble = 4, variant 상위 2비트 = 10.
  bytes[6] = (bytes[6]! & 0x0f) | 0x40
  bytes[8] = (bytes[8]! & 0x3f) | 0x80

  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
  return [
    hex.slice(0, 8),
    hex.slice(8, 12),
    hex.slice(12, 16),
    hex.slice(16, 20),
    hex.slice(20, 32),
  ].join('-')
}
