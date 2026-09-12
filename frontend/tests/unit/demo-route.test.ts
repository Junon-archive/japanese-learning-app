/**
 * Demo **진입과 종료 경로**. 요청 0건이 여기서 고정된다.
 *
 * 이 파일은 `src/main.ts`를 실제로 부팅시킨다 --- 라우팅 결정이 그 파일에만 있고, 한때
 * 종료 경로가 `GET /api/auth/me`를 불러 **demo가 backend를 호출했다.** vitest 137건이 전부
 * 초록인 상태에서 브라우저 e2e만 그것을 잡았다. 그 방어선이 하나뿐이면 같은 회귀가 다시
 * 난다. 그래서 여기서 단정한다:
 *
 * -   `#/demo`로 들어오면 **부팅이 `fetchMe()`보다 먼저 갈린다** --- 요청 0건.
 * -   demo에서 나올 때 **새 요청을 만들지 않는다.** 들어오기 직전 화면으로 돌아갈 뿐이다.
 *
 * `fetch`는 던지는 스텁이다. 어느 경로가 부르든 그 자리에서 드러난다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { FakeElement } from './fake-dom'
import { byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const fetchMock = vi.fn<typeof fetch>()

function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

let root: FakeElement

/** `main.ts`가 `#app`을 찾는다. 그 자리에 스텁 루트를 준다. */
function stubDocument(): void {
  root = createFakeElement('div')
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
}

/** 부팅 시점의 hash를 정해 `main.ts`를 새로 실행한다. */
async function boot(hash: string): Promise<void> {
  vi.stubGlobal('location', { hash })
  vi.resetModules()
  await import('../../src/main')
  await flush()
}

beforeEach(() => {
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
  stubDocument()
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('entering the demo by url', () => {
  it('makes no request on the way in', async () => {
    await boot('#/demo')

    expect(flatText(root)).toContain('데모 모드입니다')
    // `#/demo`가 `fetchMe()`보다 먼저 갈린다. 백엔드가 죽어 있어도 demo는 열린다.
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('makes no request on the way out either', async () => {
    await boot('#/demo')

    byClass(root, 'demo-exit')[0]!.click()
    await flush()

    // ★ 이 단정이 그 회귀를 막는다. 종료가 `fetchMe()`를 부르면 여기서 빨개진다.
    expect(fetchMock).not.toHaveBeenCalled()
    // 앞선 화면이 없었으므로 로그인 화면이다. 인증 여부를 확인하지 않는다.
    expect(flatText(root)).toContain('Nihongo Context')
    expect(byClass(root, 'demo-enter')).toHaveLength(1)
    expect(location.hash).toBe('')
  })
})

describe('entering the demo from the login screen', () => {
  it('returns to the login screen without a single extra request', async () => {
    // 부팅에서 `/me`가 401 --- 로그인 화면이 뜬다. 이 요청 하나만 정당하다.
    fetchMock.mockResolvedValue(new Response(null, { status: 401 }))
    await boot('')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(byClass(root, 'demo-enter')).toHaveLength(1)

    byClass(root, 'demo-enter')[0]!.click()
    await flush()
    expect(flatText(root)).toContain('데모 모드입니다')
    expect(location.hash).toBe('#/demo')
    // 진입에 요청이 없다.
    expect(fetchMock).toHaveBeenCalledTimes(1)

    byClass(root, 'demo-exit')[0]!.click()
    await flush()

    // 종료에도 요청이 없다. 들어오기 직전 화면(로그인)으로 그냥 돌아간다.
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(flatText(root)).toContain('Nihongo Context')
    expect(location.hash).toBe('')
  })
})
