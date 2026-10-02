/**
 * 일본어 demo 진도 저장(`nc.demo.ja.v1`). 규칙 자체는 `../progress.ts`(언어 공유)가 맡고, 이 모듈은
 * 지금 번들의 일본어 fixture와 그 저장 key만 엮는다(ADR-025 결정 3).
 *
 * 진도 저장은 `spec/04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`를 따른다. 서버로 보내지
 * 않고 로그인 여부·계정 값을 넣지 않는다. 형식·값 범위·소속이 맞지 않는 저장값은 조용히 없는 것으로 본다.
 */
import { localSlot } from '../../local-store'
import type { DemoFixture, DemoProgress } from '../progress'
import { isProgressOf } from '../progress'
import { DEMO_FIXTURE_ID, DEMO_SENTENCES } from './fixture'

/** 지금 번들에 들어 있는 일본어 fixture. */
export const DEMO_FIXTURE: DemoFixture = { id: DEMO_FIXTURE_ID, sentences: DEMO_SENTENCES }

/** 지금 fixture의 진도인가(`localSlot`의 isValid). */
export function isDemoProgress(value: unknown): value is DemoProgress {
  return isProgressOf(DEMO_FIXTURE, value)
}

const slot = localSlot('nc.demo.ja.v1', isDemoProgress)

/** 저장된 진도. 없거나, 읽을 수 없거나, 다른 fixture의 값이거나, 형식이 맞지 않으면 undefined. */
export function readDemoProgress(): DemoProgress | undefined {
  return slot.read()
}

/** 저장을 시도한다. 저장할 수 없어도 이 페이지 안에서는 이어진다. 던지지 않는다. */
export function writeDemoProgress(progress: DemoProgress): void {
  slot.write(progress)
}

/** 진도 초기화. demo 진도만 지운다. */
export function resetDemoProgress(): void {
  slot.remove()
}
