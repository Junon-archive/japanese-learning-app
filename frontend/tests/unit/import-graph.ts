/**
 * `src/`의 import 그래프. 격리 검사(`spec/04_SECURITY_AND_DATA.md`의 `격리 검사 (MVP-02 확정)`, ADR-022
 * 결정 2)가 쓰는 공용 helper다. **TypeScript 컴파일러 AST**로 만든다 --- 정규식은 조합 import와 주석을
 * 구분하지 못한다.
 *
 * ``` text
 * 정적 간선    ImportDeclaration, ExportDeclaration(from)의 문자열 지정자. import type·typeof import()도 센다
 * 동적 간선    import() 인자가 정확히 1개의 StringLiteral 또는 NoSubstitutionTemplateLiteral
 * 해석         상대(./ ../)와 루트(/, frontend 기준)만. base, base.ts, base/index.ts 순
 *              .css 파일은 그래프에서 뺀다
 * fail-closed  풀리지 않는 지정자, 그 밖의 비-TS 파일, bare 지정자, ? 쿼리 지정자, 비리터럴 import(),
 *              import = require() 는 간선을 만들지 않고 finding으로 낸다
 * ```
 *
 * 경로는 전부 `src/` 기준 상대 경로(`'demo/demo.ts'`)다. `overlay`로 합성 소스를 얹을 수 있다(양성 대조군).
 * 같은 경로의 실제 파일이 있으면 overlay가 이긴다. 디스크는 건드리지 않는다.
 */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { dirname, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

import ts from 'typescript'

export const FRONTEND = fileURLToPath(new URL('../..', import.meta.url))
export const SRC = join(FRONTEND, 'src')

export type Finding = { file: string; line: number; rule: string; text: string }
export type Edge = { from: string; to: string; dynamic: boolean; line: number }

type Resolution = { kind: 'module'; file: string } | { kind: 'asset' } | { kind: 'violation'; rule: string }

export type Project = {
  /** `src/` 아래 모든 `.ts` 모듈(overlay 포함), 정렬됨. */
  files: string[]
  read: (file: string) => string
  /** 이 파일만 파싱한 AST. 부모 노드가 설정되어 있다. */
  sourceFile: (file: string) => ts.SourceFile
  /** import 간선과 fail-closed finding. */
  scan: (file: string) => { edges: Edge[]; findings: Finding[] }
  /** 타입 검사기가 붙은 AST. 처음 부를 때 program을 만든다. */
  typed: (file: string) => { sourceFile: ts.SourceFile; checker: ts.TypeChecker }
  /** 절대 경로 -> `src/` 기준 경로. */
  rel: (absolute: string) => string
}

function walkTs(dir: string): string[] {
  if (!existsSync(dir)) return []
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) return walkTs(path)
    return path.endsWith('.ts') ? [path] : []
  })
}

export function lineOf(node: ts.Node): number {
  const sourceFile = node.getSourceFile()
  return sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1
}

/** program 사이에서 공유하는 파싱 결과. overlay가 아닌 파일(lib.dom.d.ts 포함)만 담는다. */
const sharedSourceFiles = new Map<string, ts.SourceFile>()

function compilerOptions(): ts.CompilerOptions {
  const configPath = join(FRONTEND, 'tsconfig.json')
  const config = ts.readConfigFile(configPath, (path) => ts.sys.readFile(path))
  return ts.parseJsonConfigFileContent(config.config, ts.sys, FRONTEND).options
}

