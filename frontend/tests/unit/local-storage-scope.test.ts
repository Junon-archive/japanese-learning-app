/**
 * 브라우저 저장소 접근 범위(불변식 18). TypeScript 컴파일러 AST로 `frontend/src/` 전체를 훑는다.
 *
 * canonical: `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위 (MVP-02 확정)`,
 * ADR-022 결정 3, `spec/mvp-02-onboarding/12_TEST_PLAN.md`의 `localStorage (불변식 18)`, 합격 기준 45.
 *
 * 규칙마다 합성 소스로 양성 대조군을 둔다. 검사가 "위반이 없다"고 말하는 것만으로는 검사가 실제로
 * 위반을 잡는지 알 수 없기 때문이다. 주석은 AST에 없으므로 주석에서 이름을 말하는 것은 막지 않는다.
 *
 * private 그래프(`private.ts`) 안의 `localSlot` key 검사는 shell 레인이 이 파일에 따로 더한다.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import type { Project } from './import-graph'
import { createProject, fullGraph } from './import-graph'

const SRC = fileURLToPath(new URL('../../src', import.meta.url))

/** `src` 기준 경로(`/` 구분). */
const STORE_MODULE = 'local-store.ts'

const EXPECTED_KEYS = ['nc.furigana.v1', 'nc.kana.v1', 'nc.demo.v1'] as const
type StoreKey = (typeof EXPECTED_KEYS)[number]

/** slot 소유 위치(04 `slot 소유`). */
const SLOT_OWNER: Record<StoreKey, (path: string) => boolean> = {
  'nc.furigana.v1': (path) => path === 'ui/furigana.ts',
  'nc.kana.v1': (path) => path.startsWith('kana/'),
  'nc.demo.v1': (path) => path.startsWith('demo/'),
}

/**
 * Wave 2 시점 규칙(메인 결정 G1): 모든 key는 `localSlot` 호출이 1회 이하이고, 이 목록의 key는 정확히
 * 1회다. 명세의 최종 규칙은 "세 key 모두 정확히 1회"다. Wave 3 레인이 자기 slot을 만들면서 자기 key를
 * 이 목록에 넣어 정확히 1회로 올린다(furigana-fe -> 'nc.furigana.v1', demo -> 'nc.demo.v1').
 */
const REQUIRED_SLOT_KEYS: readonly StoreKey[] = ['nc.kana.v1', 'nc.furigana.v1']

/** local-store.ts가 export해도 되는 이름 전부. 임의 key·임의 값을 쓰는 함수는 없다. */
const STORE_EXPORTS = ['LOCAL_STORE_KEYS', 'LocalSlot', 'LocalStoreKey', 'localSlot']

/** 계산된 속성 접근(`[...]`)과 구조 분해를 막는 전역 객체. */
const GLOBAL_OBJECTS = new Set(['globalThis', 'window', 'self', 'document', 'navigator', 'history', 'location'])

const STORAGE_FRAGMENT = /storage|cookie|indexeddb/i

type Source = { path: string; file: ts.SourceFile }

const CODE_KINDS: Record<string, ts.ScriptKind> = {
  '.ts': ts.ScriptKind.TS,
  '.mts': ts.ScriptKind.TS,
  '.cts': ts.ScriptKind.TS,
  '.tsx': ts.ScriptKind.TSX,
  '.js': ts.ScriptKind.JS,
  '.mjs': ts.ScriptKind.JS,
  '.cjs': ts.ScriptKind.JS,
  '.jsx': ts.ScriptKind.JSX,
}

/** 코드가 아니어서 훑지 않는 확장자. 여기 없는 확장자가 `src`에 생기면 실패한다(fail-closed). */
const NON_CODE_EXTENSIONS = new Set(['.css'])

function parse(path: string, text: string): Source {
  const kind = CODE_KINDS[extname(path)] ?? ts.ScriptKind.TS
  return { path, file: ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kind) }
}

function listFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name)
    return entry.isDirectory() ? listFiles(full) : [full]
  })
}

function srcPath(full: string): string {
  return relative(SRC, full).split(sep).join('/')
}

function loadSrc(): Source[] {
  return listFiles(SRC)
    .filter((full) => extname(full) in CODE_KINDS)
    .map((full) => parse(srcPath(full), readFileSync(full, 'utf8')))
}

function walk(node: ts.Node, visit: (node: ts.Node) => void): void {
  visit(node)
  node.forEachChild((child) => walk(child, visit))
}

function where(source: Source, node: ts.Node): string {
  const { line } = source.file.getLineAndCharacterOfPosition(node.getStart(source.file))
  return `${source.path}:${line + 1}`
}

function unwrap(expression: ts.Expression): ts.Expression {
  let current = expression
  while (
    ts.isParenthesizedExpression(current) ||
    ts.isAsExpression(current) ||
    ts.isNonNullExpression(current) ||
    ts.isSatisfiesExpression(current) ||
    ts.isTypeAssertionExpression(current)
  ) {
    current = current.expression
  }
  return current
}

/** `window`, `window.document`, `globalThis.navigator` 같은 전역 객체 참조면 마지막 이름. */
function globalName(expression: ts.Expression): string | undefined {
  const node = unwrap(expression)
  if (ts.isIdentifier(node)) return GLOBAL_OBJECTS.has(node.text) ? node.text : undefined
  if (ts.isPropertyAccessExpression(node) && GLOBAL_OBJECTS.has(node.name.text)) {
    return globalName(node.expression) === undefined ? undefined : node.name.text
  }
  return undefined
}

function isStringLike(node: ts.Node): node is ts.StringLiteralLike | ts.TemplateLiteralLikeNode {
  return (
    ts.isStringLiteral(node) ||
    ts.isNoSubstitutionTemplateLiteral(node) ||
    ts.isTemplateHead(node) ||
    ts.isTemplateMiddle(node) ||
    ts.isTemplateTail(node)
  )
}

// ---------------------------------------------------------------------------
// 규칙. 각 함수는 위반 목록을 돌려준다(없으면 빈 배열).
// ---------------------------------------------------------------------------

/** `localStorage` 식별자는 local-store.ts에만 나온다. */
function localStorageOutsideStore(sources: readonly Source[]): string[] {
  const violations: string[] = []
  for (const source of sources) {
    if (source.path === STORE_MODULE) continue
    walk(source.file, (node) => {
      if (ts.isIdentifier(node) && node.text === 'localStorage') {
        violations.push(`${where(source, node)} localStorage`)
      }
    })
  }
  return violations
}

/** 전역 객체에 대한 `[...]` 접근과 구조 분해가 없다. */
function computedGlobalAccess(sources: readonly Source[]): string[] {
  const violations: string[] = []
  for (const source of sources) {
    walk(source.file, (node) => {
      if (ts.isElementAccessExpression(node)) {
        const name = globalName(node.expression)
        if (name !== undefined) violations.push(`${where(source, node)} ${name}[...]`)
      }
      if (
        ts.isVariableDeclaration(node) &&
        ts.isObjectBindingPattern(node.name) &&
        node.initializer !== undefined
      ) {
        const name = globalName(node.initializer)
        if (name !== undefined) violations.push(`${where(source, node)} destructures ${name}`)
      }
    })
  }
  return violations
}

/** local-store.ts 밖 문자열 리터럴에 `Storage`·`cookie`·`indexedDB` 조각이 없다(대소문자 무시). */
function storageFragments(sources: readonly Source[]): string[] {
  const violations: string[] = []
  for (const source of sources) {
    if (source.path === STORE_MODULE) continue
    walk(source.file, (node) => {
      if (isStringLike(node) && STORAGE_FRAGMENT.test(node.text)) {
        violations.push(`${where(source, node)} ${JSON.stringify(node.text)}`)
      }
    })
  }
  return violations
}

