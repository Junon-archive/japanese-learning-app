/**
 * 최소 DOM 스텁. **새 의존성을 추가하지 않기 위한 것이다** --- 이 프로젝트에는 jsdom도
 * happy-dom도 없고, F2가 테스트해야 하는 것은 "어떤 노드를 몇 개 만드는가"까지다.
 *
 * `src/ui/*`가 실제로 쓰는 API만 있다. 여기에 기능을 늘리기 전에 그 테스트가 정말
 * DOM을 필요로 하는지 먼저 생각한다(순수 함수로 뽑을 수 있으면 그쪽이 낫다).
 *
 * 실제 DOM과 맞춘 동작 몇 가지(화면 전환·시트 테스트가 기댄다):
 *
 * -   event는 부모로 올라간다(`parentNode` 사슬). `target`은 처음 받은 요소다.
 * -   `append`/`replaceChildren`는 노드를 옛 부모에서 떼어 옮긴다.
 * -   `focus()`는 자신이나 조상이 `inert`면 아무것도 하지 않고, 아니면 전역 `document`의
 *     `activeElement`를 바꾼다.
 * -   `transitionend`는 저절로 오지 않는다. 테스트가 `fire`로 흘리지 않으면 영영 없다.
 * -   텍스트 노드가 있다(`createTextNode`, `append`/`replaceChildren`의 문자열). `childNodes`는 텍스트 노드를
 *     포함하고 `children`은 요소만이다. 요소의 `textContent`는 여전히 필드일 뿐이라 후손 텍스트를 모아 주지
 *     않는다 --- 모은 문자열은 `flatText`/`textWithoutRt`로 본다.
 */

export type FakeEvent = {
  type: string
  target: FakeElement
  currentTarget: FakeElement
  /** `keydown`의 키. 그 밖의 event에서는 ''. */
  key: string
  defaultPrevented: boolean
  preventDefault: () => void
  stopPropagation: () => void
}

export type FakeClassList = {
  add: (...names: string[]) => void
  remove: (...names: string[]) => void
  toggle: (name: string, force?: boolean) => boolean
  contains: (name: string) => boolean
}

/** `createTextNode`나 `append('문자열')`이 만든 노드. */
export type FakeText = {
  nodeType: 3
  textContent: string
  parentNode: FakeElement | null
}

export type FakeNode = FakeElement | FakeText

export type FakeElement = {
  nodeType: 1
  tagName: string
  className: string
  /** `className`을 원본으로 읽고 쓴다. */
  classList: FakeClassList
  type: string
  lang: string
  textContent: string
  /** `<textarea>`. 실제 DOM처럼 입력값을 들고 있다. */
  value: string
  disabled: boolean
  inert: boolean
  scrollTop: number
  parentNode: FakeElement | null
  /** 텍스트 노드를 포함한 자식. 순서가 문서 순서다. */
  childNodes: FakeNode[]
  /** `childNodes` 중 요소만. */
  readonly children: FakeElement[]
  attributes: Record<string, string>
  style: Record<string, string>
  setAttribute: (name: string, value: string) => void
  getAttribute: (name: string) => string | null
  /** 문자열은 텍스트 노드가 된다(실제 DOM과 같다). */
  append: (...nodes: (FakeNode | string)[]) => void
  replaceChildren: (...nodes: (FakeNode | string)[]) => void
  remove: () => void
  /** 태그 이름 선택자(`'h1'`)만 받는다. 자신은 빼고 후손에서 찾는다. */
  querySelector: (selector: string) => FakeElement | null
  /** `querySelector`와 같은 규칙으로 전부. */
  querySelectorAll: (selector: string) => FakeElement[]
  addEventListener: (type: string, listener: (event: FakeEvent) => void) => void
  click: () => FakeEvent
  /** `click` 밖의 event(예: `input`, `keydown`, `transitionend`)를 흘린다. */
  fire: (type: string, init?: { key?: string }) => FakeEvent
  focus: (options?: unknown) => void
}

