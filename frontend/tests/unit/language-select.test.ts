/**
 * 언어 선택 화면과 세션 언어 409 (`03_UI_UX_SPEC.md`의 `언어 선택 화면`, MVP-03 합격 기준 9·11,
 * `mvp-03-english/12_TEST_PLAN.md`의 `언어 선택 화면`).
 *
 * 대상은 `src/ui/language-select.ts` 전체와 `src/ui/study.ts`의 `showLanguageMismatch`다. 실제
 * `private.ts`를 지나므로 "언제 묻는가"(열린 세션 유무)도 함께 본다.
 *
 * 갈리는 지점. 넷 다 **화면에서는 그럴듯하게 보인다.**
 *
 * 1.  **열린 세션이 있으면 묻지 않는다.** 물으면 사용자가 매번 한 번 더 누르고, 고른 언어가 열린
 *     세션과 다르면 멀쩡한 세션이 409 분기로 끌려간다.
 * 2.  **"마지막에 고른 언어"를 저장하지 않는다**(불변식 18). 저장하면 localStorage key가 늘고
 *     (`04_SECURITY_AND_DATA.md`의 `localStorage 사용 범위`), 다음에 묻지 않게 되어 1번과 겹치는
 *     상태가 두 곳(서버의 열린 세션, 브라우저의 저장값)에 생긴다.
 * 3.  **409는 오류가 아니라 두 선택지다**(ADR-023 결정 7). 오류로 다루면 "다시 시도하기"가 같은
 *     409를 영원히 받는다.
 * 4.  **`이어서 하기`는 `/finish`를 부르지 않는다.** 부르면 다른 탭·기기에서 진행 중이던 세션이
 *     조용히 닫힌다 --- 사용자는 "이어서 하기"를 눌렀는데 그 세션이 끝난다. 그래서 두 버튼의
 *     **호출 궤적**을 고정한다.
 *
 * `fetch`를 세워 실제 `api.ts`를 지난다. 요청 기록(+ 보낸 body)이 곧 단정이다. 문구는
 * `ui/notice.ts`의 `MESSAGES`에서 읽고 테스트에 복사하지 않는다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Language, Presentation, StudySession, User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import type { MemoryStorage } from './demo-harness'
import { memoryStorage } from './demo-harness'
import type { FakeDocument, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeDocument, flatText } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

const SESSION_ID = 7

function session(language: Language): StudySession {
  return {
    session_id: SESSION_ID,
    language,
    started_at: '2026-10-01T09:00:00Z',
    last_activity_at: '2026-10-01T09:00:00Z',
    ended_at: null,
    active_seconds: 0,
    target_minutes: 12,
    extended_minutes: 0,
  }
}

const PRESENTATION = {
  presentation_id: 11,
  sentence_id: 3,
  text: 'So, how was your date last night?',
  render_segments: [
    { text: 'So', sentence_item_id: 21, ruby: [] },
    { text: ', how was your date last night?', sentence_item_id: null, ruby: [] },
  ],
  presentation_role: 'new',
  review_reason: null,
  context_stage: 'anchor',
  translation_revealed: false,
  tappable_items: [{ sentence_item_id: 21, learning_item_id: 5 }],
  probe: null,
} as unknown as Presentation

const ME = 'GET /api/auth/me'
const OPEN_SESSION = 'GET /api/study/session'
const START = 'POST /api/study/session'
const FINISH = `POST /api/study/session/${SESSION_ID}/finish`
const NEXT = `POST /api/study/session/${SESSION_ID}/next`

const fetchMock = vi.fn<typeof fetch>()

/** 테스트마다 새로 불러온다. `api.ts`가 같은 요청을 합치는 모듈 상태를 들고 있다. */
let enterPrivate: typeof import('../../src/private').enterPrivate
let root: FakeElement
let doc: FakeDocument
let storage: MemoryStorage
let table: Record<string, () => Promise<Response>>

function json(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status })
}

function key(url: unknown, init?: RequestInit): string {
  return `${init?.method ?? 'GET'} ${String(url).replace(/^https?:\/\/[^/]+/, '')}`
}

function calls(): string[] {
  return fetchMock.mock.calls.map(([url, init]) => key(url, init))
}

/** `POST /api/study/session`에 실어 보낸 `language` 값들. 순서가 곧 궤적이다. */
function startedLanguages(): unknown[] {
  return fetchMock.mock.calls
    .filter(([url, init]) => key(url, init) === START)
    .map(([, init]) => JSON.parse(String(init?.body ?? 'null')) as { language?: unknown })
    .map((body) => body.language)
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 0)
    })
  }
}

function screenClass(): string {
  return root.children[0]?.className ?? ''
}

