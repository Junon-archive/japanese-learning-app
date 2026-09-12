/**
 * 최소 DOM 스텁. **새 의존성을 추가하지 않기 위한 것이다** --- 이 프로젝트에는 jsdom도
 * happy-dom도 없고, F2가 테스트해야 하는 것은 "어떤 노드를 몇 개 만드는가"까지다.
 *
 * `src/ui/*`가 실제로 쓰는 API만 있다. 여기에 기능을 늘리기 전에 그 테스트가 정말
 * DOM을 필요로 하는지 먼저 생각한다(순수 함수로 뽑을 수 있으면 그쪽이 낫다).
 */

export type FakeElement = {
  tagName: string
  className: string
  type: string
  lang: string
  textContent: string
  /** `<textarea>`. 실제 DOM처럼 입력값을 들고 있다. */
  value: string
  disabled: boolean
  children: FakeElement[]
  attributes: Record<string, string>
  style: Record<string, string>
  setAttribute: (name: string, value: string) => void
  getAttribute: (name: string) => string | null
  append: (...nodes: FakeElement[]) => void
  replaceChildren: (...nodes: FakeElement[]) => void
  addEventListener: (type: string, listener: () => void) => void
  click: () => void
  /** `click` 밖의 event(예: `input`)를 흘린다. */
  fire: (type: string) => void
  /** 로그인 화면이 첫 입력에 부른다. 스텁에서는 할 일이 없다. */
  focus: () => void
}

export function createFakeElement(tagName: string): FakeElement {
  const listeners: Record<string, (() => void)[]> = {}
  const element: FakeElement = {
    tagName: tagName.toUpperCase(),
    className: '',
    type: '',
    lang: '',
    textContent: '',
    value: '',
    disabled: false,
    children: [],
    attributes: {},
    style: {},
    setAttribute(name, value) {
      element.attributes[name] = value
    },
    getAttribute(name) {
      return element.attributes[name] ?? null
    },
    append(...nodes) {
      element.children.push(...nodes)
    },
    replaceChildren(...nodes) {
      element.children = [...nodes]
    },
    addEventListener(type, listener) {
      ;(listeners[type] ??= []).push(listener)
    },
    click() {
      element.fire('click')
    },
    fire(type) {
      for (const listener of listeners[type] ?? []) listener()
    },
    focus() {},
  }
  return element
}

/** `vi.stubGlobal('document', fakeDocument())`로 쓴다. */
export function fakeDocument(): { createElement: (tagName: string) => FakeElement } {
  return { createElement: createFakeElement }
}

export function isTappable(element: FakeElement): boolean {
  return element.tagName === 'BUTTON'
}

/** 자신을 포함한 모든 후손. 스텁이므로 DOM query 대신 이걸로 찾는다. */
export function descendants(root: FakeElement): FakeElement[] {
  return [root, ...root.children.flatMap(descendants)]
}

export function buttons(root: FakeElement): FakeElement[] {
  return descendants(root).filter(isTappable)
}

export function byClass(root: FakeElement, className: string): FakeElement[] {
  return descendants(root).filter((node) => node.className.split(' ').includes(className))
}

/**
 * 후손 전체의 `textContent`를 이어 붙인 문자열.
 *
 * 실제 DOM의 `textContent`는 후손을 모아 주지만 이 스텁은 필드일 뿐이다. "화면에 이
 * 문자열이 있는가"를 단정할 때 쓴다.
 */
export function flatText(root: FakeElement): string {
  return descendants(root)
    .map((node) => node.textContent)
    .join(' ')
}
