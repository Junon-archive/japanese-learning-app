/**
 * 브라우저 저장소의 **유일한** 접근 지점(`spec/04_SECURITY_AND_DATA.md`의
 * `localStorage 사용 범위 (MVP-02 확정)`, ADR-022 결정 3).
 *
 * key마다 그 값의 주인 모듈이 `localSlot`을 **한 번** 만든다. 임의 key·임의 값을 쓰는 함수는
 * export하지 않는다. 페이지가 살아 있는 동안은 메모리 Map이 기준값이라 저장이 막힌 브라우저에서도
 * 그 페이지 안에서는 값이 이어진다. 모든 저장소 접근은 던질 수 있다고 보고 감싼다.
 */

export const LOCAL_STORE_KEYS = ['nc.furigana.v1', 'nc.kana.v1', 'nc.demo.v1'] as const
export type LocalStoreKey = (typeof LOCAL_STORE_KEYS)[number]

export type LocalSlot<T> = {
  /** 없거나, 읽을 수 없거나, JSON이 아니거나, isValid가 거르면 undefined. 던지지 않는다. */
  read: () => T | undefined
  /** isValid를 통과한 값만 메모리에 쓰고 localStorage에 시도한다. 실패해도 던지지 않는다. */
  write: (value: T) => void
  /** 진도 초기화. 메모리와 localStorage 둘 다에서 지운다. 던지지 않는다. */
  remove: () => void
}

const memory = new Map<LocalStoreKey, unknown>()
const created = new Set<LocalStoreKey>()

/** key 인자는 문자열 리터럴이어야 한다(AST 검사). 같은 key로 두 번 만들면 던진다. */
export function localSlot<T>(
  key: LocalStoreKey,
  isValid: (value: unknown) => value is T,
): LocalSlot<T> {
  if (created.has(key)) {
    throw new Error(`localSlot already created for ${key}`)
  }
  created.add(key)

  return {
    read() {
      if (memory.has(key)) return memory.get(key) as T
      try {
        const raw = localStorage.getItem(key)
        if (raw === null) return undefined
        const value: unknown = JSON.parse(raw)
        if (!isValid(value)) return undefined
        memory.set(key, value)
        return value
      } catch {
        return undefined
      }
    },
    write(value) {
      if (!isValid(value)) return
      memory.set(key, value)
      try {
        localStorage.setItem(key, JSON.stringify(value))
      } catch {
        // 용량 초과, 사생활 보호 모드, 접근 거부. 메모리 값으로 계속한다.
      }
    },
    remove() {
      memory.delete(key)
      try {
        localStorage.removeItem(key)
      } catch {
        // 저장소를 쓸 수 없으면 지울 것도 없다.
      }
    },
  }
}
