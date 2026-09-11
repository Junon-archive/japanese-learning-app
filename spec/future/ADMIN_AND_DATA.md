# Future --- Admin and Data

작은 admin 후보: - flagged sentence 확인 - edit/delete/regenerate -
explanation edit - LearningItem merge - lemma/surface 수정 -
provenance/prompt/job 확인 및 retry

Export 후보: - vocabulary.csv - learning_history.json - sentences.json

DB backup은 restore 가능성까지 검증한다.

## MVP와의 경계

admin UI 자체는 Future지만 **content flag 시 quarantine 동작은 MVP
필수**다(`spec/mvp-01-core/10_ERROR_HANDLING.md`). flag된 콘텐츠가 다시
선택되지 않도록 막는 것까지가 MVP이고, 그것을 사람이 검토·수정·재생성하는
화면이 Future다.

export도 Future다(`spec/04_SECURITY_AND_DATA.md`의 Portability).