function press(text: string): void {
  const found = buttons(root).filter((button) => button.textContent === text)
  expect(found, `button "${text}" on screen`).toHaveLength(1)
  found[0]!.click()
}

function topBarRight(): string[] {
  const bar = byClass(root, 'topbar')[0]!
  return buttons(byClass(bar, 'topbar-actions')[0]!).map((button) => button.textContent)
}

function notices(): FakeElement[] {
  return byClass(root, 'notice')
}

/** 409 `session_language_mismatch`의 body(`backend/app/main.py`의 handler가 내는 모양 그대로). */
function mismatch(openLanguage: Language): Response {
  return json(409, {
    error: 'session_language_mismatch',
    open_session: { id: SESSION_ID, language: openLanguage },
  })
}

/** 로그인 영역에 들어간다. `GET /api/auth/me`는 200이다. */
async function enter(): Promise<AbortController> {
  table = { [ME]: async () => json(200, USER), ...table }
  const area = new AbortController()
  enterPrivate({
    root: root as unknown as HTMLElement,
    signal: area.signal,
    goHome: () => {},
    openLogin: () => {},
  })
  await settle()
  return area
}

beforeEach(async () => {
  vi.resetModules()
  ;({ enterPrivate } = await import('../../src/private'))
  root = createFakeElement('div')
  doc = fakeDocument()
  storage = memoryStorage()
  vi.stubGlobal('document', doc)
  vi.stubGlobal('localStorage', storage)
  table = {}
  fetchMock.mockReset()
  fetchMock.mockImplementation((url, init) => table[key(url, init)]?.() ?? new Promise<Response>(() => {}))
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// --------------------------------------------------------------------------
// 언제 묻는가 (합격 기준 11)
// --------------------------------------------------------------------------

describe('열린 세션이 있을 때', () => {
  it('does not ask and continues in that session language', async () => {
    table = {
      [OPEN_SESSION]: async () => json(200, { session: session('en') }),
      [START]: async () => json(200, { session: session('en'), resumed: true, timed_out_session_id: null }),
      [NEXT]: async () => json(200, { presentation: PRESENTATION }),
    }
    await enter()

    expect(byClass(root, 'language-select')).toEqual([])
    expect(screenClass()).toContain('study')
    // 열린 세션의 language 그대로 시작한다. 묻지도, 기본값으로 덮지도 않는다.
    expect(startedLanguages()).toEqual(['en'])
    expect(calls()).toEqual([ME, OPEN_SESSION, START, NEXT])
  })

  it('has no language switch button on the study screen top bar', async () => {
    table = {
      [OPEN_SESSION]: async () => json(200, { session: session('en') }),
      [START]: async () => json(200, { session: session('en'), resumed: false, timed_out_session_id: null }),
      [NEXT]: async () => json(200, { presentation: PRESENTATION }),
    }
    await enter()

    // 언어를 바꾸는 입구는 409 분기 하나다(ADR-025 결정 2). 상단바에 전환 버튼을 두지 않는다.
    expect(topBarRight()).not.toContain(MESSAGES.languageJa)
    expect(topBarRight()).not.toContain(MESSAGES.languageEn)
    // 영어 Study Screen에는 후리가나 토글도 없다(합격 기준 24).
    expect(topBarRight()).toEqual(['학습 기록', '로그아웃'])
  })
})

describe('열린 세션이 없을 때', () => {
  beforeEach(() => {
    table = {
      [OPEN_SESSION]: async () => json(200, { session: null }),
      [START]: async () => json(200, { session: session('en'), resumed: false, timed_out_session_id: null }),
      [NEXT]: async () => json(200, { presentation: PRESENTATION }),
    }
  })

  it('asks which language, and asks nothing of the server until the user picks', async () => {
    await enter()

    expect(screenClass()).toContain('language-select')
    expect(root.children[0]!.querySelector('h1')!.textContent).toBe(MESSAGES.languageSelectTitle)
    expect(byClass(root, 'home-card').map((card) => card.textContent)).toEqual([
      MESSAGES.languageJa,
      MESSAGES.languageEn,
    ])
    // 상단바 오른쪽은 `로그아웃`뿐이다 --- 로그인 영역 안이고 문장이 없다.
    expect(topBarRight()).toEqual(['로그아웃'])
    // 고르기 전에는 세션을 만들지 않는다.
    expect(calls()).toEqual([ME, OPEN_SESSION])
  })

  it('starts a session in the chosen language', async () => {
    await enter()
    press(MESSAGES.languageEn)
    await settle()

    expect(screenClass()).toContain('study')
    expect(startedLanguages()).toEqual(['en'])
    expect(calls()).toEqual([ME, OPEN_SESSION, START, NEXT])
  })

  it('writes nothing to localStorage when a language is chosen', async () => {
    // 일본어를 고른다 --- 후리가나 토글이 있는 쪽이라 저장소를 건드릴 경로가 더 많다.
    table[START] = async () =>
      json(200, { session: session('ja'), resumed: false, timed_out_session_id: null })
    await enter()

    // 양성 대조군: 이 스텁은 쓰기를 실제로 기록한다.
    storage.setItem('nc.probe', '1')
    expect(storage.writtenKeys).toEqual(['nc.probe'])
    storage.writtenKeys.length = 0

    press(MESSAGES.languageJa)
    await settle()

    expect(screenClass()).toContain('study')
    // "마지막에 고른 언어"를 저장하지 않는다(불변식 18). 선택은 서버의 세션 language로만 남는다.
    expect(storage.writtenKeys).toEqual([])
  })
})

// --------------------------------------------------------------------------
// 409 SessionLanguageMismatch (합격 기준 9)
// --------------------------------------------------------------------------

describe('고른 언어와 열린 세션이 다를 때(409)', () => {
  /** 언어 선택 화면에서 `en`을 골랐고 서버에는 `ja` 세션이 열려 있다. */
  async function chooseEnglishAgainstAJapaneseSession(): Promise<void> {
    table = {
      [OPEN_SESSION]: async () => json(200, { session: null }),
      [START]: async () => mismatch('ja'),
      [NEXT]: async () => json(200, { presentation: PRESENTATION }),
      ...table,
    }
    await enter()
    press(MESSAGES.languageEn)
    await settle()
  }

  it('shows two choices instead of an error, and finishes nothing yet', async () => {
    await chooseEnglishAgainstAJapaneseSession()

    expect(notices()).toHaveLength(1)
    const notice = notices()[0]!
    // 오류가 아니다. `다시 시도하기`를 주면 같은 409를 영원히 받는다.
    expect(notice.className).toContain('notice-info')
    expect(buttons(notice).map((button) => button.textContent)).toEqual([
      MESSAGES.continueOtherSession,
      MESSAGES.finishAndSwitch,
    ])
    // 두 언어가 문구에 나온다(어느 학습이 진행 중이고 무엇으로 바꾸는지).
    expect(flatText(notice)).toContain(MESSAGES.languageJa)
    expect(flatText(notice)).toContain(MESSAGES.languageEn)
    // 재전송하지 않고, 사용자가 고르기 전에는 아무 세션도 닫지 않는다.
    expect(calls()).toEqual([ME, OPEN_SESSION, START])
    expect(startedLanguages()).toEqual(['en'])
  })

  it('이어서 하기 restarts in the open session language and never calls /finish', async () => {
    await chooseEnglishAgainstAJapaneseSession()
    table[START] = async () =>
      json(200, { session: session('ja'), resumed: true, timed_out_session_id: null })

    press(MESSAGES.continueOtherSession)
    await settle()

    expect(screenClass()).toContain('study')
    // 궤적: 409를 받은 뒤 **열린 세션의 language로** 다시 시작한다. `/finish`가 없다.
    expect(calls()).toEqual([ME, OPEN_SESSION, START, START, NEXT])
    expect(startedLanguages()).toEqual(['en', 'ja'])
    expect(calls()).not.toContain(FINISH)
    expect(notices()).toEqual([])
  })

  it('마치고 바꾸기 finishes the open session first, then starts the chosen language', async () => {
    await chooseEnglishAgainstAJapaneseSession()
    table[FINISH] = async () => json(200, { ...session('ja'), ended_at: '2026-10-01T09:10:00Z' })
    table[START] = async () =>
      json(200, { session: session('en'), resumed: false, timed_out_session_id: null })

    press(MESSAGES.finishAndSwitch)
    await settle()

    expect(screenClass()).toContain('study')
    // 궤적: `/finish` -> `POST /session`(고른 language) -> `/next`. 순서가 뒤집히면 다시 409다.
    expect(calls()).toEqual([ME, OPEN_SESSION, START, FINISH, START, NEXT])
    expect(startedLanguages()).toEqual(['en', 'en'])
    expect(notices()).toEqual([])
  })

  it('keeps the two buttons when 이어서 하기 is pressed twice (no double finish)', async () => {
    await chooseEnglishAgainstAJapaneseSession()
    // 다시 눌러도 여전히 409라면(그 사이 또 바뀌었다) 안내가 다시 뜨고 `/finish`는 여전히 없다.
    press(MESSAGES.continueOtherSession)
    await settle()

    expect(calls().filter((call) => call === FINISH)).toEqual([])
    expect(notices()).toHaveLength(1)
    expect(buttons(notices()[0]!).map((button) => button.textContent)).toEqual([
      MESSAGES.continueOtherSession,
      MESSAGES.finishAndSwitch,
    ])
  })
})