/** `sessionStorage`, `indexedDB`, `caches`, `cookieStore`, `document.cookie`, `window.name`, `navigator.storage`가 없다. */
function forbiddenStores(sources: readonly Source[]): string[] {
  const violations: string[] = []
  const forbiddenIdentifiers = new Set(['sessionStorage', 'indexedDB', 'caches', 'cookieStore'])
  const forbiddenMembers: [string, ReadonlySet<string>][] = [
    ['cookie', new Set(['document'])],
    ['name', new Set(['window', 'self', 'globalThis'])],
    ['storage', new Set(['navigator'])],
  ]
  for (const source of sources) {
    walk(source.file, (node) => {
      if (ts.isIdentifier(node) && forbiddenIdentifiers.has(node.text)) {
        violations.push(`${where(source, node)} ${node.text}`)
      }
      if (ts.isPropertyAccessExpression(node)) {
        const owner = globalName(node.expression)
        for (const [member, owners] of forbiddenMembers) {
          if (node.name.text === member && owner !== undefined && owners.has(owner)) {
            violations.push(`${where(source, node)} ${owner}.${member}`)
          }
        }
      }
    })
  }
  return violations
}

/** `pushState`/`replaceState`는 호출로만 쓰고 state 인자는 `null`뿐이다. */
function historyState(sources: readonly Source[]): string[] {
  const violations: string[] = []
  const methods = new Set(['pushState', 'replaceState'])
  for (const source of sources) {
    walk(source.file, (node) => {
      if (!ts.isPropertyAccessExpression(node) || !methods.has(node.name.text)) return
      const call = node.parent
      if (!ts.isCallExpression(call) || unwrap(call.expression) !== node) {
        violations.push(`${where(source, node)} ${node.name.text} used without a call`)
        return
      }
      const state = call.arguments[0]
      if (state === undefined || unwrap(state).kind !== ts.SyntaxKind.NullKeyword) {
        violations.push(`${where(source, node)} ${node.name.text} state is not null`)
      }
    })
  }
  return violations
}

/** local-store.ts: 세 key, 정해진 export, `localStorage`는 `key`로 getItem/setItem/removeItem만. */
function storeModuleShape(sources: readonly Source[]): string[] {
  const store = sources.find((source) => source.path === STORE_MODULE)
  if (store === undefined) return [`${STORE_MODULE} is missing`]
  const violations: string[] = []

  const exported: string[] = []
  let keys: string[] | undefined
  for (const statement of store.file.statements) {
    if (ts.isExportDeclaration(statement) || ts.isExportAssignment(statement)) {
      violations.push(`${where(store, statement)} export declaration`)
      continue
    }
    const modifiers = ts.canHaveModifiers(statement) ? ts.getModifiers(statement) : undefined
    if (!modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)) continue
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        exported.push(declaration.name.getText(store.file))
        if (declaration.name.getText(store.file) !== 'LOCAL_STORE_KEYS') continue
        const initializer = declaration.initializer && unwrap(declaration.initializer)
        if (initializer === undefined || !ts.isArrayLiteralExpression(initializer)) {
          violations.push(`${where(store, declaration)} LOCAL_STORE_KEYS is not an array literal`)
          continue
        }
        keys = initializer.elements.map((element) =>
          ts.isStringLiteral(element) ? element.text : `<non-literal ${element.getText(store.file)}>`,
        )
      }
    } else if (
      (ts.isFunctionDeclaration(statement) ||
        ts.isTypeAliasDeclaration(statement) ||
        ts.isInterfaceDeclaration(statement) ||
        ts.isClassDeclaration(statement) ||
        ts.isEnumDeclaration(statement)) &&
      statement.name !== undefined
    ) {
      exported.push(statement.name.text)
    } else {
      violations.push(`${where(store, statement)} unexpected export`)
    }
  }

  if (JSON.stringify(keys) !== JSON.stringify(EXPECTED_KEYS)) {
    violations.push(`LOCAL_STORE_KEYS is ${JSON.stringify(keys)}`)
  }
  if (JSON.stringify([...exported].sort()) !== JSON.stringify([...STORE_EXPORTS].sort())) {
    violations.push(`exports are ${JSON.stringify([...exported].sort())}`)
  }

  const methods = new Set(['getItem', 'setItem', 'removeItem'])
  walk(store.file, (node) => {
    if (!ts.isIdentifier(node) || node.text !== 'localStorage') return
    const access = node.parent
    const call = access.parent
    const ok =
      ts.isPropertyAccessExpression(access) &&
      access.expression === node &&
      methods.has(access.name.text) &&
      ts.isCallExpression(call) &&
      call.expression === access &&
      call.arguments[0] !== undefined &&
      ts.isIdentifier(call.arguments[0]) &&
      call.arguments[0].text === 'key'
    if (!ok) violations.push(`${where(store, node)} localStorage used other than <method>(key, ...)`)
  })
  return violations
}

