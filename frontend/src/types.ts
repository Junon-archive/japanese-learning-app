/**
 * backend 응답/요청 스키마에 1:1 대응하는 타입 선언. **런타임 코드가 없다.**
 *
 * 출처는 명세가 아니라 구현이다: `backend/app/schemas/study.py`,
 * `backend/app/schemas/auth.py`, `backend/app/models/enums.py`.
 *
 * 두 가지가 타입에 박혀 있다.
 *
 * 1.  `Presentation`에 `korean_translation`이 **없다.** 번역은
 *     `POST .../translation/reveal`의 응답에만 있다. 필드를 추가하지 마라 --- 필드가
 *     없으면 번역을 미리 DOM에 넣고 숨기는 구현이 타입 단계에서 불가능해진다.
 * 2.  id는 전부 `number`다(ADR-005). 문자열로 감싸지 않는다. 예외는 client가 만드는
 *     `client_event_id`(UUID 문자열) 하나뿐이고, 그것은 `api.ts`가 붙인다.
 */

// --------------------------------------------------------------------------
// enum (app/models/enums.py)
// --------------------------------------------------------------------------

export type StartingLevel = 'beginner' | 'intermediate' | 'advanced'
export type LearningItemType = 'word' | 'grammar' | 'expression'
export type ContextStage = 'anchor' | 'near_original' | 'varied' | 'new_context'
export type PresentationRole = 'review' | 'new' | 'exploration'
export type ReviewReason = 'fsrs_due' | 'reinforcement' | 'context_repair'

/** self-report 3값. `skip`은 여기에 없다 --- self-report는 건너뛸 값이 아니라 안 하는 것이다. */
export type ExplicitSignal = 'known' | 'uncertain' | 'unknown'

/**
 * 서버가 **지금** 내는 probe 4값. UI 라벨은 `알고 있었음 / 애매함 / 몰랐음 / 건너뛰기`다.
 *
 * `Probe.options`와 probe 응답의 `value`는 이 union이 **아니라** `string`이다. 계약은
 * "서버가 값을 추가할 수 있다"이고 화면은 모르는 값을 원문 그대로 보여줘야 하므로
 * (05_API_SPEC.md, `ui/probe.ts`), 4값으로 좁히면 그 경우가 타입상 표현되지 않는다.
 * 이 union이 남아 있는 이유는 **라벨 매핑의 키**이기 때문이다.
 */
export type ProbeResponseValue = ExplicitSignal | 'skip'

export type ContentFlagReason = 'unnatural' | 'wrong' | 'too_easy' | 'too_hard' | 'other'

// --------------------------------------------------------------------------
// auth
// --------------------------------------------------------------------------

export type LoginBody = {
  login_id: string
  password: string
}

export type User = {
  user_id: number
  login_id: string
  timezone: string
  starting_level: StartingLevel
}

// --------------------------------------------------------------------------
// study session
// --------------------------------------------------------------------------

export type StudySession = {
  session_id: number
  /** UTC ISO-8601 문자열. */
  started_at: string
  last_activity_at: string
  ended_at: string | null
  active_seconds: number
  /** 세션 목표 길이. 서버가 준다 --- 12를 frontend에 적지 않는다. */
  target_minutes: number
  extended_minutes: number
}

/** `GET /api/study/session`. 열린 session이 없으면 `session: null`이다. */
export type OpenSessionResponse = {
  session: StudySession | null
}

/** `POST /api/study/session`. */
export type StartSessionResponse = {
  session: StudySession
  resumed: boolean
  /** idle timeout으로 이번에 닫힌 직전 session. 없으면 null. */
  timed_out_session_id: number | null
}

// --------------------------------------------------------------------------
// presentation
// --------------------------------------------------------------------------

/**
 * 서버가 offset을 이미 적용해 만든 렌더링 단위.
 *
 * `text`를 순서대로 이어 붙이면 `japanese`가 된다. **frontend는 index를 계산하지
 * 않는다**(05_API_SPEC.md). `sentence_item_id`가 non-null이면 tap 가능한 span이다.
 */
/** segment 안의 표시 조각. reading이 null이면 후리가나 없이 text만 그린다. */
export type RubyPart = {
  text: string
  reading: string | null
}

