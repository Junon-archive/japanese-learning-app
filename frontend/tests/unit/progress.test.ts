/**
 * 진행 표시와 세션 종료 도달 판정.
 *
 * fixture의 `target_minutes`는 **7**이다. 12가 아니다. E2E가
 * `default_session_minutes=7`을 주입해 검증하는 것과 같은 이유로, 분모를 `12 * 60`처럼
 * 리터럴로 적으면 이 파일이 빨개져야 한다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { StudySession } from '../../src/types'
import {
  progressLabel,
  progressReadout,
  renderProgress,
  sessionProgress,
} from '../../src/ui/progress'
import type { FakeElement } from './fake-dom'
import { fakeDocument } from './fake-dom'

function session(fields: Partial<StudySession>): StudySession {
  return {
    session_id: 1,
    started_at: '2026-03-01T09:00:00Z',
    last_activity_at: '2026-03-01T09:05:00Z',
    ended_at: null,
    active_seconds: 0,
    target_minutes: 7,
    extended_minutes: 0,
    ...fields,
  }
}

describe('sessionProgress', () => {
  it('takes the denominator from the payload, not from a policy constant', () => {
    const progress = sessionProgress(session({ active_seconds: 120 }))

    expect(progress.totalSeconds).toBe(7 * 60)
    expect(progress.activeSeconds).toBe(120)
    expect(progress.ratio).toBeCloseTo(120 / 420)
  })

  it('adds extended_minutes to the denominator', () => {
    const progress = sessionProgress(session({ active_seconds: 420, extended_minutes: 5 }))

    expect(progress.totalSeconds).toBe((7 + 5) * 60)
    expect(progress.reached).toBe(false)
  })

  it('clamps the ratio to 1 without clamping the seconds', () => {
    const progress = sessionProgress(session({ active_seconds: 10_000 }))

    expect(progress.ratio).toBe(1)
    expect(progress.activeSeconds).toBe(10_000)
  })
})

describe('세션 종료 도달 판정', () => {
  it('is false one second below the denominator', () => {
    expect(sessionProgress(session({ active_seconds: 7 * 60 - 1 })).reached).toBe(false)
  })

  it('is true exactly at the denominator', () => {
    expect(sessionProgress(session({ active_seconds: 7 * 60 })).reached).toBe(true)
  })

  it('is true above the denominator', () => {
    expect(sessionProgress(session({ active_seconds: 7 * 60 + 1 })).reached).toBe(true)
  })

  it('moves the boundary when the session was extended', () => {
    const extended = { extended_minutes: 5 }
    expect(sessionProgress(session({ active_seconds: 719, ...extended })).reached).toBe(false)
    expect(sessionProgress(session({ active_seconds: 720, ...extended })).reached).toBe(true)
  })
})

describe('진행 문구', () => {
  it('uses the minutes the server sent', () => {
    expect(progressLabel(session({}))).toBe('오늘 약 7분')
    expect(progressLabel(session({ extended_minutes: 5 }))).toBe('오늘 약 7분 (+5분 연장)')
    expect(progressReadout(session({ active_seconds: 150 }))).toBe('2분 / 7분')
  })

  it('never prints a policy default the payload did not contain', () => {
    const text = `${progressLabel(session({}))} ${progressReadout(session({}))}`
    expect(text).not.toContain('12')
  })
})

describe('renderProgress', () => {
  beforeEach(() => {
    vi.stubGlobal('document', fakeDocument())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('describes the bar with the payload denominator', () => {
    const wrap = renderProgress(session({ active_seconds: 210 })) as unknown as FakeElement

    const bar = wrap.children.find((child) => child.className === 'progress-bar')
    expect(bar?.getAttribute('aria-valuemax')).toBe('420')
    expect(bar?.getAttribute('aria-valuenow')).toBe('210')
    expect(bar?.children[0]?.style['width']).toBe('50%')
  })
})