export type FakeDocument = {
  createElement: (tagName: string) => FakeElement
  createTextNode: (data: string) => FakeText
  documentElement: FakeElement
  body: FakeElement
  activeElement: FakeElement | null
}

const LISTENERS = new WeakMap<FakeElement, Record<string, ((event: FakeEvent) => void)[]>>()

function detach(node: FakeNode): void {
  const parent = node.parentNode
  if (parent === null) return
  parent.childNodes = parent.childNodes.filter((child) => child !== node)
  node.parentNode = null
}

function isElement(node: FakeNode): node is FakeElement {
  return node.nodeType === 1
}

export function createFakeText(data: string): FakeText {
  return { nodeType: 3, textContent: data, parentNode: null }
}

function isInert(element: FakeElement): boolean {
  for (let node: FakeElement | null = element; node !== null; node = node.parentNode) {
    if (node.inert) return true
  }
  return false
}

export function createFakeElement(tagName: string): FakeElement {
  const listeners: Record<string, ((event: FakeEvent) => void)[]> = {}
  const names = (): string[] => element.className.split(' ').filter((name) => name !== '')
  const element: FakeElement = {
    nodeType: 1,
    tagName: tagName.toUpperCase(),
    className: '',
    classList: {
      add(...added) {
        element.className = [...new Set([...names(), ...added])].join(' ')
      },
      remove(...removed) {
        element.className = names()
          .filter((name) => !removed.includes(name))
          .join(' ')
      },
      toggle(name, force) {
        const on = force ?? !names().includes(name)
        if (on) element.classList.add(name)
        else element.classList.remove(name)
        return on
      },
      contains(name) {
        return names().includes(name)
      },
    },
    type: '',
    lang: '',
    textContent: '',
    value: '',
    disabled: false,
    inert: false,
    scrollTop: 0,
    parentNode: null,
    childNodes: [],
    get children() {
      return element.childNodes.filter(isElement)
    },
    attributes: {},
    style: {},
    setAttribute(name, value) {
      element.attributes[name] = value
    },
    getAttribute(name) {
      return element.attributes[name] ?? null
    },
    append(...nodes) {
      for (const given of nodes) {
        const node = typeof given === 'string' ? createFakeText(given) : given
        detach(node)
        node.parentNode = element
        element.childNodes.push(node)
      }
    },
    replaceChildren(...nodes) {
      for (const child of element.childNodes) child.parentNode = null
      element.childNodes = []
      element.append(...nodes)
    },
    remove() {
      detach(element)
    },
    querySelector(selector) {
      return element.querySelectorAll(selector)[0] ?? null
    },
    querySelectorAll(selector) {
      const wanted = selector.toUpperCase()
      return descendants(element).filter((node) => node !== element && node.tagName === wanted)
    },
    addEventListener(type, listener) {
      ;(listeners[type] ??= []).push(listener)
    },
    click() {
      return element.fire('click')
    },
    fire(type, init) {
      let stopped = false
      const event: FakeEvent = {
        type,
        target: element,
        currentTarget: element,
        key: init?.key ?? '',
        defaultPrevented: false,
        preventDefault() {
          event.defaultPrevented = true
        },
        stopPropagation() {
          stopped = true
        },
      }
      for (let node: FakeElement | null = element; node !== null && !stopped; node = node.parentNode) {
        event.currentTarget = node
        for (const listener of LISTENERS.get(node)?.[type] ?? []) listener(event)
      }
      return event
    },
    focus() {
      if (isInert(element)) return
      const doc = (globalThis as { document?: { activeElement?: unknown } }).document
      if (doc !== undefined) doc.activeElement = element
    },
  }
  LISTENERS.set(element, listeners)
  return element
}

