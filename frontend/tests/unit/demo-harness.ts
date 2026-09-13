/**
 * Demo 화면을 가짜 DOM 위에서 여는 도구. `demo.test.ts`와 `demo-progress.test.ts`가 함께 쓴다.
 *
 * -   `freshDemo()`는 **새 페이지를 연 것과 같다.** 모듈을 새로 불러오므로 `local-store.ts`의 메모리 기준값과
 *     `localSlot` 생성 기록도 새것이다. 같은 `localStorage` 스텁을 두고 다시 부르면 "새로고침 뒤"다.
 * -   문구와 상수는 테스트에 복사하지 않는다. 버튼은 사용자가 읽는 글자로 누르고, 숫자는 fixture 길이와
 *     `constants.ts`에서 온다.
 */
import { expect, vi } from 'vitest'

import type { FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement } from './fake-dom'

export type DemoModules = {
  demo: typeof import('../../src/demo/demo')
  progress: typeof import('../../src/demo/progress')
  fixture: typeof import('../../src/demo/fixture')
  furigana: typeof import('../../src/ui/furigana')
}

/** 새 페이지. 모듈 그래프 전체를 새로 불러온다. */
export async function freshDemo(): Promise<DemoModules> {
  vi.resetModules()
  const [demo, progress, fixture, furigana] = await Promise.all([
    import('../../src/demo/demo'),
    import('../../src/demo/progress'),
    import('../../src/demo/fixture'),
    import('../../src/ui/furigana'),
  ])
  return { demo, progress, fixture, furigana }
}

export type MountedDemo = {
  root: FakeElement
  navigations: string[]
  logins: () => number
}

export function mountDemo(modules: DemoModules): MountedDemo {
  const root = createFakeElement('div')
  const navigations: string[] = []
  let logins = 0
  modules.demo.mount({
    root: root as unknown as HTMLElement,
    signal: new AbortController().signal,
    subpath: '',
    navigate: (hash) => navigations.push(hash),
    openLogin: () => {
      logins += 1
    },
  })
  return { root, navigations, logins: () => logins }
}

export function flush(): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, 0)
  })
}

/** 글자가 정확히 `text`인 버튼 하나를 누른다. */
export function press(root: FakeElement, text: string): void {
  const found = buttons(root).filter((button) => button.textContent === text)
  expect(found, `button "${text}" on screen`).toHaveLength(1)
  found[0]!.click()
}

export function click(root: FakeElement, className: string, index = 0): void {
  const target = byClass(root, className)[index]
  expect(target, `no .${className}[${index}] on screen`).toBeDefined()
  target!.click()
}

/** 화면의 학습 문장(원문). 없으면 null(완료 화면). */
export function sentenceOnScreen(root: FakeElement): string | null {
  return byClass(root, 'sentence')[0]?.getAttribute('aria-label') ?? null
}

/** `{본 문장 수} / {전체 문장 수}` 표시. */
export function progressText(root: FakeElement): string {
  const found = byClass(root, 'demo-progress')
  expect(found).toHaveLength(1)
  return found[0]!.textContent
}

export function progressLabel(seen: number, total: number): string {
  return `${seen} / ${total}`
}

/** `tokenIndex`번째 표현을 탭하고, 열린 설명 시트의 자기평가 버튼(글자 `label`)을 누른다. */
export async function selfReport(root: FakeElement, tokenIndex: number, label: string): Promise<void> {
  click(root, 'token', tokenIndex)
  await flush()
  const open = byClass(root, 'sheet-scrim').filter((scrim) => !scrim.classList.contains('is-closing'))
  expect(open, 'one open explanation sheet').toHaveLength(1)
  const choice = byClass(open[0]!, 'self-report').filter((button) => button.textContent === label)
  expect(choice, `self-report "${label}"`).toHaveLength(1)
  choice[0]!.click()
  await flush()
}

export async function answerProbe(root: FakeElement, label: string): Promise<void> {
  const choice = byClass(root, 'probe-option').filter((button) => button.textContent === label)
  expect(choice, `probe option "${label}"`).toHaveLength(1)
  choice[0]!.click()
  await flush()
}

export function next(root: FakeElement): void {
  press(root, '다음 문장')
}

export type MemoryStorage = Storage & { data: Map<string, string>; writtenKeys: string[] }

/** 쓴 key를 기록하는 localStorage 스텁. */
export function memoryStorage(initial: Record<string, string> = {}): MemoryStorage {
  const data = new Map(Object.entries(initial))
  const writtenKeys: string[] = []
  return {
    data,
    writtenKeys,
    get length() {
      return data.size
    },
    clear: () => {
      data.clear()
    },
    key: (index: number) => [...data.keys()][index] ?? null,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      writtenKeys.push(key)
      data.set(key, value)
    },
    removeItem: (key: string) => {
      data.delete(key)
    },
  }
}

/** 모든 접근이 던지는 저장소(차단, 용량 초과, 사생활 보호 모드). */
export function throwingStorage(): Storage {
  const fail = (): never => {
    throw new DOMException('storage denied', 'SecurityError')
  }
  return {
    get length(): number {
      return fail()
    },
    clear: fail,
    getItem: fail,
    key: fail,
    removeItem: fail,
    setItem: fail,
  }
}
