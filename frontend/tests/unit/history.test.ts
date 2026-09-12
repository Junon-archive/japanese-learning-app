/**
 * 학습 기록의 두 목록.
 *
 * **날짜는 `users.timezone` 기준이다**(`04_DB_SPEC.md` 공통 규칙: 사용자 local day 경계는
 * `users.timezone`으로 계산한다). 그래서 아래 `date formatting`은 **같은 UTC 순간이 시간대
 * 마다 다른 날짜로** 찍히는 것을 단정한다. 경계가 아닌 시각을 쓰면 `timeZone` 옵션을
 * 지워도 실행 환경 시간대와 우연히 같아 통과한다 --- fixture 두 개가 서로 반대 방향
 * (UTC보다 앞/뒤)을 덮으므로 실행 환경이 무엇이든 최소 하나가 빨개진다.
 *
 * 이 파일이 지키는 것 셋. 전부 "화면은 멀쩡해 보이는데 거짓말을 하는" 종류다.
 *
 * 1.  **잘림 문구는 `truncated`가 `true`일 때만 뜬다.** 행 수로 추측하는 구현을 잡기 위해
 *     **행이 정확히 상한(50)만큼인데 `truncated: false`인** fixture를 쓴다. 행이 적은
 *     fixture만 쓰면 그 구현이 통과한다.
 * 2.  **`null`을 0이나 빈 문자열로 뭉개지 않는다.** `comprehension_mastery: null`은 "아직
 *     evidence 없음"이지 0%가 아니고, `next_review_at: null`은 예정이 없다는 뜻이다.
 * 3.  MVP 밖 화면(`표현 보관함`/`설정`)과 통계·차트를 만들지 않는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { dateFormat, renderItemHistory, renderSessionHistory } from '../../src/ui/history'
import type { HistoryItem, HistorySession } from '../../src/types'
import type { FakeElement } from './fake-dom'
import { byClass, fakeDocument, flatText } from './fake-dom'

const TRUNCATION_NOTE = '오래된 기록은'

/**
 * 테스트용 formatter. 기본은 `UTC`다 --- 실행 환경 시간대에 기대지 않는다.
 *
 * 실제 화면은 `GET /api/auth/me`의 `timezone`으로 이것을 만든다.
 */
function utcDates(): (iso: string) => string {
  return dateFormat('UTC').format
}

const SESSION: HistorySession = {
  session_id: 812,
  started_at: '2026-09-12T09:02:11Z',
  ended_at: '2026-09-12T09:15:40Z',
  active_seconds: 703,
  target_minutes: 12,
  extended_minutes: 5,
  completed_sentence_count: 9,
}

const ITEM: HistoryItem = {
  learning_item_id: 772,
  lemma: '気が乗らない',
  item_type: 'expression',
  comprehension_mastery: 0.32,
  exposure_count: 3,
  next_review_at: '2026-09-14T09:00:00Z',
}

/** 응답 계약 상수인 고정 상한. **화면 코드에는 없어야 하는 숫자다.** */
const SERVER_ROW_CAP = 50

function sessions(count: number, truncated: boolean): FakeElement {
  return renderSessionHistory(
    {
      sessions: Array.from({ length: count }, (_, index) => ({
        ...SESSION,
        session_id: SESSION.session_id - index,
      })),
      truncated,
    },
    utcDates(),
  ) as unknown as FakeElement
}

function items(list: HistoryItem[], truncated = false): FakeElement {
  return renderItemHistory({ items: list, truncated }, utcDates()) as unknown as FakeElement
}

