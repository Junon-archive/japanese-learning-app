/**
 * 빌드 산출물에 service worker가 없다.
 *
 * MVP는 offline을 지원하지 않는다(`spec/02_ARCHITECTURE.md`). SW를 붙이는 순간
 * 열리는 것들이 전부 불변식을 깬다.
 *
 * -   POST 오프라인 큐 / Background Sync: 사용자가 포기한 노출이 뒤늦게 확정된다.
 *     큐가 재구성하면서 새 UUID를 붙이면 같은 자가보고가 evidence로 두 번 적용된다.
 * -   `/api` 응답 캐싱: 진행 상태와 세션 종료 판정이 과거 값으로 굳고, 캐시된
 *     `/next`가 이미 완료된 presentation을 다시 그린다.
 * -   오프라인 폴백 셸: 학습 화면이 그려지는데 탭과 자가보고가 전부 사라진다.
 *     "DB 저장 실패를 성공처럼 표시하지 않는다"(10_ERROR_HANDLING.md) 위반이다.
 *
 * 그래서 이 테스트는 "지금 없다"가 아니라 **"앞으로도 넣지 마라"** 를 지키는 장치다.
 * 오프라인이 필요해지면 이 테스트를 지우기 전에 위 세 가지를 어떻게 막을지 먼저
 * 정한다.
 */
import { execFileSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
const DIST = join(ROOT, 'dist')

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

/** 산출물에 영향을 주는 입력 전부. 하나라도 빠지면 그만큼 낡은 것을 검증할 수 있다. */
const SOURCES = ['src', 'public', 'index.html', 'vite.config.ts', 'tsconfig.json', 'package.json']

function mtimes(paths: string[]): number[] {
  return paths.map((path) => statSync(path).mtimeMs)
}

function newestSourceMtime(): number {
  const files = SOURCES.map((entry) => join(ROOT, entry))
    .filter((path) => existsSync(path))
    .flatMap((path) => (statSync(path).isDirectory() ? walk(path) : [path]))
  return Math.max(...mtimes(files))
}

let rebuilt = false

/**
 * **현재 소스로 만든 산출물만 검증한다.**
 *
 * 예전에는 `dist/`가 있으면 그대로 읽었다. 그러면 옛 번들을 검사하고도 초록이 된다 ---
 * SW를 등록하는 코드를 방금 넣어도 산출물이 낡아 있으면 이 테스트가 통과한다. "테스트는
 * 초록인데 아무것도 검증하지 않는" 실패 방식이고, 이 파일이 막으려는 회귀가 바로 그런
 * 종류(빌드에만 드러나는 것)라서 특히 나쁘다.
 *
 * 그래서 **가장 오래된 산출물이 가장 최근 소스보다 낡았으면 다시 빌드한다.** 실패로
 * 끝내지 않는 이유는 `dist/`가 git에 없기 때문이다 --- 새로 받은 저장소에서 `vitest`만
 * 돌리면 검증할 산출물 자체가 없고, 사람에게 빌드 순서를 기억시키는 것은 이 테스트가
 * 처음부터 피하려던 것이다.
 *
 * 비용은 **낡았을 때만** 든다. 산출물이 최신이면 `stat`만 하고 지나가므로 스위트 시간이
 * 그대로다.
 */
function distFiles(): string[] {
  const stale = !existsSync(DIST) || Math.min(...mtimes(walk(DIST))) < newestSourceMtime()
  if (stale && !rebuilt) {
    rebuilt = true
    execFileSync('npm', ['run', 'build'], { cwd: ROOT, stdio: 'inherit' })
  }
  return walk(DIST)
}

describe('build output', () => {
  it('registers no service worker and ships no sw file', () => {
    const files = distFiles()
    expect(files.length).toBeGreaterThan(0)

    const named = files.filter((path) => /(^|\/)(sw|service-worker|workbox)[-.]/.test(path))
    expect(named).toEqual([])

    const registering = files.filter((path) =>
      /serviceWorker\s*\.\s*register|navigator\.serviceWorker/.test(readFileSync(path, 'utf8')),
    )
    expect(registering).toEqual([])
  })

  it('ships the manifest and both icon sizes', () => {
    const files = distFiles().map((path) => path.slice(DIST.length + 1))
    expect(files).toContain('manifest.webmanifest')
    expect(files).toContain(join('icons', 'icon-192.png'))
    expect(files).toContain(join('icons', 'icon-512.png'))
    expect(files).toContain(join('icons', 'icon-512-maskable.png'))
  })
})
