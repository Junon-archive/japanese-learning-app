/**
 * 재생 API의 접근 범위(ADR-025 결정 4의 `모듈 경계`). TypeScript 컴파일러 AST로 `frontend/src/` 전체를
 * 훑어 **`speechSynthesis` / `SpeechSynthesisUtterance` 식별자가 `ui/speech.ts` 밖에 없다**를 단정한다.
 * `local-store.ts`의 `localStorage`를 보는 `local-storage-scope.test.ts`와 같은 방식이고, 규칙마다
 * **합성 소스로 양성 대조군**을 둔다 --- 검사가 "위반이 없다"고 말하는 것만으로는 검사가 실제로 위반을
 * 잡는지 알 수 없기 때문이다. 주석은 AST에 없으므로 주석에서 이름을 말하는 것은 막지 않는다.
 *
 * **계산된 속성 접근(`window['speechSynthesis']`, `globalThis['speech' + 'Synthesis']`)은 여기서 다시
 * 세지 않는다.** `local-storage-scope.test.ts`의 `has no computed property access or destructuring on
 * browser globals`가 전역 객체(`window`·`globalThis`·`self`·`document`·`navigator`·`history`·`location`)의
 * `[...]` 접근을 **종류를 가리지 않고** 이미 막는다. 그 규칙이 이 검사의 우회로를 닫는다.
 *
 * 그래프 쪽도 함께 본다. **재생은 학습 신호가 아니다**(불변식 25): `ui/speech.ts`가 API 모듈에도
 * `local-store.ts`에도 닿지 않아야 "서버로 아무것도 보내지 않고 재생 여부를 저장하지도 않는다"가
 * 구조로 참이 되고, 동시에 공개 화면(demo)의 import 그래프에 있어도 되는 모듈이 된다.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { extname, join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import ts from 'typescript'
import { describe, expect, it } from 'vitest'

import { createProject, fullGraph } from './import-graph'

const SRC = fileURLToPath(new URL('../../src', import.meta.url))

/** `src` 기준 경로(`/` 구분). 이 모듈만 재생 API를 만진다. */
const SPEECH_MODULE = 'ui/speech.ts'

/** 이 식별자는 `SPEECH_MODULE` 밖에 나오지 않는다. */
const SPEECH_GLOBALS = ['speechSynthesis', 'SpeechSynthesisUtterance'] as const

/** ADR-025가 정한 export 전부. 재생 상태나 synth 객체를 밖으로 내지 않는다. */
const SPEECH_EXPORTS = ['isSpeechAvailable', 'renderSpeakButton', 'speak']

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

type Source = { path: string; file: ts.SourceFile }

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

function loadSrc(): Source[] {
  return listFiles(SRC)
    .filter((full) => extname(full) in CODE_KINDS)
    .map((full) => parse(relative(SRC, full).split(sep).join('/'), readFileSync(full, 'utf8')))
}

function walk(node: ts.Node, visit: (node: ts.Node) => void): void {
  visit(node)
  node.forEachChild((child) => walk(child, visit))
}

function where(source: Source, node: ts.Node): string {
  const { line } = source.file.getLineAndCharacterOfPosition(node.getStart(source.file))
  return `${source.path}:${line + 1}`
}

function synthetic(files: Record<string, string>): Source[] {
  return Object.entries(files).map(([path, text]) => parse(path, text))
}

// ---------------------------------------------------------------------------
// 규칙
// ---------------------------------------------------------------------------

/**
 * 재생 API 식별자가 `ui/speech.ts` 밖에 나오는 곳 전부.
 *
 * 식별자를 이름으로 본다 --- `speechSynthesis`, `window.speechSynthesis`,
 * `const { speechSynthesis } = window`, `const s = speechSynthesis`,
 * `new SpeechSynthesisUtterance(...)`가 모두 걸린다.
 */
function speechGlobalsOutsideModule(sources: readonly Source[]): string[] {
  const names = new Set<string>(SPEECH_GLOBALS)
  const violations: string[] = []
  for (const source of sources) {
    if (source.path === SPEECH_MODULE) continue
    walk(source.file, (node) => {
      if (ts.isIdentifier(node) && names.has(node.text)) {
        violations.push(`${where(source, node)} ${node.text}`)
      }
    })
  }
  return violations
}

/** `ui/speech.ts`의 export 이름. 재-export(`export * from`)는 그 자체로 위반이다. */
function speechModuleExports(source: Source): { names: string[]; violations: string[] } {
  const names: string[] = []
  const violations: string[] = []
  for (const statement of source.file.statements) {
    if (ts.isExportDeclaration(statement) || ts.isExportAssignment(statement)) {
      violations.push(`${where(source, statement)} export declaration`)
      continue
    }
    const modifiers = ts.canHaveModifiers(statement) ? ts.getModifiers(statement) : undefined
    if (!modifiers?.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword)) continue
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        names.push(declaration.name.getText(source.file))
      }
    } else if (
      (ts.isFunctionDeclaration(statement) ||
        ts.isTypeAliasDeclaration(statement) ||
        ts.isInterfaceDeclaration(statement) ||
        ts.isClassDeclaration(statement)) &&
      statement.name !== undefined
    ) {
      names.push(statement.name.text)
    } else {
      violations.push(`${where(source, statement)} unexpected export`)
    }
  }
  return { names: [...names].sort(), violations }
}