type SlotCall = { key: StoreKey; path: string }

/** `localSlot` 호출: key는 문자열 리터럴, 세 key 중 하나, 소유 위치 안. 우회 참조도 위반. */
function collectSlotCalls(sources: readonly Source[]): { calls: SlotCall[]; violations: string[] } {
  const calls: SlotCall[] = []
  const violations: string[] = []
  for (const source of sources) {
    const inStore = source.path === STORE_MODULE
    walk(source.file, (node) => {
      if (!inStore && isStringLike(node) && node.text.includes('localSlot')) {
        violations.push(`${where(source, node)} string mentions localSlot`)
      }
      if (!ts.isIdentifier(node) || node.text !== 'localSlot') return

      const parent = node.parent
      const callee =
        ts.isPropertyAccessExpression(parent) && parent.name === node ? parent : (node as ts.Expression)
      const call = callee.parent
      if (ts.isCallExpression(call) && unwrap(call.expression) === callee) {
        const [first] = call.arguments
        if (first === undefined || !ts.isStringLiteral(first)) {
          violations.push(`${where(source, call)} localSlot key is not a string literal`)
          return
        }
        if (!(EXPECTED_KEYS as readonly string[]).includes(first.text)) {
          violations.push(`${where(source, call)} localSlot key ${first.text} is unknown`)
          return
        }
        const key = first.text as StoreKey
        if (!SLOT_OWNER[key](source.path)) {
          violations.push(`${where(source, call)} localSlot('${key}') outside its owner`)
        }
        calls.push({ key, path: source.path })
        return
      }

      if (inStore) return
      if (ts.isImportSpecifier(parent) && parent.name === node && parent.propertyName === undefined) return
      violations.push(`${where(source, node)} localSlot referenced other than a direct call or plain import`)
    })
  }
  return { calls, violations }
}

function slotCallViolations(sources: readonly Source[]): string[] {
  return collectSlotCalls(sources).violations
}

/** Wave 2 시점: key마다 1회 이하, `REQUIRED_SLOT_KEYS`는 정확히 1회. */
function slotCallCounts(sources: readonly Source[], required: readonly StoreKey[]): string[] {
  const { calls } = collectSlotCalls(sources)
  const violations: string[] = []
  for (const key of EXPECTED_KEYS) {
    const at = calls.filter((call) => call.key === key).map((call) => call.path)
    if (at.length > 1) violations.push(`localSlot('${key}') called ${at.length} times: ${at.join(', ')}`)
    if (required.includes(key) && at.length !== 1) {
      violations.push(`localSlot('${key}') must be called exactly once, found ${at.length}`)
    }
  }
  return violations
}

// ---------------------------------------------------------------------------
// 실제 src
// ---------------------------------------------------------------------------

