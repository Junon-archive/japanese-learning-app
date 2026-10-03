/**
 * **도달 전 종료 -> 언어 바꾸기, 결함 그대로의 회귀**(MVP-03 합격 기준 32,
 * `03_UI_UX_SPEC.md`의 `학습 중에 언어를 바꾸는 길`, ADR-025 결정 2의 `개정 2 (2026-10-03)`).
 *
 * 2026-10-03 운영에서 영어 세션을 잠깐만 하고 홈으로 나간 사용자가 일본어로 **바꿀 수 없었다.**
 * 조각마다 테스트가 있어도 잡히지 않은 결함이라(조각들은 각각 옳았다) 여기서는 그 길을 끝에서
 * 끝까지 한 번에 지난다.
 *
 * ``` text
 * 1  학습하러 가기 -> 언어 선택 화면 -> 영어         (열린 세션 없음)
 * 2  도달 **전** 상태의 영어 Study Screen
 * 3  `오늘 목표한 시간을 채웠어요.`와 `더 학습하기`가 없고 `오늘 학습 완료`가 있다
 * 4  `오늘 학습 완료` -> /finish -> 완료 화면
 * 5  상단바 앱 이름 -> 언어 선택 홈(#/)
 * 6  학습하러 가기 -> GET /me 200 -> GET /session(session: null) -> **언어 선택 화면**
 * 7  일본어 -> `language: 'ja'`로 POST /session -> 일본어 Study Screen
 * ```
 *
 * 6에서 Study Screen이 나오면 재발이다. 옛 결함은 셋이 겹쳐서 났다 --- (a) 도달 전에는 세션을
 * 끝낼 UI가 없었고, (b) 언어를 다시 묻는 조건이 "이어서 할 수 있는 세션이 없을 때"뿐이고,
 * (c) 학습 화면에 들어가는 것만으로 서버의 resume이 idle timeout을 되돌렸다. **탈출 시도가
 * 탈출 조건을 지웠다.** 그래서 이 테스트는 시계를 전혀 건드리지 않는다 --- 방금 시작한 세션에서
 * 성립해야 하는 길이다.
 *
 * `src/main.ts`를 실제로 부팅하고 `fetch`를 세워 진짜 `api.ts`를 지난다. 요청 기록(+ 보낸
 * `language`)이 곧 단언이다. 분 수는 테스트에 적지 않는다 --- 도달 전 상태는 payload의
 * `target_minutes`·`extended_minutes`에서 계산한 분모보다 `active_seconds`를 작게 두어 만든다.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { Language, Presentation, StudySession, User } from '../../src/types'
import { MESSAGES } from '../../src/ui/notice'
import { sessionProgress } from '../../src/ui/progress'
import { memoryStorage } from './demo-harness'
import type { FakeBrowser, FakeElement } from './fake-dom'
import { buttons, byClass, createFakeElement, fakeBrowser, fakeDocument, flatText } from './fake-dom'

const USER: User = { user_id: 1, login_id: 'owner', timezone: 'Asia/Seoul', starting_level: 'beginner' }

const EN_SESSION_ID = 7
const JA_SESSION_ID = 8

const FINISH_LABEL = '오늘 학습 완료'
const EXTEND_LABEL = '더 학습하기'
const REACHED_TEXT = '오늘 목표한 시간을 채웠어요.'
const ENTRY_LABEL = '학습하러 가기'

const ME = 'GET /api/auth/me'
const OPEN_SESSION = 'GET /api/study/session'
const START = 'POST /api/study/session'
const EN_FINISH = `POST /api/study/session/${EN_SESSION_ID}/finish`
const EN_NEXT = `POST /api/study/session/${EN_SESSION_ID}/next`
const JA_NEXT = `POST /api/study/session/${JA_SESSION_ID}/next`

function openSession(id: number, language: Language): StudySession {
  return {
    session_id: id,
    language,
    started_at: '2026-10-03T09:00:00Z',
    last_activity_at: '2026-10-03T09:01:12Z',
    ended_at: null,
    active_seconds: 0,
    target_minutes: 12,
    extended_minutes: 0,
  }
}

/** 분자를 분모보다 작게. 분모는 payload의 두 값에서만 나온다(`05_API_SPEC.md`의 도달 판정). */
function beforeReached(session: StudySession): StudySession {
  const total = (session.target_minutes + session.extended_minutes) * 60
  return { ...session, active_seconds: Math.floor(total / 10) }
}

function presentationOf(text: string): Presentation {
  return {
    presentation_id: 11,
    sentence_id: 3,
    text,
    render_segments: [
      { text, sentence_item_id: 21, ruby: [] },
    ],
    presentation_role: 'new',
    review_reason: null,
    context_stage: 'anchor',
    translation_revealed: false,
    tappable_items: [{ sentence_item_id: 21, learning_item_id: 5 }],
    probe: null,
  } as unknown as Presentation
}

const EN_PRESENTATION = presentationOf('So, how was your date last night?')
const JA_PRESENTATION = presentationOf('気が乗らない。')

const fetchMock = vi.fn<typeof fetch>()

let root: FakeElement
let browser: FakeBrowser
let table: Record<string, () => Promise<Response>>

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status })
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
    .map(([, init]) => (JSON.parse(String(init?.body ?? 'null')) as { language?: unknown }).language)
}

async function settle(): Promise<void> {
  await vi.dynamicImportSettled()
  for (let i = 0; i < 4; i += 1) {
    await new Promise((resolve) => {
      setTimeout(resolve, 0)
    })
  }
  await vi.dynamicImportSettled()
}

