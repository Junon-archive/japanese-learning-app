/**
 * origin은 `src/env.ts` **한 곳**에만 있다.
 *
 * 실제 배포 도메인은 아직 정해지지 않았다. origin이 여러 파일에 흩어지면 도메인이
 * 정해질 때 하나를 빠뜨리게 되고, 그 요청만 조용히 다른 곳으로 나간다. 그 실패는
 * 화면상 "왜인지 로그인이 안 된다"로만 보인다.
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const SRC = fileURLToPath(new URL('../../src', import.meta.url))

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

describe('origin literals', () => {
  it('appear in src/env.ts and nowhere else', () => {
    const offenders = walk(SRC).filter((path) => /https?:\/\//.test(readFileSync(path, 'utf8')))
    expect(offenders.map((path) => path.slice(SRC.length + 1))).toEqual(['env.ts'])
  })

  it('are the configured default in env.ts, not a second copy', () => {
    const source = readFileSync(join(SRC, 'env.ts'), 'utf8')
    expect(source).toContain('import.meta.env.VITE_API_BASE_URL')
    expect(source.match(/https?:\/\//g)).toHaveLength(1)
  })
})
