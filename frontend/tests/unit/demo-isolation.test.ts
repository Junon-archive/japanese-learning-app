/**
 * 공개 화면 셋(선택 홈, Public Demo, 가나 학습)의 격리. **불변식 13: 세 화면은 서버 요청 0건이고 API
 * 모듈에 정적 import로도 동적 import로도 닿지 않는다.** 규칙의 canonical은
 * `spec/04_SECURITY_AND_DATA.md`의 `격리 검사 (MVP-02 확정)`, 결정 배경은 ADR-022 결정 2다.
 *
 * ``` text
 * (a) main.ts 정적 그래프에 api·endpoints·env·private 없음
 * (b) home/ demo/ kana/ 아래 모든 모듈의 정적 + 리터럴 동적 그래프에 위 넷 없음 (디렉터리 기준)
 * (c) API 모듈에 닿는 동적 import는 main.ts -> private.ts 하나. main.ts 정적 그래프 안의 동적 import 대상은
 *     private.ts이거나 home·demo·kana 아래
 * (d) src/ 전체 금지 목록 (fail-closed 지정자, 코드 생성, 네트워크 원시 API, HTML 삽입, 동적 URL·이동)
 * (e) 현재 소스로 빌드한 entry 청크에 env.ts의 기본 origin 없음. 어떤 청크에는 있음
 * ```
 *
 * 규칙마다 **합성 소스 양성 대조군**이 있다. 판정 함수가 아무것도 내지 않는 식으로 초록이 되면 안 된다.
 * 합성 소스는 `createProject`의 overlay로만 얹고 디스크에 쓰지 않는다.
 *
 * **한계:** 이 검사는 실수 방지용이다. 검사가 모르는 새 API나 여러 단계 간접 참조 같은 의도적인 우회는
 * 막지 못한다. 부팅 런타임 단정(`login-entry.test.ts`)과 브라우저 e2e (f)가 결과(요청 0건)로 받친다.
 * 이름 기반으로 판정하는 규칙(`sendBeacon`, `innerHTML` 등)은 같은 이름의 무관한 멤버도 막는다 --- 더
 * 엄격한 쪽이다.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import { buildOutput, walk } from './build-output'
import type { Finding, Project } from './import-graph'
import { createProject, fullGraph, lineOf, SRC, staticGraph } from './import-graph'

const API_MODULES = ['api.ts', 'endpoints.ts', 'env.ts']
const PRIVATE = 'private.ts'
const FORBIDDEN = [...API_MODULES, PRIVATE]
const PUBLIC_DIRS = ['home/', 'demo/', 'kana/']
const MAIN = 'main.ts'
const ROUTES = 'routes.ts'

/** 넉넉한 시간. 첫 타입 검사 program은 lib.dom.d.ts를 파싱한다. */
const TYPED_TIMEOUT_MS = 120_000
const BUILD_TIMEOUT_MS = 600_000

const isPublic = (file: string): boolean => PUBLIC_DIRS.some((dir) => file.startsWith(dir))

// ---------------------------------------------------------------------------------------------
// (a)(b)(c) 그래프 판정
// ---------------------------------------------------------------------------------------------

function checkA(project: Project): string[] {
  const graph = staticGraph(project, MAIN)
  return FORBIDDEN.filter((file) => graph.has(file))
}

function checkB(project: Project): string[] {
  return project.files.filter(isPublic).flatMap((file) => {
    const graph = fullGraph(project, file)
    return FORBIDDEN.filter((forbidden) => graph.has(forbidden)).map((forbidden) => `${file} -> ${forbidden}`)
  })
}

/** API 모듈에 닿는 동적 import 간선(`private.ts` 정적 그래프 밖). */
function apiDynamicEdges(project: Project): string[] {
  const privateGraph = staticGraph(project, PRIVATE)
  return project.files
    .filter((file) => !privateGraph.has(file))
    .flatMap((file) => project.scan(file).edges)
    .filter((edge) => edge.dynamic)
    .filter((edge) => API_MODULES.some((api) => fullGraph(project, edge.to).has(api)))
    .map((edge) => `${edge.from} -> ${edge.to}`)
}

