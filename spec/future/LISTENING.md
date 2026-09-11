# Future --- Listening

**MVP-01에는 audio가 전혀 없다.**

``` text
TTS 없음
audio button 없음
audio API 없음
audio event 없음
listening review 없음
```

MVP schema에는 `listening_mastery`가 nullable float로 존재하지만 초기값은
NULL이고 MVP에서 갱신하지 않는다. NULL은 listening 능력이 0이라는 뜻이
아니라 **아직 측정하지 않았다**는 뜻이다.

`item_exposures.modality`도 MVP에서는 `reading`만 사용한다. listening이
추가되면 별도 modality로 확장한다.

고급 listening은 Future.

-   TTS와 real spontaneous speech 구분
-   audio recognition review
-   동일 표현의 읽기/듣기 mastery 분리
-   실제 발화의 속도·축약·억양으로 확장

TTS만으로 최종 청해 능력을 대표하지 않는다.
