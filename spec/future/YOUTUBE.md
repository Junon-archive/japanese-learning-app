# Future --- YouTube

MVP-01 범위 밖이다.

장기적으로 YouTube는 학습 UI가 아니라 Content Source 중 하나다.

예상 흐름:
`URL → transcript ingestion → cleaning/segmentation → mastery 비교 → 가치 높은 표현 3~10개 선별 → 학습 콘텐츠 → SRS`

Transcript ingestion은 교체 가능한 subsystem으로 설계한다. 플랫폼
API/약관 변경이 전체 앱을 깨뜨리지 않게 한다. 전체 transcript/audio의
불필요한 저장·재배포를 피하고 source/provenance를 유지한다.