describe('browser storage scope in frontend/src', () => {
  const sources = loadSrc()

  it('scans every file in src (only known non-code extensions are skipped)', () => {
    const skipped = listFiles(SRC)
      .map((full) => extname(full))
      .filter((extension) => !(extension in CODE_KINDS))
    expect(skipped.filter((extension) => !NON_CODE_EXTENSIONS.has(extension))).toEqual([])
    const paths = sources.map((source) => source.path)
    expect(paths).toContain(STORE_MODULE)
    expect(paths).toContain('kana/progress.ts')
  })

  it('uses the localStorage identifier only in local-store.ts', () => {
    expect(localStorageOutsideStore(sources)).toEqual([])
  })

  it('has no computed property access or destructuring on browser globals', () => {
    expect(computedGlobalAccess(sources)).toEqual([])
  })

  it('has no Storage, cookie or indexedDB fragment in string literals outside local-store.ts', () => {
    expect(storageFragments(sources)).toEqual([])
  })

  it('does not use sessionStorage, indexedDB, caches, document.cookie, window.name or navigator.storage', () => {
    expect(forbiddenStores(sources)).toEqual([])
  })

  it('passes only null as history state', () => {
    expect(historyState(sources)).toEqual([])
  })

  it('local-store.ts has exactly the three keys and no arbitrary-key access', () => {
    expect(storeModuleShape(sources)).toEqual([])
  })

  it('calls localSlot only with a literal key, in the owner module, without indirect references', () => {
    expect(slotCallViolations(sources)).toEqual([])
  })

  it('calls localSlot at most once per key and exactly once for the keys required in this wave', () => {
    expect(slotCallCounts(sources, REQUIRED_SLOT_KEYS)).toEqual([])
    expect(collectSlotCalls(sources).calls).toContainEqual({ key: 'nc.kana.v1', path: 'kana/progress.ts' })
  })
})

// ---------------------------------------------------------------------------
// 양성 대조군: 합성 소스에서 각 규칙이 실제로 위반을 잡는다
// ---------------------------------------------------------------------------

const VALID_STORE = `
export const LOCAL_STORE_KEYS = ['nc.furigana.v1', 'nc.kana.v1', 'nc.demo.v1'] as const
export type LocalStoreKey = (typeof LOCAL_STORE_KEYS)[number]
export type LocalSlot<T> = { read: () => T | undefined }
export function localSlot<T>(key: LocalStoreKey, isValid: (value: unknown) => value is T): LocalSlot<T> {
  const raw = localStorage.getItem(key)
  localStorage.setItem(key, 'x')
  localStorage.removeItem(key)
  throw new Error(\`localSlot for \${key} \${raw} \${isValid} Storage\`)
}
`

function synthetic(files: Record<string, string>): Source[] {
  return Object.entries(files).map(([path, text]) => parse(path, text))
}

