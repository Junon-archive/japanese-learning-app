/**
 * `src/`에 **자동 폴링과 unload 시점 전송이 없다.**
 *
 * 둘 다 화면에서는 정상으로 보이기 때문에 코드에서 막는다.
 *
 * -   `setInterval` / `setTimeout` 재귀로 상호작용 endpoint를 주기 호출하면 서버의
 *     `touch()`가 자리를 비운 시간을 학습 시간으로 누적한다. 진행바는 오히려 매끄럽게
 *     움직이고 틀어지는 것은 `active_seconds`의 의미뿐이다(05_API_SPEC.md).
 * -   `beforeunload` / `pagehide` / `visibilitychange` / `sendBeacon`으로 mutation을
 *     보내면 **사용자가 보지 않은 문장이 완료로 확정되어** 없던 노출이 생긴다
 *     (불변식 #2: 부재를 완료로 추론하지 않는다).
 *
 * 주석에서 이 단어를 언급하는 것은 막지 않는다 --- 호출/등록 형태만 찾는다.
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

const FORBIDDEN: [string, RegExp][] = [
  ['setInterval', /setInterval\s*\(/],
  ['sendBeacon', /sendBeacon\s*\(/],
  ['unload listener', /addEventListener\s*\(\s*['"](beforeunload|pagehide|visibilitychange)/],
]

describe('src', () => {
  for (const [name, pattern] of FORBIDDEN) {
    it(`never uses ${name}`, () => {
      const offenders = walk(SRC)
        .filter((path) => pattern.test(readFileSync(path, 'utf8')))
        .map((path) => path.slice(SRC.length + 1))

      expect(offenders).toEqual([])
    })
  }
})
