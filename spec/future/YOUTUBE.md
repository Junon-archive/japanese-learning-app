# Future --- YouTube

MVP 밖이며 Content Source 중 하나.

UX: `URL 공유/붙여넣기 → 자동 처리`

Pipeline: metadata → Japanese transcript → clean/segment → mastery 비교
→ candidate → 가치 높은 3\~10개 표현 → learning content → SRS.

Conceptual ranking:
`LearningValue = Frequency × ConversationalValue × PersonalRelevance × UnknownProbability`

같은 영상도 사용자마다 다른 표현을 선택한다. 장기적으로 video
difficulty/comprehension score에 vocabulary, grammar, speech rate,
subtitle quality, colloquiality 등을 반영.

학습 3\~7일 뒤 rewatch와 예상 comprehension improvement 표시를 고려한다.

Ingestion은 교체 가능한 `ContentIngestor`로 구현. 전체
transcript/audio의 불필요한 저장·재배포를 피하고 source/provenance를
유지. 실제 구현 시 최신 YouTube API/Terms를 다시 확인한다.
