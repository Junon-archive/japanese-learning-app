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
import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, it } from 'vitest'

import { buildOutput } from './build-output'

/**
 * **현재 소스로 만든 산출물만 검증한다.** 신선도 확인과 재빌드는 `build-output.ts`에 있다(격리 검사 (e)와
 * 공용).
 */
function distFiles(): string[] {
  return buildOutput().files
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
    const { dir, files: built } = buildOutput()
    const files = built.map((path) => path.slice(dir.length + 1))
    expect(files).toContain('manifest.webmanifest')
    expect(files).toContain(join('icons', 'icon-192.png'))
    expect(files).toContain(join('icons', 'icon-512.png'))
    expect(files).toContain(join('icons', 'icon-512-maskable.png'))
  })
})