export function createProject(overlay: Record<string, string> = {}): Project {
  const overlayAbsolute = new Map(Object.entries(overlay).map(([file, text]) => [join(SRC, file), text]))

  const rel = (absolute: string): string => relative(SRC, absolute).split(sep).join('/')
  const abs = (file: string): string => join(SRC, file)

  const isFile = (absolute: string): boolean =>
    overlayAbsolute.has(absolute) || (existsSync(absolute) && statSync(absolute).isFile())

  const files = [...new Set([...walkTs(SRC), ...overlayAbsolute.keys()].map(rel))].sort()

  const read = (file: string): string => overlayAbsolute.get(abs(file)) ?? readFileSync(abs(file), 'utf8')

  const parsed = new Map<string, ts.SourceFile>()
  const sourceFile = (file: string): ts.SourceFile => {
    let result = parsed.get(file)
    if (result === undefined) {
      result = ts.createSourceFile(abs(file), read(file), ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
      parsed.set(file, result)
    }
    return result
  }

  function resolveSpecifier(from: string, specifier: string): Resolution {
    if (specifier.includes('?')) return { kind: 'violation', rule: 'query specifier' }
    const relativeOrRoot = /^\.\.?(\/|$)/.test(specifier) || specifier.startsWith('/')
    if (!relativeOrRoot) return { kind: 'violation', rule: 'bare specifier' }

    const base = specifier.startsWith('/') ? join(FRONTEND, specifier) : resolve(dirname(abs(from)), specifier)
    for (const candidate of [base, `${base}.ts`, join(base, 'index.ts')]) {
      if (!isFile(candidate)) continue
      if (candidate.endsWith('.ts')) return { kind: 'module', file: rel(candidate) }
      if (candidate.endsWith('.css')) return { kind: 'asset' }
      return { kind: 'violation', rule: 'non-module file specifier' }
    }
    return { kind: 'violation', rule: 'unresolved specifier' }
  }

  const scans = new Map<string, { edges: Edge[]; findings: Finding[] }>()
  const scan = (file: string): { edges: Edge[]; findings: Finding[] } => {
    const cached = scans.get(file)
    if (cached !== undefined) return cached

    const edges: Edge[] = []
    const findings: Finding[] = []
    const source = sourceFile(file)

    function follow(node: ts.Node, specifier: string, dynamic: boolean): void {
      const resolution = resolveSpecifier(file, specifier)
      const line = lineOf(node)
      if (resolution.kind === 'module') edges.push({ from: file, to: resolution.file, dynamic, line })
      if (resolution.kind === 'violation') findings.push({ file, line, rule: resolution.rule, text: specifier })
    }

    function visit(node: ts.Node): void {
      if (
        (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) &&
        node.moduleSpecifier !== undefined &&
        ts.isStringLiteral(node.moduleSpecifier)
      ) {
        follow(node, node.moduleSpecifier.text, false)
      } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
        findings.push({ file, line: lineOf(node), rule: 'require()', text: node.getText(source) })
      } else if (ts.isImportTypeNode(node)) {
        const argument = node.argument
        if (ts.isLiteralTypeNode(argument) && ts.isStringLiteral(argument.literal)) {
          follow(node, argument.literal.text, false)
        } else {
          findings.push({ file, line: lineOf(node), rule: 'non-literal import()', text: node.getText(source) })
        }
      } else if (ts.isCallExpression(node) && node.expression.kind === ts.SyntaxKind.ImportKeyword) {
        const [argument] = node.arguments
        if (node.arguments.length === 1 && argument !== undefined && ts.isStringLiteralLike(argument)) {
          follow(node, argument.text, true)
        } else {
          findings.push({ file, line: lineOf(node), rule: 'non-literal import()', text: node.getText(source) })
        }
      }
      ts.forEachChild(node, visit)
    }
    visit(source)

    const result = { edges, findings }
    scans.set(file, result)
    return result
  }

  let program: ts.Program | undefined
  const typed = (file: string): { sourceFile: ts.SourceFile; checker: ts.TypeChecker } => {
    if (program === undefined) {
      const options = compilerOptions()
      const host = ts.createCompilerHost(options, true)
      const fileExists = host.fileExists.bind(host)
      const readFile = host.readFile.bind(host)
      const getSourceFile = host.getSourceFile.bind(host)
      host.fileExists = (path) => overlayAbsolute.has(resolve(path)) || fileExists(path)
      host.readFile = (path) => overlayAbsolute.get(resolve(path)) ?? readFile(path)
      host.getSourceFile = (path, languageVersion, onError, shouldCreate) => {
        const text = overlayAbsolute.get(resolve(path))
        if (text !== undefined) return ts.createSourceFile(path, text, languageVersion, true, ts.ScriptKind.TS)
        const cached = sharedSourceFiles.get(path)
        if (cached !== undefined) return cached
        const created = getSourceFile(path, languageVersion, onError, shouldCreate)
        if (created !== undefined) sharedSourceFiles.set(path, created)
        return created
      }
      program = ts.createProgram(files.map(abs), options, host)
    }
    const typedSource = program.getSourceFile(abs(file))
    if (typedSource === undefined) throw new Error(`${file} is not in the program`)
    return { sourceFile: typedSource, checker: program.getTypeChecker() }
  }

  return { files, read, sourceFile, scan, typed, rel }
}

/** `entry`에서 닿는 모든 모듈(자기 포함). `dynamic`이면 리터럴 동적 import도 따라간다. */
export function reach(project: Project, entry: string, options: { dynamic: boolean }): Set<string> {
  const seen = new Set<string>()
  const queue = [entry]
  while (queue.length > 0) {
    const file = queue.pop()!
    if (seen.has(file)) continue
    seen.add(file)
    for (const edge of project.scan(file).edges) {
      if (options.dynamic || !edge.dynamic) queue.push(edge.to)
    }
  }
  return seen
}

export const staticGraph = (project: Project, entry: string): Set<string> =>
  reach(project, entry, { dynamic: false })

export const fullGraph = (project: Project, entry: string): Set<string> => reach(project, entry, { dynamic: true })