describe('positive controls', () => {
  it('a clean synthetic tree passes every rule', () => {
    const sources = synthetic({
      [STORE_MODULE]: VALID_STORE,
      'kana/progress.ts': `
        // localStorage, sessionStorage, document.cookie 를 주석에서 말하는 것은 괜찮다.
        import { localSlot } from '../local-store'
        const slot = localSlot('nc.kana.v1', isKana)
        history.replaceState(null, '', '#/')
        window.history.pushState(null, '', '#/kana')
        window.addEventListener('hashchange', () => location.hash)
        const origin = window.location.origin
        const crypto = globalThis.crypto
        const record = { name: 'x' }
        record['name'] = navigator.language
      `,
      'ui/furigana.ts': `import { localSlot } from '../local-store'\nlocalSlot<Flag>('nc.furigana.v1', isFlag)`,
      'demo/progress.ts': `import { localSlot } from '../local-store'\nlocalSlot('nc.demo.v1', isDemo)`,
    })
    expect(localStorageOutsideStore(sources)).toEqual([])
    expect(computedGlobalAccess(sources)).toEqual([])
    expect(storageFragments(sources)).toEqual([])
    expect(forbiddenStores(sources)).toEqual([])
    expect(historyState(sources)).toEqual([])
    expect(storeModuleShape(sources)).toEqual([])
    expect(slotCallViolations(sources)).toEqual([])
    expect(slotCallCounts(sources, EXPECTED_KEYS)).toEqual([])
  })

  it.each([
    ['direct access', 'localStorage.setItem("nc.kana.v1", "{}")'],
    ['window member', 'window.localStorage.getItem(key)'],
    ['destructuring', 'const { localStorage } = globalThis'],
    ['shorthand reference', 'const s = localStorage'],
  ])('localStorage outside local-store.ts: %s', (_name, text) => {
    expect(localStorageOutsideStore(synthetic({ 'kana/progress.ts': text }))).toHaveLength(1)
  })

  it.each([
    ['globalThis concatenation', `globalThis['local' + 'Storage']`],
    ['window variable key', 'window[key]'],
    ['self', `self['x']`],
    ['document', `document['coo' + 'kie']`],
    ['navigator', `navigator[prop]`],
    ['history', `history['push' + 'State']({}, '')`],
    ['location', `location['hash']`],
    ['nested global', `window.document[name]`],
    ['optional element access', `globalThis?.[name]`],
    ['parenthesized', `(window as any)[name]`],
    ['destructuring a global', `const { cookie } = document`],
  ])('computed access on a browser global: %s', (_name, text) => {
    expect(computedGlobalAccess(synthetic({ 'demo/demo.ts': text })).length).toBeGreaterThan(0)
  })

  it.each([
    ['Storage fragment', `const k = 'local' + 'Storage'`],
    ['lowercase storage', `const k = 'session' + 'storage'`],
    ['cookie fragment', `const k = 'coo' + 'kie' || 'cookie'`],
    ['indexedDB fragment', 'const k = `indexedDB`'],
    ['template part', 'const k = `${prefix}Storage`'],
  ])('string fragment outside local-store.ts: %s', (_name, text) => {
    expect(storageFragments(synthetic({ 'ui/furigana.ts': text })).length).toBeGreaterThan(0)
  })

  it('string fragments are allowed inside local-store.ts', () => {
    expect(storageFragments(synthetic({ [STORE_MODULE]: VALID_STORE }))).toEqual([])
  })

  it.each([
    ['sessionStorage', 'sessionStorage.setItem("a", "b")'],
    ['indexedDB', 'window.indexedDB.open("db")'],
    ['caches', 'caches.open("v1")'],
    ['document.cookie', 'document.cookie = "a=b"'],
    ['window.document.cookie', 'const c = window.document.cookie'],
    ['window.name', 'window.name = "x"'],
    ['self.name', 'const n = self.name'],
    ['navigator.storage', 'navigator.storage.persist()'],
    ['cookieStore', "cookieStore.set('a', 'b')"],
    ['window.cookieStore', "void window.cookieStore.get('a')"],
  ])('forbidden browser store: %s', (_name, text) => {
    expect(forbiddenStores(synthetic({ 'kana/quiz.ts': text })).length).toBeGreaterThan(0)
  })

  it('forbidden stores apply inside local-store.ts too', () => {
    expect(forbiddenStores(synthetic({ [STORE_MODULE]: 'sessionStorage.clear()' }))).toHaveLength(1)
  })

  it.each([
    ['object state', `history.pushState({ round: 3 }, '', '#/kana')`],
    ['string state', `window.history.replaceState('x', '', '#/')`],
    ['undefined state', `history.replaceState(undefined, '', '#/')`],
    ['no arguments', 'history.pushState()'],
    ['unbound reference', 'const push = history.pushState'],
  ])('history state other than null: %s', (_name, text) => {
    expect(historyState(synthetic({ 'routes.ts': text }))).toHaveLength(1)
  })

  it.each([
    ['a fourth key', VALID_STORE.replace(`'nc.demo.v1']`, `'nc.demo.v1', 'nc.extra.v1']`)],
    ['a missing key', VALID_STORE.replace(`, 'nc.demo.v1']`, `]`)],
    ['a non-literal key', VALID_STORE.replace(`'nc.demo.v1']`, `DEMO_KEY]`)],
    ['an arbitrary-key export', `${VALID_STORE}\nexport function writeAny(k: string) { localStorage.setItem(k, '') }`],
    ['a re-export', `${VALID_STORE}\nexport * from './other'`],
    ['clear()', VALID_STORE.replace('localStorage.removeItem(key)', 'localStorage.clear()')],
    ['a literal key', VALID_STORE.replace('localStorage.removeItem(key)', `localStorage.removeItem('nc.x')`)],
  ])('local-store.ts with %s', (_name, text) => {
    expect(text).not.toBe(VALID_STORE)
    expect(storeModuleShape(synthetic({ [STORE_MODULE]: text })).length).toBeGreaterThan(0)
  })

  it.each([
    ['a variable key', 'kana/progress.ts', 'const k = "nc.kana.v1"; localSlot(k, isKana)'],
    ['a template key', 'kana/progress.ts', 'localSlot(`nc.kana.v1`, isKana)'],
    ['an unknown key', 'kana/progress.ts', `localSlot('nc.other.v1', isKana)`],
    ['kana key outside src/kana', 'ui/study.ts', `localSlot('nc.kana.v1', isKana)`],
    ['demo key in private code', 'private.ts', `localSlot('nc.demo.v1', isDemo)`],
    ['furigana key outside ui/furigana.ts', 'ui/study.ts', `localSlot('nc.furigana.v1', isFlag)`],
    ['a renamed import', 'kana/progress.ts', `import { localSlot as make } from '../local-store'`],
    ['a re-export', 'kana/index.ts', `export { localSlot } from '../local-store'`],
    ['an alias', 'kana/progress.ts', 'const make = localSlot'],
    ['a string member', 'kana/progress.ts', `store['localSlot']('nc.kana.v1', isKana)`],
  ])('localSlot with %s', (_name, path, text) => {
    expect(slotCallViolations(synthetic({ [path]: text })).length).toBeGreaterThan(0)
  })

  it('counts namespace-member calls as localSlot calls', () => {
    const sources = synthetic({
      'kana/progress.ts': `import * as store from '../local-store'\nstore.localSlot('nc.kana.v1', isKana)`,
      'kana/other.ts': `import { localSlot } from '../local-store'\nlocalSlot('nc.kana.v1', isKana)`,
    })
    expect(slotCallViolations(sources)).toEqual([])
    expect(collectSlotCalls(sources).calls).toHaveLength(2)
    expect(slotCallCounts(sources, REQUIRED_SLOT_KEYS).length).toBeGreaterThan(0)
  })

  it('rejects the same key called twice, in one module or in two', () => {
    const twiceInOne = synthetic({
      'kana/progress.ts': `localSlot('nc.kana.v1', a)\nlocalSlot('nc.kana.v1', b)`,
    })
    const twiceInTwo = synthetic({
      'demo/a.ts': `localSlot('nc.demo.v1', a)`,
      'demo/b.ts': `localSlot('nc.demo.v1', b)`,
      'kana/progress.ts': `localSlot('nc.kana.v1', a)`,
    })
    expect(slotCallCounts(twiceInOne, REQUIRED_SLOT_KEYS).length).toBeGreaterThan(0)
    expect(slotCallCounts(twiceInTwo, REQUIRED_SLOT_KEYS).length).toBeGreaterThan(0)
  })

  it('rejects a required key that is never called', () => {
    const sources = synthetic({ 'ui/furigana.ts': `localSlot('nc.furigana.v1', isFlag)` })
    expect(slotCallCounts(sources, REQUIRED_SLOT_KEYS)).toEqual([
      `localSlot('nc.kana.v1') must be called exactly once, found 0`,
    ])
  })
})