// ---------------------------------------------------------------------------
// 실제 src
// ---------------------------------------------------------------------------

describe('speech API scope in frontend/src', () => {
  const sources = loadSrc()

  it('scans every file in src (only known non-code extensions are skipped)', () => {
    const skipped = listFiles(SRC)
      .map((full) => extname(full))
      .filter((extension) => !(extension in CODE_KINDS))
    expect(skipped.filter((extension) => !NON_CODE_EXTENSIONS.has(extension))).toEqual([])
    expect(sources.map((source) => source.path)).toContain(SPEECH_MODULE)
  })

  it('uses the speech identifiers only in ui/speech.ts', () => {
    expect(speechGlobalsOutsideModule(sources)).toEqual([])
  })

  it('positive control: ui/speech.ts really does use both identifiers', () => {
    // 규칙이 "아무도 쓰지 않아서" 초록인 것이 아니다. 예외로 둔 그 모듈이 실제로 둘 다 쓴다.
    const speech = sources.find((source) => source.path === SPEECH_MODULE)!
    const used = new Set<string>()
    walk(speech.file, (node) => {
      if (ts.isIdentifier(node) && (SPEECH_GLOBALS as readonly string[]).includes(node.text)) {
        used.add(node.text)
      }
    })
    expect([...used].sort()).toEqual([...SPEECH_GLOBALS].sort())
  })

  it('exports exactly the three names the ADR named', () => {
    const speech = sources.find((source) => source.path === SPEECH_MODULE)!
    const { names, violations } = speechModuleExports(speech)
    expect(violations).toEqual([])
    expect(names).toEqual([...SPEECH_EXPORTS].sort())
  })
})

describe('speech module graph', () => {
  const project = createProject()

  it('reaches neither the API modules, nor private.ts, nor local-store.ts', () => {
    // 불변식 25: 서버로 아무것도 보내지 않고 재생 여부를 브라우저에 저장하지도 않는다.
    const graph = fullGraph(project, SPEECH_MODULE)
    expect(graph).toContain(SPEECH_MODULE)
    expect(
      ['api.ts', 'endpoints.ts', 'env.ts', 'private.ts', 'local-store.ts'].filter((file) => graph.has(file)),
    ).toEqual([])
  })

  it('is reached by both the public english demo and the login area', () => {
    // 공개 화면과 로그인 영역이 같은 모듈을 쓴다(ADR-025 결정 4의 `모듈 경계`).
    expect(fullGraph(project, 'demo/en/demo.ts')).toContain(SPEECH_MODULE)
    expect(fullGraph(project, 'private.ts')).toContain(SPEECH_MODULE)
  })

  it('positive control: a speech module that imported endpoints.ts would be found', () => {
    const speech = project.read(SPEECH_MODULE)
    const dirty = createProject({ [SPEECH_MODULE]: `import '../endpoints'\n${speech}` })
    expect(fullGraph(dirty, SPEECH_MODULE)).toContain('endpoints.ts')
  })
})

// ---------------------------------------------------------------------------
// 양성 대조군: 합성 소스에서 규칙이 실제로 위반을 잡는다
// ---------------------------------------------------------------------------

describe('positive controls', () => {
  it('a clean synthetic tree passes', () => {
    const sources = synthetic({
      [SPEECH_MODULE]: `
        export function speak(text: string): void {
          speechSynthesis.cancel()
          speechSynthesis.speak(new SpeechSynthesisUtterance(text))
        }
      `,
      'ui/study.ts': `
        // speechSynthesis, SpeechSynthesisUtterance 를 주석에서 말하는 것은 괜찮다.
        import { renderSpeakButton } from './speech'
        const node = renderSpeakButton('hello', signal)
      `,
      'demo/demo.ts': `import { renderSpeakButton } from '../ui/speech'`,
    })
    expect(speechGlobalsOutsideModule(sources)).toEqual([])
  })

  it.each([
    ['direct call', `speechSynthesis.speak(utterance)`],
    ['window member', `window.speechSynthesis.cancel()`],
    ['globalThis member', `globalThis.speechSynthesis.getVoices()`],
    ['destructuring', `const { speechSynthesis } = window`],
    ['shorthand reference', `const synth = speechSynthesis`],
    ['typeof guard', `const ok = typeof speechSynthesis !== 'undefined'`],
    ['new utterance', `const u = new SpeechSynthesisUtterance('hi')`],
    ['utterance member', `const C = window.SpeechSynthesisUtterance`],
    ['type position', `let u: SpeechSynthesisUtterance | null = null`],
  ])('speech identifier outside ui/speech.ts: %s', (_name, text) => {
    expect(speechGlobalsOutsideModule(synthetic({ 'ui/study.ts': text })).length).toBeGreaterThan(0)
  })

  it.each([
    ['a fourth export', `export function cancelAll(): void {}`],
    ['an exported const', `export const synth = null`],
    ['a re-export', `export * from './other'`],
  ])('ui/speech.ts with %s', (_name, extra) => {
    const source = synthetic({ [SPEECH_MODULE]: `export function speak(): void {}\n${extra}` })[0]!
    const { names, violations } = speechModuleExports(source)
    expect([...violations, ...names.filter((name) => !SPEECH_EXPORTS.includes(name))].length).toBeGreaterThan(0)
  })
})