export type RenderSegment = {
  text: string
  sentence_item_id: number | null
  /**
   * 후리가나 표시 보조(MVP-02, 05_API_SPEC.md R1~R7). 학습 신호가 아니다.
   * []  이 segment에 달 읽기가 없다 (한자 없음 / 생략 / 미계산 / 저장값 무효 --- 구분하지 않는다)
   * 그 밖  parts.map(p => p.text).join('') === text
   * 토글 상태와 무관하게 서버가 항상 싣는다.
   */
  ruby: RubyPart[]
}

export type TappableItem = {
  sentence_item_id: number
  learning_item_id: number
}

export type Probe = {
  probe_id: number
  learning_item_id: number
  /** 서버가 주는 문구. frontend에 상수로 복사하지 않는다. */
  prompt: string
  expression: string
  /**
   * 표시 순서 그대로. 객관식 의미 문제가 아니다.
   *
   * **`string[]`이다.** 서버가 option을 추가해도 화면이 그 값을 그대로 노출할 수 있어야
   * 하고(조용히 버리면 버튼이 사라진다), 그것이 이 필드의 계약이다.
   */
  options: string[]
}

/** `korean_translation`이 **없다.** 추가하지 마라(모듈 주석). */
export type Presentation = {
  presentation_id: number
  sentence_id: number
  japanese: string
  render_segments: RenderSegment[]
  presentation_role: PresentationRole
  review_reason: ReviewReason | null
  context_stage: ContextStage
  translation_revealed: boolean
  tappable_items: TappableItem[]
  probe: Probe | null
}

/** Ready Pool이 비면 `presentation: null`이고 상태 코드는 **200**이다. 오류가 아니다. */
export type NextPresentationResponse = {
  presentation: Presentation | null
}

export type CompletePresentationResponse = {
  presentation_id: number
  completed_at: string
}

// --------------------------------------------------------------------------
// interaction
// --------------------------------------------------------------------------

/** precomputed `sentence_item_explanations` 그대로. reading은 여기에만 있다. */
export type Explanation = {
  sentence_item_id: number
  learning_item_id: number
  canonical_form: string
  reading: string
  item_type: LearningItemType
  core_meaning: string
  meaning_in_context: string
  nuance: string
  example_sentence: string
  example_translation: string | null
}

export type TranslationResponse = {
  korean_translation: string
}

export type SelfReportBody = {
  sentence_item_id: number
  value: ExplicitSignal
}

/**
 * `learning_item_id`를 보내지 않는다. 서버가 probe event에서 읽는다(ADR-009).
 *
 * `value`는 사용자가 고른 **`options`의 값 그대로**이므로 `options`와 같은 `string`이다.
 * 모르는 값을 골랐다고 보내지 못하면 화면이 그 버튼을 그릴 이유가 없어진다.
 */
export type ProbeResponseBody = {
  probe_id: number
  value: string
}

export type ProbeResultResponse = {
  probe_id: number
  learning_item_id: number
  /** 서버가 기록한 값. 같은 `probe_id`에 이미 응답이 있으면 그 값이다. */
  value: string
}

export type ContentFlagBody = {
  reason: ContentFlagReason
  note?: string | null
}

// --------------------------------------------------------------------------
// history (app/schemas/history.py)
// --------------------------------------------------------------------------

export type HistorySession = {
  session_id: number
  started_at: string
  /** 진행 중인 session은 `null`이다. 목록에서 빠지지 않는다. */
  ended_at: string | null
  active_seconds: number
  target_minutes: number
  extended_minutes: number
  completed_sentence_count: number
}

/**
 * `truncated`는 고정 상한에 걸려 **오래된 행이 잘렸다**는 뜻이다. 총 개수도 상한도 응답에
 * 없다 --- 화면은 이 boolean만 본다. **받은 행 수로 추측하지 않는다**(05_API_SPEC.md의
 * `개수 상한`, 03_UI_UX_SPEC.md의 `History`): 행이 정확히 상한만큼인 사용자에게 잘렸다고
 * 거짓을 말하게 된다.
 */
export type HistorySessionsResponse = {
  sessions: HistorySession[]
  truncated: boolean
}

export type HistoryItem = {
  learning_item_id: number
  lemma: string
  item_type: LearningItemType
  /** `null`은 **"아직 evidence 없음"**이다. 0이 아니다(02_LEARNING_POLICY.md). */
  comprehension_mastery: number | null
  exposure_count: number
  /** `review_states` 행이 없으면 `null`이다. */
  next_review_at: string | null
}

export type HistoryItemsResponse = {
  items: HistoryItem[]
  truncated: boolean
}
