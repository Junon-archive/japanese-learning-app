/**
 * `src/local-store.ts` 런타임 계약(`spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`,
 * `12_TEST_PLAN.md`의 `localStorage`).
 *
 * 모듈 수준 상태(메모리 Map, 만든 key 집합)가 있으므로 테스트마다 모듈을 새로 불러온다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

type LocalStoreModule = typeof import('../../src/local-store')

type Flag = { on: boolean }
function isFlag(value: unknown): value is Flag {
  return (
    typeof value === 'object' &&
    value !== null &&
    Object.keys(value).length === 1 &&
    typeof (value as { on?: unknown }).on === 'boolean'
  )
}

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial))
  return {
    data,
    getItem: vi.fn((key: string) => data.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      data.set(key, value)
    }),
    removeItem: vi.fn((key: string) => {
      data.delete(key)
    }),
  }
}

function throwingStorage() {
  const fail = () => {
    throw new DOMException('denied', 'SecurityError')
  }
  return { getItem: vi.fn(fail), setItem: vi.fn(fail), removeItem: vi.fn(fail) }
}

async function freshModule(): Promise<LocalStoreModule> {
  vi.resetModules()
  return import('../../src/local-store')
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('LOCAL_STORE_KEYS', () => {
  it('is exactly the three keys', async () => {
    const { LOCAL_STORE_KEYS } = await freshModule()
    expect([...LOCAL_STORE_KEYS]).toEqual(['nc.furigana.v1', 'nc.kana.v1', 'nc.demo.v1'])
  })
})

describe('localSlot', () => {
  it('throws when the same key is created twice', async () => {
    const { localSlot } = await freshModule()
    localSlot('nc.furigana.v1', isFlag)
    expect(() => localSlot('nc.furigana.v1', isFlag)).toThrow()
    // 다른 key는 영향받지 않는다.
    expect(() => localSlot('nc.kana.v1', isFlag)).not.toThrow()
  })

  it('reads a valid stored value and round-trips writes through JSON', async () => {
    const storage = memoryStorage({ 'nc.furigana.v1': '{"on":true}' })
    vi.stubGlobal('localStorage', storage)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.furigana.v1', isFlag)

    expect(slot.read()).toEqual({ on: true })
    slot.write({ on: false })
    expect(storage.data.get('nc.furigana.v1')).toBe('{"on":false}')
    expect(slot.read()).toEqual({ on: false })
  })

  it('returns undefined when nothing is stored', async () => {
    vi.stubGlobal('localStorage', memoryStorage())
    const { localSlot } = await freshModule()
    expect(localSlot('nc.furigana.v1', isFlag).read()).toBeUndefined()
  })

  it('returns undefined for a stored value that is not JSON', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ 'nc.furigana.v1': '{on:true' }))
    const { localSlot } = await freshModule()
    expect(localSlot('nc.furigana.v1', isFlag).read()).toBeUndefined()
  })

  it('returns undefined for a stored value that isValid rejects', async () => {
    vi.stubGlobal('localStorage', memoryStorage({ 'nc.furigana.v1': '{"on":true,"x":1}' }))
    const { localSlot } = await freshModule()
    expect(localSlot('nc.furigana.v1', isFlag).read()).toBeUndefined()
  })

  it('does nothing when writing a value isValid rejects', async () => {
    const storage = memoryStorage({ 'nc.furigana.v1': '{"on":true}' })
    vi.stubGlobal('localStorage', storage)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.furigana.v1', isFlag)

    slot.write({ on: 'yes' } as unknown as Flag)
    expect(storage.setItem).not.toHaveBeenCalled()
    expect(slot.read()).toEqual({ on: true })
  })

  it('never throws with a throwing localStorage and keeps the value in memory', async () => {
    const storage = throwingStorage()
    vi.stubGlobal('localStorage', storage)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.furigana.v1', isFlag)

    expect(slot.read()).toBeUndefined()
    expect(() => slot.write({ on: true })).not.toThrow()
    expect(storage.setItem).toHaveBeenCalled()
    expect(slot.read()).toEqual({ on: true })
    expect(() => slot.remove()).not.toThrow()
    expect(slot.read()).toBeUndefined()
  })

  it('never throws when the localStorage global itself is missing', async () => {
    // node에는 localStorage 전역이 없다. 접근 자체가 ReferenceError다.
    expect('localStorage' in globalThis).toBe(false)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.kana.v1', isFlag)

    expect(slot.read()).toBeUndefined()
    expect(() => slot.write({ on: true })).not.toThrow()
    expect(slot.read()).toEqual({ on: true })
    expect(() => slot.remove()).not.toThrow()
  })

  it('never throws when reading the localStorage global throws', async () => {
    Object.defineProperty(globalThis, 'localStorage', {
      configurable: true,
      get() {
        throw new DOMException('denied', 'SecurityError')
      },
    })
    try {
      const { localSlot } = await freshModule()
      const slot = localSlot('nc.demo.v1', isFlag)
      expect(slot.read()).toBeUndefined()
      expect(() => slot.write({ on: false })).not.toThrow()
      expect(slot.read()).toEqual({ on: false })
      expect(() => slot.remove()).not.toThrow()
    } finally {
      Reflect.deleteProperty(globalThis, 'localStorage')
    }
  })

  it('remove clears both memory and storage and leaves other keys alone', async () => {
    const storage = memoryStorage({
      'nc.furigana.v1': '{"on":true}',
      'nc.kana.v1': '{"on":true}',
    })
    vi.stubGlobal('localStorage', storage)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.furigana.v1', isFlag)

    slot.write({ on: false })
    slot.remove()
    expect(storage.data.has('nc.furigana.v1')).toBe(false)
    expect(storage.data.get('nc.kana.v1')).toBe('{"on":true}')
    expect(slot.read()).toBeUndefined()
  })

  it('serves reads from memory once a value is known', async () => {
    const storage = memoryStorage({ 'nc.furigana.v1': '{"on":true}' })
    vi.stubGlobal('localStorage', storage)
    const { localSlot } = await freshModule()
    const slot = localSlot('nc.furigana.v1', isFlag)

    slot.read()
    // 다른 탭 등이 저장소를 바꿔도 이 페이지의 기준값은 메모리다.
    storage.data.set('nc.furigana.v1', '{"on":false}')
    expect(slot.read()).toEqual({ on: true })
    expect(storage.getItem).toHaveBeenCalledTimes(1)
  })
})
