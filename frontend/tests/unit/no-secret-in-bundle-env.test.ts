/**
 * 빌드 환경에서 번들로 들어가는 값은 **`VITE_API_BASE_URL` 하나뿐이다.**
 *
 * Vite는 `import.meta.env.VITE_*`와 `index.html`의 `%VITE_*%`를 빌드 시 문자열로 박아
 * 넣는다. 그래서 frontend가 secret을 "갖지 않는다"는 것은 코드에 키가 없다는 것만으로는
 * 부족하다 --- 누군가 `import.meta.env.VITE_LLM_API_KEY`를 읽는 한 줄을 넣고 빌드 셸에
 * 그 값을 두면, 저장소에는 키가 없는데 번들에는 있다(`spec/04_SECURITY_AND_DATA.md`:
 * "PWA bundle에 secret 금지", `13_ACCEPTANCE_CRITERIA.md`의 `secret frontend/Git 노출 없음`).
 * Git 쪽 검사(`backend/tests/test_git_hygiene.py`)는 index만 보므로 이 경로를 보지 못한다.
 *
 * 막는 통로는 셋이다: `src/`의 env 읽기, `index.html` 치환, vite 설정(`envPrefix`를
 * 넓히거나 `define`으로 임의 값을 박는 것).
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
const SRC = join(ROOT, 'src')

/** 번들에 들어가도 되는 유일한 빌드 환경값. 공개값(API origin)이다. */
const ALLOWED_ENV = ['VITE_API_BASE_URL']

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

describe('build-time env reaching the bundle', () => {
  const sources = walk(SRC).map((path) => ({
    name: path.slice(SRC.length + 1),
    text: readFileSync(path, 'utf8'),
  }))

  it('src reads only the allowed name, and only by name', () => {
    const read = new Set<string>()
    const wholeObject: string[] = []
    for (const { name, text } of sources) {
      for (const match of text.matchAll(/import\.meta\.env(\.([A-Za-z0-9_]+))?/g)) {
        if (match[2] === undefined) wholeObject.push(name)
        else read.add(match[2])
      }
    }

    // 객체째 넘기면(`const env = import.meta.env`) 이름 검사를 우회해 무엇이든 읽는다.
    expect(wholeObject).toEqual([])
    expect([...read].sort()).toEqual(ALLOWED_ENV)
  })

  it('index.html substitutes no env value', () => {
    const html = readFileSync(join(ROOT, 'index.html'), 'utf8')

    expect(html.match(/%[A-Z0-9_]+%/g)).toBeNull()
  })

  it('the vite config neither widens the env prefix nor defines values', () => {
    const config = readFileSync(join(ROOT, 'vite.config.ts'), 'utf8')

    // `define`은 option 키 모양으로만 찾는다. `defineConfig` 호출은 정상이다.
    for (const pattern of [/\benvPrefix\b/, /\bdefine\s*:/, /\bloadEnv\b/, /process\.env/]) {
      expect(config).not.toMatch(pattern)
    }
  })
})