/** `main.ts` 정적 그래프 안에서 대상이 private.ts도 공개 화면도 아닌 동적 import. */
function strayMainDynamicImports(project: Project): string[] {
  return [...staticGraph(project, MAIN)]
    .flatMap((file) => project.scan(file).edges)
    .filter((edge) => edge.dynamic && edge.to !== PRIVATE && !isPublic(edge.to))
    .map((edge) => `${edge.from}:${edge.line} -> ${edge.to}`)
}

// ---------------------------------------------------------------------------------------------
// (d) 금지 목록 판정
// ---------------------------------------------------------------------------------------------

/** 전역 객체를 가리키는 이름. `window.window`, `top.fetch`, `document.defaultView.fetch`처럼 이어도 전역이다. */
const GLOBAL_OBJECTS = new Set(['window', 'globalThis', 'self', 'top', 'parent', 'frames'])
/** 동적 값을 넣으면 위반인 URL 속성 대입(`iframe.src =`, `form.action =`, `object.data =` 등). 리터럴은 허용. */
const URL_PROPERTIES = new Set(['src', 'action', 'formAction', 'data'])
const NETWORK_GLOBALS = new Set(['fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource'])
const CODE_GLOBALS = new Set(['eval', 'Function', 'require'])
const WORKER_GLOBALS = new Set(['Worker', 'SharedWorker'])
const TIMER_GLOBALS = new Set(['setTimeout', 'setInterval'])
const HTML_SINKS = new Set([
  'innerHTML',
  'outerHTML',
  'insertAdjacentHTML',
  'createContextualFragment',
  'parseFromString',
  'srcdoc',
])

function memberName(node: ts.Node): string | undefined {
  if (ts.isPropertyAccessExpression(node)) return node.name.text
  if (ts.isElementAccessExpression(node) && ts.isStringLiteralLike(node.argumentExpression)) {
    return node.argumentExpression.text
  }
  return undefined
}

function inTypePosition(node: ts.Node): boolean {
  for (let current = node.parent; current !== undefined; current = current.parent) {
    if (ts.isTypeNode(current)) return true
  }
  return false
}

function unwrapExpression(node: ts.Expression): ts.Expression {
  let current = node
  while (ts.isParenthesizedExpression(current) || ts.isAsExpression(current) || ts.isNonNullExpression(current)) {
    current = current.expression
  }
  return current
}

/** 전역 객체 식인가: `window`, `window.window`, `top`, `globalThis.parent`, `document.defaultView`. */
function isGlobalObject(node: ts.Expression): boolean {
  const current = unwrapExpression(node)
  if (ts.isIdentifier(current)) return GLOBAL_OBJECTS.has(current.text)
  if (!(ts.isPropertyAccessExpression(current) || ts.isElementAccessExpression(current))) return false
  const name = memberName(current)
  if (name === 'defaultView') return isDocument(current.expression) || isGlobalObject(current.expression)
  return name !== undefined && GLOBAL_OBJECTS.has(name) && isGlobalObject(current.expression)
}

/** 전역 `name`을 가리키는 식이면 그 이름: `name`, `window.name`, `globalThis['name']`, `window.window.name`. */
function globalName(node: ts.Node): string | undefined {
  if (ts.isIdentifier(node)) {
    const parent = node.parent
    if (ts.isPropertyAccessExpression(parent) && parent.name === node) return undefined
    const namedMember =
      ts.isPropertyAssignment(parent) ||
      ts.isPropertySignature(parent) ||
      ts.isPropertyDeclaration(parent) ||
      ts.isMethodDeclaration(parent) ||
      ts.isMethodSignature(parent)
    if (namedMember && parent.name === node) return undefined
    if (inTypePosition(node)) return undefined
    return node.text
  }
  if ((ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) && isGlobalObject(node.expression)) {
    return memberName(node)
  }
  return undefined
}