// ---------------------------------------------------------------------------
// private 그래프(shell 레인): 로그인 영역이 닿는 모듈의 localSlot key는 nc.furigana.v1뿐
// ---------------------------------------------------------------------------

/**
 * 로그인 영역(`private.ts`에서 정적 + 리터럴 동적 import로 닿는 모듈)이 만들 수 있는 slot은 후리가나 설정
 * 하나다(`spec/04_SECURITY_AND_DATA.md`의 `slot 소유`, 12_TEST_PLAN.md의 `localStorage (불변식 18)`).
 * 가나·demo 진도는 공개 화면의 것이고 계정 진도와 섞이지 않는다. 그래프는 격리 검사와 같은
 * `import-graph.ts`로 만든다. 그래서 `ui/furigana.ts`처럼 공개 화면과 함께 쓰는 모듈은 이 목록 안에 있다.
 */
const PRIVATE_ENTRY = 'private.ts'
const PRIVATE_ALLOWED_KEYS: readonly StoreKey[] = ['nc.furigana.v1']

function privateGraphSlotKeys(project: Project): { keys: string[]; violations: string[] } {
  const graph = fullGraph(project, PRIVATE_ENTRY)
  const sources = [...graph].sort().map((path) => parse(path, project.read(path)))
  const { calls, violations } = collectSlotCalls(sources)
  const keys = [...new Set(calls.map((call) => call.key))].sort()
  return {
    keys,
    violations: [
      ...violations,
      ...keys
        .filter((key) => !(PRIVATE_ALLOWED_KEYS as readonly string[]).includes(key))
        .map((key) => `private graph creates localSlot('${key}')`),
    ],
  }
}

