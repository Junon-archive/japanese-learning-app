/**
 * 영어 demo fixture(`../fixture.ts`의 `DemoSentence`와 같은 모양). 데이터는
 * `scripts/build_demo_fixture.py --language en`이 `fixture-data.ts`에 생성한다(ADR-025 결정 3).
 * ruby는 전부 빈 배열이다(ADR-023 결정 6, 영어는 후리가나 계산을 건너뛴다).
 */

export type { DemoSentence } from '../fixture'
export { DEMO_FIXTURE_ID, DEMO_SENTENCES } from './fixture-data'