/** `location`, `window.location`, `document.location` */
function isLocation(node: ts.Expression): boolean {
  return (ts.isIdentifier(node) && node.text === 'location') || memberName(node) === 'location'
}

function isDocument(node: ts.Expression): boolean {
  return (ts.isIdentifier(node) && node.text === 'document') || memberName(node) === 'document'
}

function isFunctionValue(node: ts.Expression | undefined, checker: ts.TypeChecker): boolean {
  if (node === undefined) return false
  if (ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return true
  if (ts.isStringLiteralLike(node) || ts.isTemplateExpression(node) || ts.isBinaryExpression(node)) return false
  // 식별자(`setTimeout(resolve, ms)`) 등은 타입으로 본다. any·unknown·string은 호출 시그니처가 없어 위반이다.
  return checker.getTypeAtLocation(node).getCallSignatures().length > 0
}

/** `routes.ts`에 선언된, 문자열 리터럴로 초기화된 `const`(예: `HOME_HASH`). */
function isRouteConstant(node: ts.Expression | undefined, project: Project, checker: ts.TypeChecker): boolean {
  if (node === undefined || !(ts.isIdentifier(node) || ts.isPropertyAccessExpression(node))) return false
  let symbol = checker.getSymbolAtLocation(node)
  if (symbol !== undefined && symbol.flags & ts.SymbolFlags.Alias) symbol = checker.getAliasedSymbol(symbol)
  const declaration = symbol?.valueDeclaration
  return (
    declaration !== undefined &&
    ts.isVariableDeclaration(declaration) &&
    ts.isVariableDeclarationList(declaration.parent) &&
    (declaration.parent.flags & ts.NodeFlags.Const) !== 0 &&
    declaration.initializer !== undefined &&
    ts.isStringLiteralLike(declaration.initializer) &&
    project.rel(declaration.getSourceFile().fileName) === ROUTES
  )
}

const isAssignment = (node: ts.BinaryExpression): boolean =>
  node.operatorToken.kind >= ts.SyntaxKind.FirstAssignment && node.operatorToken.kind <= ts.SyntaxKind.LastAssignment

/** `src/`의 한 모듈이 (d) 목록에 걸리는 곳 전부. 지정자 fail-closed finding을 포함한다. */
function forbiddenUses(project: Project, file: string): Finding[] {
  const { sourceFile, checker } = project.typed(file)
  const findings: Finding[] = [...project.scan(file).findings]
  const report = (node: ts.Node, rule: string): void => {
    findings.push({ file, line: lineOf(node), rule, text: node.getText(sourceFile).slice(0, 120) })
  }

  function visit(node: ts.Node): void {
    const global = globalName(node)
    if (global !== undefined) {
      if (NETWORK_GLOBALS.has(global) && file !== 'api.ts') report(node, 'network API outside api.ts')
      if (CODE_GLOBALS.has(global)) report(node, `${global}`)
      if (WORKER_GLOBALS.has(global)) report(node, 'Worker')
    }

    const member = memberName(node)
    if (member === 'sendBeacon' && file !== 'api.ts') report(node, 'network API outside api.ts')
    if (member !== undefined && HTML_SINKS.has(member)) report(node, 'HTML insertion')
    if (
      (ts.isPropertyAssignment(node) || ts.isShorthandPropertyAssignment(node)) &&
      ts.isIdentifier(node.name) &&
      HTML_SINKS.has(node.name.text)
    ) {
      report(node, 'HTML insertion')
    }

    if (ts.isMetaProperty(node) && node.keywordToken === ts.SyntaxKind.ImportKeyword) {
      const name = memberName(node.parent)
      if (name === undefined) report(node, 'import.meta as a value')
      else if (name.startsWith('glob')) report(node.parent, 'import.meta.glob')
      else if (name === 'env' && file !== 'env.ts') report(node.parent, 'import.meta.env outside env.ts')
    }

    if (ts.isCallExpression(node)) {
      const callee = node.expression
      const [first, second] = node.arguments
      const calleeGlobal = globalName(callee)
      const calleeMember = memberName(callee)

      if (calleeGlobal !== undefined && TIMER_GLOBALS.has(calleeGlobal) && !isFunctionValue(first, checker)) {
        report(node, 'timer with a non-function argument')
      }
      if (calleeMember === 'createElement' || calleeMember === 'createElementNS') {
        // createElementNS(namespace, tag): 태그는 두 번째 인자다. SVG의 <script>도 실행된다.
        const tag = calleeMember === 'createElement' ? first : second
        const literal = tag !== undefined && ts.isStringLiteralLike(tag)
        if (!literal || tag.text.trim().toLowerCase() === 'script') report(node, 'createElement')
      }
      if (calleeMember === 'setAttribute' || calleeMember === 'setAttributeNS') {
        // setAttributeNS(namespace, name, value): 이름·값이 한 칸씩 뒤다. `xlink:href`는 접두사를 떼고 본다.
        const offset = calleeMember === 'setAttribute' ? 0 : 1
        const nameArgument = node.arguments[offset]
        const valueArgument = node.arguments[offset + 1]
        if (nameArgument === undefined || !ts.isStringLiteralLike(nameArgument)) {
          report(node, 'setAttribute with a dynamic name')
        } else {
          const name = nameArgument.text.trim().toLowerCase().split(':').pop() ?? ''
          if (name.startsWith('on') || name === 'srcdoc') report(node, 'setAttribute on*/srcdoc')
          if (
            (name === 'href' || name === 'src') &&
            (valueArgument === undefined || !ts.isStringLiteralLike(valueArgument))
          ) {
            report(node, 'setAttribute href/src with a dynamic value')
          }
        }
      }
      if (
        (calleeMember === 'write' || calleeMember === 'writeln') &&
        ts.isPropertyAccessExpression(callee) &&
        isDocument(callee.expression)
      ) {
        report(node, 'HTML insertion')
      }
      const locationCall =
        (calleeMember === 'assign' || calleeMember === 'replace') &&
        (ts.isPropertyAccessExpression(callee) || ts.isElementAccessExpression(callee)) &&
        isLocation(callee.expression)
      if ((locationCall || calleeGlobal === 'open') && !isRouteConstant(first, project, checker)) {
        report(node, 'navigation to a non-route value')
      }
    }

    if (ts.isBinaryExpression(node) && isAssignment(node)) {
      const target = node.left
      const navigates = memberName(target) === 'href' || isLocation(target)
      const fixed = node.operatorToken.kind === ts.SyntaxKind.EqualsToken && isRouteConstant(node.right, project, checker)
      if (navigates && !fixed) report(node, 'navigation to a non-route value')
      const urlProperty = memberName(target)
      if (
        urlProperty !== undefined &&
        URL_PROPERTIES.has(urlProperty) &&
        !(node.operatorToken.kind === ts.SyntaxKind.EqualsToken && ts.isStringLiteralLike(node.right))
      ) {
        report(node, 'URL property with a dynamic value')
      }
    }

    ts.forEachChild(node, visit)
  }
  visit(sourceFile)
  return findings
}

// ---------------------------------------------------------------------------------------------
// 실제 src/
// ---------------------------------------------------------------------------------------------

describe('isolation graph (a)(b)(c)', () => {
  const project = createProject()

  it('(a) keeps the API modules and private.ts out of the static graph of main.ts', () => {
    expect(staticGraph(project, MAIN).size).toBeGreaterThan(1)
    expect(checkA(project)).toEqual([])
  })

  it('(b) keeps every module under home/, demo/, kana/ away from them, statically and dynamically', () => {
    // 디렉터리 기준이다. kana/는 아직 없어도 된다. 대상이 0개로 초록이 되지는 않게 한다.
    expect(project.files.filter(isPublic).length).toBeGreaterThan(0)
    expect(checkB(project)).toEqual([])
  })

  it('(c) enters the API modules through exactly one dynamic import, main.ts -> private.ts', () => {
    expect(apiDynamicEdges(project)).toEqual([`${MAIN} -> ${PRIVATE}`])
    expect(strayMainDynamicImports(project)).toEqual([])
  })

  it('positive control: the private graph does reach endpoints.ts', () => {
    expect(staticGraph(project, PRIVATE).has('endpoints.ts')).toBe(true)
  })
})

describe('forbidden uses (d)', () => {
  it(
    'finds none anywhere in src/',
    () => {
      const project = createProject()
      const findings = project.files.flatMap((file) => forbiddenUses(project, file))
      expect(findings.map((f) => `${f.file}:${f.line} ${f.rule}: ${f.text}`)).toEqual([])
    },
    TYPED_TIMEOUT_MS,
  )
})

describe('demo source', () => {
  const files = ['demo/demo.ts', 'demo/fixture.ts'].map((name) => ({
    name,
    source: readFileSync(join(SRC, name), 'utf8'),
  }))

  it('keeps demo state out of every persistent store', () => {
    // demo 상태는 browser memory/session 수준에서만 유지한다(04_SECURITY_AND_DATA.md).
    // 주석에서 이름을 언급하는 것은 막지 않는다 --- 접근 형태만 찾는다.
    const patterns = [
      /localStorage\s*[.[]/,
      /sessionStorage\s*[.[]/,
      /indexedDB\s*[.[]/i,
      /document\.cookie/,
    ]

    for (const pattern of patterns) {
      expect(files.filter((file) => pattern.test(file.source)).map((f) => f.name)).toEqual([])
    }
  })

  it('reaches the renderers it reuses', () => {
    // 격리가 "demo가 자기 화면을 따로 만들었다"로 달성되면 안 된다. 실제 학습 화면과
    // 같은 코드여야 한다(03_UI_UX_SPEC.md의 `Demo`).
    const graph = fullGraph(createProject(), 'demo/demo.ts')
    for (const module of [
      'ui/interactions.ts',
      'ui/segments.ts',
      // (D3 임시) ui/progress.ts·ui/session-end.ts는 demo에서 뺐다. D7에서 이 목록을 다시 쓴다.
      'demo/fixture.ts',
    ]) {
      expect(graph).toContain(module)
    }
  })
})

// ---------------------------------------------------------------------------------------------
// (e) 빌드 산출물
// ---------------------------------------------------------------------------------------------

/** `env.ts`의 기본 origin 리터럴. 테스트에 적지 않고 소스에서 읽는다. */
function defaultOrigin(): string {
  const origins: string[] = []
  const visit = (node: ts.Node): void => {
    if (ts.isStringLiteralLike(node) && /^https?:\/\//.test(node.text)) origins.push(node.text)
    ts.forEachChild(node, visit)
  }
  visit(createProject().sourceFile('env.ts'))
  expect(origins).toHaveLength(1)
  return origins[0]!
}

/** index.html의 module script와 그것이 정적으로 import하는 청크(전이). 동적 `import()`는 따라가지 않는다. */
function entryChunks(dir: string): string[] {
  const html = readFileSync(join(dir, 'index.html'), 'utf8')
  const entries = [...html.matchAll(/<script\b[^>]*\btype="module"[^>]*\bsrc="\/([^"]+)"/g)].map((m) => join(dir, m[1]!))
  expect(entries.length).toBeGreaterThan(0)

  const seen = new Set<string>()
  const queue = [...entries]
  while (queue.length > 0) {
    const chunk = queue.pop()!
    if (seen.has(chunk)) continue
    seen.add(chunk)
    const code = readFileSync(chunk, 'utf8')
    for (const match of code.matchAll(/\b(?:import|export)\s*(?:[\w$*{}\s,]*?\bfrom\s*)?["']\.\/([^"']+\.js)["']/g)) {
      queue.push(join(chunk, '..', match[1]!))
    }
  }
  return [...seen]
}

describe('build output (e)', () => {
  it(
    'keeps the default API origin out of the entry chunk and ships it in some chunk',
    () => {
      const origin = defaultOrigin()
      const { dir, files } = buildOutput()

      const entry = entryChunks(dir)
      expect(entry.filter((chunk) => readFileSync(chunk, 'utf8').includes(origin))).toEqual([])

      // 양성 대조군: 문자열이 어디에도 없어서 초록인 것이 아니다.
      const chunks = walk(join(dir, 'assets')).filter((path) => path.endsWith('.js'))
      expect(files).toEqual(expect.arrayContaining(chunks))
      expect(chunks.some((chunk) => readFileSync(chunk, 'utf8').includes(origin))).toBe(true)
    },
    BUILD_TIMEOUT_MS,
  )
})

// ---------------------------------------------------------------------------------------------
// 양성 대조군: 합성 소스
// ---------------------------------------------------------------------------------------------

describe('positive controls: graph checks on synthetic sources', () => {
  it('(a) flags main.ts statically importing an API module', () => {
    const main = `${readFileSync(join(SRC, MAIN), 'utf8')}\nimport './endpoints'\n`
    expect(checkA(createProject({ [MAIN]: main }))).toContain('endpoints.ts')
  })

  it('(b) flags a new kana/ module importing ../api, with no test change', () => {
    const project = createProject({ 'kana/probe.ts': "import '../api'\n" })
    expect(checkB(project)).toEqual(expect.arrayContaining(['kana/probe.ts -> api.ts']))
  })

  it('(b) follows literal dynamic imports', () => {
    const project = createProject({ 'demo/probe.ts': "export const load = () => import('../private')\n" })
    expect(checkB(project)).toEqual(expect.arrayContaining(['demo/probe.ts -> private.ts']))
  })

  it('(c) flags a route that dynamically imports a login-area screen', () => {
    const routes = `${readFileSync(join(SRC, ROUTES), 'utf8')}\nexport const study = () => import('./ui/study')\n`
    const project = createProject({ [ROUTES]: routes })
    expect(apiDynamicEdges(project)).toContain(`${ROUTES} -> ui/study.ts`)
    expect(strayMainDynamicImports(project).some((edge) => edge.startsWith(`${ROUTES}:`))).toBe(true)
  })
})

describe('positive controls: forbidden uses on synthetic sources', () => {
  const DECLARATIONS = 'declare const el: HTMLElement\ndeclare const v: string\ndeclare const code: string\ndeclare const tag: string\n'

  const VIOLATIONS: [string, string, string][] = [
    ['concatenated import()', "export const m = () => import('../' + 'api')", 'non-literal import()'],
    ['variable import()', "const s = '../api'\nexport const m = () => import(s)", 'non-literal import()'],
    ['two-argument import()', "export const m = () => import('../api', {})", 'non-literal import()'],
    ['import.meta.glob', "export const m = import.meta.glob('../*.ts')", 'import.meta.glob'],
    ['import.meta.env outside env.ts', 'export const m = import.meta.env.VITE_API_BASE_URL', 'import.meta.env outside env.ts'],
    ['unresolvable .js specifier', "import '../api.js'", 'unresolved specifier'],
    ['unresolvable relative specifier', "import './missing'", 'unresolved specifier'],
    ['bare specifier', "import 'some-pkg'", 'bare specifier'],
    ['?worker specifier', "import W from '../private?worker'\nexport { W }", 'query specifier'],
    ['?raw dynamic specifier', "export const m = () => import('../x?raw')", 'query specifier'],
    ['require()', "export const m = require('../api')", 'require'],
    ['fetch outside api.ts', "void fetch('x')", 'network API outside api.ts'],
    ['window.fetch outside api.ts', "void window.fetch('x')", 'network API outside api.ts'],
    ['XMLHttpRequest', 'export const x = new XMLHttpRequest()', 'network API outside api.ts'],
    ['sendBeacon', "navigator.sendBeacon('x')", 'network API outside api.ts'],
    ['WebSocket', "export const x = new WebSocket('ws://x')", 'network API outside api.ts'],
    ['EventSource', "export const x = new EventSource('x')", 'network API outside api.ts'],
    ['new Worker', "export const x = new Worker('x')", 'Worker'],
    ['new SharedWorker', "export const x = new SharedWorker('x')", 'Worker'],
    ['eval', 'eval(code)', 'eval'],
    ['Function constructor', 'export const f = new Function(code)', 'Function'],
    ['setTimeout(code)', 'setTimeout(code)', 'timer with a non-function argument'],
    ["setTimeout('code')", "setTimeout('x()', 0)", 'timer with a non-function argument'],
    ['setInterval(template)', 'setInterval(`${code}`, 10)', 'timer with a non-function argument'],
    ['createElement(tag)', 'document.createElement(tag)', 'createElement'],
    ["createElement('script')", "document.createElement('script')", 'createElement'],
    ['innerHTML assignment', 'el.innerHTML = v', 'HTML insertion'],
    ['outerHTML assignment', 'el.outerHTML = v', 'HTML insertion'],
    ['insertAdjacentHTML', "el.insertAdjacentHTML('beforeend', v)", 'HTML insertion'],
    ['document.write', 'document.write(v)', 'HTML insertion'],
    ['document.writeln', 'document.writeln(v)', 'HTML insertion'],
    ['createContextualFragment', 'new Range().createContextualFragment(v)', 'HTML insertion'],
    ['DOMParser.parseFromString', "new DOMParser().parseFromString(v, 'text/html')", 'HTML insertion'],
    ['iframe srcdoc', "document.createElement('iframe').srcdoc = v", 'HTML insertion'],
    ["setAttribute('onclick', v)", "el.setAttribute('onclick', v)", 'setAttribute on*/srcdoc'],
    ["setAttribute('onclick', 'x()')", "el.setAttribute('onclick', 'x()')", 'setAttribute on*/srcdoc'],
    ["setAttribute('srcdoc', literal)", "el.setAttribute('srcdoc', '<p>x</p>')", 'setAttribute on*/srcdoc'],
    ["setAttribute('href', v)", "el.setAttribute('href', v)", 'setAttribute href/src with a dynamic value'],
    ["setAttribute('src', v)", "el.setAttribute('src', v)", 'setAttribute href/src with a dynamic value'],
    ['setAttribute(name, v)', 'el.setAttribute(v, v)', 'setAttribute with a dynamic name'],
    ['location.href = v', 'location.href = v', 'navigation to a non-route value'],
    ["location.href = 'literal'", "location.href = '#/x'", 'navigation to a non-route value'],
    ['location.assign(v)', 'location.assign(v)', 'navigation to a non-route value'],
    ['location.replace(v)', 'window.location.replace(v)', 'navigation to a non-route value'],
    ['window.open(v)', 'window.open(v)', 'navigation to a non-route value'],
    ['a.href = v', "document.createElement('a').href = v", 'navigation to a non-route value'],
    ['createElementNS(ns, tag)', "document.createElementNS('http://www.w3.org/2000/svg', tag)", 'createElement'],
    [
      "createElementNS(ns, 'script')",
      "document.createElementNS('http://www.w3.org/2000/svg', 'script')",
      'createElement',
    ],
    ["setAttributeNS(ns, 'onload', literal)", "el.setAttributeNS(null, 'onload', 'x()')", 'setAttribute on*/srcdoc'],
    ["setAttributeNS(ns, 'srcdoc', literal)", "el.setAttributeNS(null, 'srcdoc', '<p>x</p>')", 'setAttribute on*/srcdoc'],
    [
      "setAttributeNS(xlink, 'xlink:href', v)",
      "el.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', v)",
      'setAttribute href/src with a dynamic value',
    ],
    ["setAttributeNS(ns, 'src', v)", "el.setAttributeNS(null, 'src', v)", 'setAttribute href/src with a dynamic value'],
    ['setAttributeNS(ns, name, v)', 'el.setAttributeNS(null, v, v)', 'setAttribute with a dynamic name'],
    ['iframe.src = v', "document.createElement('iframe').src = v", 'URL property with a dynamic value'],
    ['img.src = v', "document.createElement('img').src = v", 'URL property with a dynamic value'],
    ['form.action = v', "document.createElement('form').action = v", 'URL property with a dynamic value'],
    ['button.formAction = v', "document.createElement('button').formAction = v", 'URL property with a dynamic value'],
    ['object.data = v', "document.createElement('object').data = v", 'URL property with a dynamic value'],
    ['window.window.fetch', "void window.window.fetch('x')", 'network API outside api.ts'],
    ['top.fetch', "void top.fetch('x')", 'network API outside api.ts'],
    ['parent.eval', 'parent.eval(code)', 'eval'],
    ['frames.WebSocket', "export const x = new frames.WebSocket('ws://x')", 'network API outside api.ts'],
    ['document.defaultView.fetch', "void document.defaultView?.fetch('x')", 'network API outside api.ts'],
    ['globalThis.self.setTimeout(code)', 'globalThis.self.setTimeout(code)', 'timer with a non-function argument'],
  ]

  const ALLOWED: [string, string][] = [
    ['a function identifier as the timer argument', 'declare const resolve: () => void\nsetTimeout(resolve, 10)'],
    ['an arrow function as the timer argument', 'setInterval(() => {}, 10)'],
    ['a literal non-script element', "document.createElement('div')"],
    ['a literal plain attribute', "el.setAttribute('role', v)"],
    ['a literal href', "el.setAttribute('href', '#/demo')"],
    ['a route constant for navigation', "import { HOME_HASH } from '../routes'\nlocation.href = HOME_HASH\nwindow.open(HOME_HASH)"],
    ['a literal dynamic import of a public module', "export const m = () => import('./demo')"],
    ['a stylesheet import', "import '../styles.css'"],
    ['an explicit .ts specifier', "import '../ids.ts'"],
    ['a string method named replace', "export const s = v.replace('a', 'b')"],
    ['a literal element namespace tag', "document.createElementNS('http://www.w3.org/2000/svg', 'svg')"],
    ['a literal URL property', "document.createElement('img').src = '/icons/icon-192.png'"],
    ['a plain setAttributeNS', "el.setAttributeNS(null, 'viewBox', v)"],
    ['a local object named data', 'const box = { data: 1 }\nbox.data === 1'],
  ]

  const overlay: Record<string, string> = {}
  VIOLATIONS.forEach(([, source], index) => {
    overlay[`demo/violation-${index}.ts`] = `${DECLARATIONS}${source}\n`
  })
  ALLOWED.forEach(([, source], index) => {
    overlay[`demo/allowed-${index}.ts`] = `${DECLARATIONS}${source}\n`
  })
  overlay['env-probe.ts'] = 'export const x = import.meta.env.VITE_API_BASE_URL\n'
  const project = createProject(overlay)

  VIOLATIONS.forEach(([name, , rule], index) => {
    it(
      `flags ${name}`,
      () => {
        const rules = forbiddenUses(project, `demo/violation-${index}.ts`).map((finding) => finding.rule)
        expect(rules).toContain(rule)
      },
      TYPED_TIMEOUT_MS,
    )
  })

  ALLOWED.forEach(([name], index) => {
    it(
      `allows ${name}`,
      () => {
        expect(forbiddenUses(project, `demo/allowed-${index}.ts`)).toEqual([])
      },
      TYPED_TIMEOUT_MS,
    )
  })

  it('allows import.meta.env and fetch only in their own modules', () => {
    const own = createProject({
      'env.ts': 'export const x = import.meta.env.VITE_API_BASE_URL\n',
      'api.ts': "export const r = fetch('x')\n",
    })
    expect(forbiddenUses(own, 'env.ts')).toEqual([])
    expect(forbiddenUses(own, 'api.ts')).toEqual([])
    expect(forbiddenUses(project, 'env-probe.ts').map((f) => f.rule)).toContain('import.meta.env outside env.ts')
  }, TYPED_TIMEOUT_MS)
})