describe('private graph storage keys', () => {
  it('reaches only nc.furigana.v1 from private.ts', () => {
    const project = createProject()
    // 그래프가 실제 로그인 영역을 담는다. 비어서 초록인 것이 아니다.
    expect(fullGraph(project, PRIVATE_ENTRY)).toContain('ui/study.ts')
    expect(privateGraphSlotKeys(project).violations).toEqual([])
  })

  it('positive control: flags nc.demo.v1 created in a module the private graph reaches', () => {
    const study = createProject().read('ui/study.ts')
    const project = createProject({
      'ui/study.ts': `${study}\nimport { localSlot } from '../local-store'\nlocalSlot('nc.demo.v1', isDemo)\n`,
    })
    const result = privateGraphSlotKeys(project)
    expect(result.keys).toContain('nc.demo.v1')
    expect(result.violations).toContain(`private graph creates localSlot('nc.demo.v1')`)
  })

  it('positive control: follows a transitive and a dynamic import into a kana slot', () => {
    const privateSource = createProject().read(PRIVATE_ENTRY)
    const project = createProject({
      [PRIVATE_ENTRY]: `${privateSource}\nexport const later = () => import('./ui/probe-slot')\n`,
      'ui/probe-slot.ts': `import '../kana/progress'\n`,
    })
    expect(privateGraphSlotKeys(project).violations).toContain(`private graph creates localSlot('nc.kana.v1')`)
  })

  it('positive control: allows nc.furigana.v1 and ignores slots outside the private graph', () => {
    // 실제 로그인 영역과 무관한 합성 그래프다. 실제 소스가 바뀌어도 이 대조군의 결과는 같다.
    const project = createProject({
      [PRIVATE_ENTRY]: `import './ui/probe-furigana'\n`,
      'ui/probe-furigana.ts': `import { localSlot } from '../local-store'\nlocalSlot('nc.furigana.v1', isFlag)\n`,
      'demo/probe-slot.ts': `import { localSlot } from '../local-store'\nlocalSlot('nc.demo.v1', isDemo)\n`,
    })
    const result = privateGraphSlotKeys(project)
    expect(result.keys).toEqual(['nc.furigana.v1'])
    expect(result.violations.filter((line) => line.startsWith('private graph'))).toEqual([])
  })
})
