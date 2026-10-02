/**
 * `#/ja/demo` route의 화면(`routes.ts`). 화면 로직은 `../demo.ts`(언어 공유)가 맡고, 이 모듈은
 * 일본어 fixture와 `nc.demo.ja.v1` 저장소, 후리가나 토글, `글자 배우기` 완료 버튼을 엮기만 한다
 * (ADR-025 결정 2·3).
 */
import type { PublicScreenContext } from '../../routes'
import { mountDemo } from '../demo'
import { DEMO_FIXTURE, readDemoProgress, resetDemoProgress, writeDemoProgress } from './progress'

export function mount(ctx: PublicScreenContext): void {
  mountDemo(ctx, {
    fixture: DEMO_FIXTURE,
    store: { read: readDemoProgress, write: writeDemoProgress, reset: resetDemoProgress },
    withFuriganaToggle: true,
    kana: { hash: '#/ja/kana' },
  })
}