beforeEach(() => {
  vi.stubGlobal('document', fakeDocument())
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('date formatting', () => {
  /** Seoul(+9)에서는 **다음 날** 00:30, UTC에서는 같은 날 15:30이다. */
  const EVENING_UTC = '2026-09-12T15:30:00Z'
  /** Los Angeles(-7)에서는 **전날** 21:30, UTC에서는 같은 날 04:30이다. */
  const EARLY_UTC = '2026-09-12T04:30:00Z'

  it('renders one instant as different dates in different timezones', () => {
    expect(dateFormat('Asia/Seoul').format(EVENING_UTC)).toBe('2026-09-13')
    expect(dateFormat('UTC').format(EVENING_UTC)).toBe('2026-09-12')

    expect(dateFormat('America/Los_Angeles').format(EARLY_UTC)).toBe('2026-09-11')
    expect(dateFormat('UTC').format(EARLY_UTC)).toBe('2026-09-12')
  })

  it('puts the session row date in the learner timezone', () => {
    const seoul = renderSessionHistory(
      { sessions: [{ ...SESSION, started_at: EVENING_UTC, ended_at: EVENING_UTC }], truncated: false },
      dateFormat('Asia/Seoul').format,
    ) as unknown as FakeElement
    const utc = renderSessionHistory(
      { sessions: [{ ...SESSION, started_at: EVENING_UTC, ended_at: EVENING_UTC }], truncated: false },
      dateFormat('UTC').format,
    ) as unknown as FakeElement

    expect(flatText(seoul)).toContain('2026-09-13')
    expect(flatText(utc)).toContain('2026-09-12')
  })

  it('puts the next review date in the learner timezone too', () => {
    const seoul = renderItemHistory(
      { items: [{ ...ITEM, next_review_at: EVENING_UTC }], truncated: false },
      dateFormat('Asia/Seoul').format,
    ) as unknown as FakeElement

    expect(flatText(seoul)).toContain('복습 2026-09-13')
  })

  it('formats the same way whatever the host locale would prefer', () => {
    // locale을 고정하고 조각을 직접 조립하므로 자릿수와 순서가 흔들리지 않는다.
    expect(dateFormat('UTC').format('2026-01-02T00:00:00Z')).toBe('2026-01-02')
  })

  it('falls back to the device timezone and says so when the value is unusable', () => {
    // 서버가 이상한 값을 줘도 기록 화면이 죽지 않는다. 그리고 조용히 넘어가지 않는다.
    const broken = dateFormat('Not/AZone')

    expect(broken.usesRequestedZone).toBe(false)
    expect(broken.format(EVENING_UTC)).toMatch(/^\d{4}-\d{2}-\d{2}$/)
    expect(dateFormat('Asia/Seoul').usesRequestedZone).toBe(true)
  })
})

describe('truncation', () => {
  it('says nothing when the server says nothing was cut', () => {
    // **행이 정확히 상한만큼이다.** 행 수로 추측하는 구현이 여기서 빨개진다.
    const full = sessions(SERVER_ROW_CAP, false)

    expect(byClass(full, 'history-row')).toHaveLength(SERVER_ROW_CAP)
    expect(flatText(full)).not.toContain(TRUNCATION_NOTE)
  })

  it('says it was cut when the server says so, however few rows came back', () => {
    const cut = sessions(2, true)

    expect(flatText(cut)).toContain(TRUNCATION_NOTE)
  })

  it('applies the same rule to the item list', () => {
    expect(flatText(items([ITEM], false))).not.toContain(TRUNCATION_NOTE)
    expect(flatText(items([ITEM], true))).toContain(TRUNCATION_NOTE)
  })

  it('never prints the server row cap', () => {
    // 상한은 서버 계약이다. 화면은 boolean 하나만 본다.
    expect(flatText(sessions(SERVER_ROW_CAP, true))).not.toContain(String(SERVER_ROW_CAP))
  })
})

describe('renderSessionHistory', () => {
  it('shows the date, the minutes and the completed sentence count', () => {
    const text = flatText(sessions(1, false))

    expect(text).toMatch(/\d{4}-\d{2}-\d{2}/)
    expect(text).toContain('학습 11분')
    expect(text).toContain('완료 9문장')
  })

  it('marks a session that is still open instead of leaving it blank', () => {
    const open = renderSessionHistory(
      { sessions: [{ ...SESSION, ended_at: null }], truncated: false },
      utcDates(),
    ) as unknown as FakeElement

    expect(flatText(open)).toContain('진행 중')
  })

  it('says so when there is nothing yet', () => {
    const empty = renderSessionHistory(
      { sessions: [], truncated: false },
      utcDates(),
    ) as unknown as FakeElement

    expect(byClass(empty, 'history-row')).toEqual([])
    expect(flatText(empty)).toContain('아직')
  })
})

describe('renderItemHistory', () => {
  it('shows the lemma, the exposure count and the next review', () => {
    const text = flatText(items([ITEM]))

    expect(text).toContain(ITEM.lemma)
    expect(text).toContain('노출 3회')
    expect(text).toMatch(/복습 \d{4}-\d{2}-\d{2}/)
    expect(text).toContain('32%')
  })

  it('reads a null mastery as "not evaluated yet", never as 0', () => {
    const text = flatText(items([{ ...ITEM, comprehension_mastery: null }]))

    expect(text).toContain('아직 평가 없음')
    expect(text).not.toContain('0%')
  })

  it('keeps a real zero mastery distinct from no evidence', () => {
    // 0.0은 "평가했고 결과가 0"이다. `null`과 같은 문구로 뭉개면 둘을 구분할 수 없다.
    const text = flatText(items([{ ...ITEM, comprehension_mastery: 0 }]))

    expect(text).toContain('0%')
    expect(text).not.toContain('아직 평가 없음')
  })

  it('says there is no scheduled review instead of printing an empty cell', () => {
    const text = flatText(items([{ ...ITEM, next_review_at: null }]))

    expect(text).toContain('복습 예정 없음')
  })

  it('builds nothing that the MVP excluded', () => {
    const text = flatText(items([ITEM]))

    // `표현 보관함`·`설정`은 MVP 화면이 아니고, 여기서 학습으로 이어지는 버튼도 두지
    // 않는다(03_UI_UX_SPEC.md의 `History`).
    expect(text).not.toMatch(/표현 보관함|설정|더 보기|기간|정렬|검색/)
    expect(byClass(items([ITEM]), 'history-row').flatMap((row) => row.children)).not.toEqual(
      expect.arrayContaining([expect.objectContaining({ tagName: 'BUTTON' })]),
    )
  })
})
