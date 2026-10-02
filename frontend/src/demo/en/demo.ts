/**
 * `#/en/demo` route의 화면(`routes.ts`). 화면 로직은 `../demo.ts`(언어 공유)가 맡고, 이 모듈은
 * 영어 fixture와 `nc.demo.en.v1` 저장소를 엮기만 한다(ADR-025 결정 2·3).
 *
 * -   **후리가나 토글이 없다.** 영어 fixture의 `render_segments[].ruby`는 전부 `[]`다(ADR-023 결정 6).
 * -   **완료 화면에 `글자 배우기`가 없다.** 가나 학습에 대응하는 영어 보조 화면이 없다(ADR-025 결정 2).
 * -   재생 버튼은 이 레인의 범위가 아니다(`speech` 레인이 잇는다).
 */
import type { PublicScreenContext } from '../../routes'
import { mountDemo } from '../demo'
import { DEMO_FIXTURE, readDemoProgress, resetDemoProgress, writeDemoProgress } from './progress'

export function mount(ctx: PublicScreenContext): void {
  mountDemo(ctx, {
    fixture: DEMO_FIXTURE,
    store: { read: readDemoProgress, write: writeDemoProgress, reset: resetDemoProgress },
    withFuriganaToggle: false,
  })
}
