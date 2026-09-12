/**
 * Public Demo의 격리. **불변식이다: demo는 static frontend fixture이고 backend API를
 * 호출하지 않는다**(`04_SECURITY_AND_DATA.md`, `05_API_SPEC.md`, `10_ERROR_HANDLING.md`).
 *
 * **전이적** import를 훑는 것이 이 테스트의 핵심이다. 직접 import만 보면 한 다리 건너
 * 들어오는 것을 놓친다 --- 실제로 `ui/notice.ts`가 `api.ts`를 import하고 있었고, demo가
 * 안내 문구 하나를 쓰는 것만으로 API client가 번들에 딸려 들어올 뻔했다.
 *
 * 정적 검사와 런타임 검사를 **둘 다** 한다. 정적 검사는 "코드에 없다"를, 런타임 검사
 * (`demo.test.ts`)는 "그래서 아무것도 안 나간다"를 말한다. 정적 검사만 두면 동적
 * `import()`나 전역 `fetch` 호출을 놓치고, 런타임 검사만 두면 아직 안 지나간 분기를
 * 놓친다.
 */
import { existsSync, readFileSync } from 'node:fs'
import { dirname, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const SRC = fileURLToPath(new URL('../../src', import.meta.url))
const DEMO_ENTRY = resolve(SRC, 'demo/demo.ts')

/** `from '...'`와 side-effect import 양쪽을 잡는다. */
const IMPORT_PATTERN = /(?:from\s*|import\s*\(?\s*)['"]([^'"]+)['"]/g

function resolveModule(fromFile: string, specifier: string): string | null {
  // 상대 경로만 따라간다. bare specifier(패키지)는 이 프로젝트에 없다.
  if (!specifier.startsWith('.')) return null
  const base = resolve(dirname(fromFile), specifier)
  for (const candidate of [base, `${base}.ts`, `${base}/index.ts`]) {
    if (existsSync(candidate) && candidate.endsWith('.ts')) return candidate
  }
  // `.css` 같은 비-TS asset. 코드가 아니므로 그래프에서 뺀다.
  return null
}

/** 진입점에서 닿는 **모든** 모듈. `import type`도 뺴지 않는다(더 엄격한 쪽으로 센다). */
function importGraph(entry: string): string[] {
  const seen = new Set<string>()
  const queue = [entry]

  while (queue.length > 0) {
    const file = queue.pop()!
    if (seen.has(file)) continue
    seen.add(file)

    const source = readFileSync(file, 'utf8')
    for (const match of source.matchAll(IMPORT_PATTERN)) {
      const next = resolveModule(file, match[1]!)
      if (next !== null) queue.push(next)
    }
  }

  return [...seen].map((file) => relative(SRC, file))
}

describe('demo import graph', () => {
  it('never reaches the API client, transitively', () => {
    const graph = importGraph(DEMO_ENTRY)

    expect(graph).toContain('demo/demo.ts')
    expect(graph).not.toContain('api.ts')
    expect(graph).not.toContain('endpoints.ts')
    // origin을 아는 파일도 닿지 않는다. demo는 어떤 주소도 알 필요가 없다.
    expect(graph).not.toContain('env.ts')
    // 로그아웃도 여기 없다. demo에는 폐기할 auth session이 없다.
    expect(graph).not.toContain('ui/logout.ts')
  })

  it('does reach the renderers it reuses', () => {
    const graph = importGraph(DEMO_ENTRY)

    // 격리가 "demo가 자기 화면을 따로 만들었다"로 달성되면 안 된다. 실제 학습 화면과
    // 같은 코드여야 한다(03_UI_UX_SPEC.md의 `Demo`).
    for (const module of [
      'ui/interactions.ts',
      'ui/segments.ts',
      'ui/progress.ts',
      'ui/session-end.ts',
      'demo/fixture.ts',
    ]) {
      expect(graph).toContain(module)
    }
  })
})

describe('demo source', () => {
  const files = ['demo/demo.ts', 'demo/fixture.ts'].map((name) => ({
    name,
    source: readFileSync(resolve(SRC, name), 'utf8'),
  }))

  it('makes no network call of any kind', () => {
    const patterns: [string, RegExp][] = [
      ['fetch', /\bfetch\s*\(/],
      ['XMLHttpRequest', /XMLHttpRequest/],
      ['WebSocket', /WebSocket/],
      ['EventSource', /EventSource/],
      ['sendBeacon', /sendBeacon\s*\(/],
    ]

    for (const [name, pattern] of patterns) {
      const offenders = files
        .filter((file) => pattern.test(file.source))
        .map((file) => `${file.name} uses ${name}`)
      expect(offenders).toEqual([])
    }
  })

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
})