/** `vi.stubGlobal('document', fakeDocument())`로 쓴다. */
export function fakeDocument(): FakeDocument {
  const documentElement = createFakeElement('html')
  const body = createFakeElement('body')
  documentElement.append(body)
  return {
    createElement: createFakeElement,
    createTextNode: createFakeText,
    documentElement,
    body,
    activeElement: null,
  }
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

/** 자신을 포함한 모든 후손 노드(텍스트 노드 포함), 문서 순서. */
function nodes(root: FakeNode): FakeNode[] {
  return isElement(root) ? [root, ...root.childNodes.flatMap(nodes)] : [root]
}

/**
 * 후손 전체(텍스트 노드 포함)의 `textContent`를 이어 붙인 문자열.
 *
 * 실제 DOM의 `textContent`는 후손을 모아 주지만 이 스텁은 필드일 뿐이다. "화면에 이
 * 문자열이 있는가"를 단정할 때 쓴다.
 */
export function flatText(root: FakeElement): string {
  return nodes(root)
    .map((node) => node.textContent)
    .join(' ')
}

/**
 * `<rt>`(후리가나 읽기)를 뺀 텍스트를 구분자 없이 문서 순서로 이은 문자열.
 *
 * 문장 텍스트를 원문과 비교할 때 쓴다(03_UI_UX_SPEC.md의 `토글과 렌더링`: "`rt`의 읽기를 빼고 비교한다").
 */
export function textWithoutRt(root: FakeNode): string {
  if (!isElement(root)) return root.textContent
  if (root.tagName === 'RT') return ''
  return root.textContent + root.childNodes.map(textWithoutRt).join('')
}

/**
 * `location` / `history` / `window`의 hash 이동 부분만. `vi.stubGlobal`로 셋을 함께 건다.
 *
 * 실제 브라우저와 맞춘 것:
 *
 * -   `location.hash = h`는 값이 바뀔 때만 기록을 하나 쌓고 `hashchange`를 **나중에**(microtask) 보낸다.
 * -   `history.replaceState`는 hash를 바꾸지만 `hashchange`를 보내지 않는다.
 * -   `history.back()`은 hash가 달라질 때만 `hashchange`를 보낸다.
 */
export type FakeBrowser = {
  location: { hash: string; pathname: string; search: string }
  history: {
    replaceState: (state: unknown, unused: string, url: string) => void
    back: () => void
  }
  window: { addEventListener: (type: string, listener: () => void) => void }
  /** `replaceState`에 넘어온 인자 전부. */
  replaceStateCalls: unknown[][]
  /** 등록된 리스너의 event 종류. */
  listenerTypes: () => string[]
  /** 지금 기록 줄. 마지막이 현재. */
  entries: () => string[]
}

function normalizeHash(value: string): string {
  const hash = value.startsWith('#') ? value : `#${value}`
  return hash === '#' ? '' : hash
}

export function fakeBrowser(initialHash: string): FakeBrowser {
  const entries = [normalizeHash(initialHash)]
  const listeners: { type: string; listener: () => void }[] = []
  const replaceStateCalls: unknown[][] = []

  function current(): string {
    return entries[entries.length - 1]!
  }

  function fireHashChange(): void {
    void Promise.resolve().then(() => {
      for (const entry of listeners) if (entry.type === 'hashchange') entry.listener()
    })
  }

  const location = {
    get hash(): string {
      return current()
    },
    set hash(value: string) {
      const next = normalizeHash(value)
      if (next === current()) return
      entries.push(next)
      fireHashChange()
    },
    pathname: '/',
    search: '',
  }

  return {
    location,
    history: {
      replaceState(...args: unknown[]) {
        replaceStateCalls.push(args)
        const url = String(args[2])
        const at = url.indexOf('#')
        entries[entries.length - 1] = at === -1 ? '' : normalizeHash(url.slice(at))
      },
      back() {
        if (entries.length < 2) return
        const before = entries.pop()!
        if (before !== current()) fireHashChange()
      },
    },
    window: {
      addEventListener(type, listener) {
        listeners.push({ type, listener })
      },
    },
    replaceStateCalls,
    listenerTypes: () => listeners.map((entry) => entry.type),
    entries: () => [...entries],
  }
}