async function boot(): Promise<void> {
  browser = fakeBrowser('')
  vi.stubGlobal('location', browser.location)
  vi.stubGlobal('history', browser.history)
  vi.stubGlobal('window', browser.window)
  vi.resetModules()
  await import('../../src/main')
  await settle()
}

function screenClass(): string {
  return root.children[0]?.className ?? ''
}

function press(text: string): void {
  const found = buttons(root).filter((button) => button.textContent === text)
  expect(found, `button "${text}" on screen`).toHaveLength(1)
  found[0]!.click()
}

function labelsOnScreen(): string[] {
  return buttons(root).map((button) => button.textContent)
}

beforeEach(() => {
  root = createFakeElement('div')
  table = {}
  fetchMock.mockReset()
  fetchMock.mockImplementation((url, init) => table[key(url, init)]?.() ?? new Promise<Response>(() => {}))
  vi.stubGlobal('document', { ...fakeDocument(), querySelector: () => root })
  vi.stubGlobal('localStorage', memoryStorage())
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.resetModules()
})

describe('도달 전에 끝내고 언어를 바꾼다 (결함 재현 경로)', () => {
  it('goes 영어 Study(도달 전) -> 오늘 학습 완료 -> 홈 -> 학습하러 가기 -> 언어 선택 -> 일본어', async () => {
    const english = beforeReached(openSession(EN_SESSION_ID, 'en'))
    // 전제: 이 세션은 도달 **전**이다(운영에서 걸린 상태). 아니면 아래 단언이 도달 후 화면을 본다.
    expect(sessionProgress(english).reached).toBe(false)
    const japanese = openSession(JA_SESSION_ID, 'ja')
    let openSessionRow: StudySession | null = null

    table = {
      [ME]: async () => json(200, USER),
      // 서버 상태를 흉내 낸다 --- 열린 세션이 있으면 그것, `/finish` 뒤에는 없다.
      [OPEN_SESSION]: async () => json(200, { session: openSessionRow, resumable: openSessionRow !== null }),
      [START]: async (): Promise<Response> => {
        const language = startedLanguages().at(-1)
        const started = language === 'en' ? english : japanese
        openSessionRow = started
        return json(200, { session: started, resumed: false, timed_out_session_id: null })
      },
      [EN_NEXT]: async () => json(200, { presentation: EN_PRESENTATION }),
      [JA_NEXT]: async () => json(200, { presentation: JA_PRESENTATION }),
      [EN_FINISH]: async (): Promise<Response> => {
        openSessionRow = null
        return json(200, { ...english, ended_at: '2026-10-03T09:01:12Z' })
      },
    }

    await boot()
    expect(screenClass()).toContain('home')

    // 1. 학습하러 가기 -> 열린 세션이 없으므로 언어 선택 화면. 영어를 고른다.
    press(ENTRY_LABEL)
    await settle()
    expect(screenClass()).toContain('language-select')
    press(MESSAGES.languageEn)
    await settle()

    // 2~3. 영어 Study Screen이고, 도달 전이라 안내 문구와 `더 학습하기`가 없다.
    expect(screenClass()).toContain('study')
    expect(flatText(root.children[0]!)).toContain(EN_PRESENTATION.text)
    expect(flatText(root.children[0]!)).not.toContain(REACHED_TEXT)
    expect(labelsOnScreen()).not.toContain(EXTEND_LABEL)
    expect(buttons(byClass(root, 'finish-slot')[0]!).map((button) => button.textContent)).toEqual([
      FINISH_LABEL,
    ])

    // 4. 끝낸다. 도달하지 않았어도 `/finish`가 불리고 완료 화면이 뜬다.
    press(FINISH_LABEL)
    await settle()
    expect(calls()).toContain(EN_FINISH)
    expect(byClass(root, 'session-finished')).toHaveLength(1)

    // 5. 상단바 앱 이름 -> 언어 선택 홈. 여기서 요청이 더 나가지 않는다.
    const callsBeforeHome = calls().length
    byClass(root, 'topbar-brand')[0]!.click()
    await settle()
    expect(screenClass()).toContain('home')
    // hash 없음과 `#/`는 둘 다 언어 선택 홈이다(`03_UI_UX_SPEC.md`의 route 표). 로그인 영역에
    // 들어갈 때 hash를 지웠으므로 여기서는 그대로 빈 문자열이다.
    expect(['', '#/']).toContain(location.hash)
    expect(calls().slice(callsBeforeHome)).toEqual([])

    // 6. **재발 지점.** 다시 들어가면 이어서 할 세션이 없으므로 언어를 **다시 묻는다.**
    press(ENTRY_LABEL)
    await settle()
    expect(calls().slice(callsBeforeHome)).toEqual([ME, OPEN_SESSION])
    expect(screenClass()).toContain('language-select')
    expect(byClass(root, 'home-card').map((card) => card.textContent)).toEqual([
      MESSAGES.languageJa,
      MESSAGES.languageEn,
    ])

    // 7. 일본어를 고르면 **고른 언어로** 새 세션이 시작된다(옛 세션의 언어가 아니다).
    press(MESSAGES.languageJa)
    await settle()
    expect(screenClass()).toContain('study')
    expect(flatText(root.children[0]!)).toContain(JA_PRESENTATION.text)
    expect(startedLanguages()).toEqual(['en', 'ja'])

    // 전체 궤적. 시계 조작이 없고, `/finish`는 사용자가 누른 한 번뿐이다.
    expect(calls()).toEqual([
      ME,
      OPEN_SESSION,
      START,
      EN_NEXT,
      EN_FINISH,
      ME,
      OPEN_SESSION,
      START,
      JA_NEXT,
    ])
  })
})
