# ADR-014 --- 닫힌 session / 완료된 presentation의 상호작용

Status: Accepted

Decision: presentation 상호작용 5종(click, explanation-revealed,
translation reveal, self-report, probe-response)은 **session이 닫혔거나
presentation이 이미 완료됐으면 409로 거부한다.** 예외는 둘이다. `/complete`는
이미 완료된 presentation이면 200(열린 presentation인데 session이 닫혔으면 409),
`/flag`는 상태와 무관하게 허용한다. canonical 표는 `05_API_SPEC.md`의
`세션·presentation 상태 게이트`.

## 문제

`/next`와 `/extend`만 닫힌 session을 409로 막았고 나머지 7개는 그대로
동작했다. 구현자가 `/next`에 그 검사를 넣으면서 코드 주석에 "명세 공백"이라고
적어 둔 상태였다.

security review 실측(끝난 session의 presentation):

``` text
click 200 / explanation-revealed 204 / translation reveal 200
self-report 204 / flag 204 / complete 200 / probe-response 400
```

`self-report`가 **끝난 session에서 새 mastery 행을 만들었고**,
`begin_interaction()`이 닫힌 session의 `last_activity_at`을 계속 갱신했다.

학습 관점의 문제가 더 크다. presentation을 닫을 때 exposure 확정과 무신호
처리(`deferred_until`)가 이미 끝난다. 그 뒤에 붙는 explicit evidence는 **같은
노출을 두 번, 서로 다르게 평가**한다.

## 버린 대안

**(a) 허용하되 이중 평가만 막는다** (event는 남기고 mastery/FSRS 부수효과는
건너뛴다). "기록은 되는데 반영은 안 되는" event가 생겨 로그 해석이
`created` 여부 외에 presentation 상태까지 봐야 하는 일이 된다. 12개 endpoint에
같은 조건 분기를 흩뿌리는 비용도 같다.

**(b) session 상태만 보고 presentation 완료 여부는 무시한다.** 이중 평가는
**열린 session 안에서도** 일어난다(`/complete` 직후 같은 pid에 self-report).
session만 막으면 그 경로가 남는다.

**(c) flag도 똑같이 막는다.** 표를 완전히 균일하게 만들 수 있어 처음에는 이쪽을
택했다가 뒤집었다. `10_ERROR_HANDLING.md`의 `Content Flag 동작`이 "이미 생성된
`item_exposures`는 `invalidated_at`을 설정"하라고 요구하는데, exposure는
presentation을 닫는 트랜잭션에서 생기므로 **완료 이후의 flag만** 그 조항을 참으로
만든다. flag를 막으면 canonical 조항 하나와 그것을 구현한
`content_flag._invalidate_exposures()`가 통째로 도달 불가능해진다. flag는 evidence를
추가하지 않고 되돌리기만 하므로 이중 평가 위험도 없다. 균일함보다 조항의 도달
가능성이 중요하다.

## 근거

-   idle timeout이 **화면을 보는 도중** 세션을 닫는 일은 없다. 모든 상호작용이
    `last_activity_at`을 갱신하고, 만료 판정은 `POST /api/study/session`이
    도착한 그 시점에만 적용된다. 409를 받는 화면은 사용자가 직접 종료했거나
    다른 탭에서 새 세션을 연 뒤의 stale 화면이다. 즉 이 거부로 잃는 정상
    상호작용이 사실상 없다.
-   `/complete`의 재호출 200은 유지해야 한다. 성공한 `/complete`의 네트워크
    재시도가 그 사이 도착한 `/finish` 때문에 실패로 보이면 client는 완료된
    문장을 완료되지 않은 것으로 취급한다.
-   거부 코드를 409로 통일한 이유: `/next`·`/extend`가 이미 409이고, client의
    복구 동작이 셋 다 같다(`POST /api/study/session` -> `/next`).
-   `/flag`는 허용하되 **닫힌 session의 `last_activity_at`을 갱신하지 않는다.**
    끝난 세션의 길이와 `active_seconds`를 뒤늦게 바꾸지 않으면서 신고는 받는다.

## 한계

거부된 상호작용은 **재전송하지 않는다.** 세션 종료와 겹친 in-flight 요청의
evidence 1건은 유실될 수 있다. 그 노출의 평가가 이미 끝난 이상 뒤늦게
반영하는 것보다 유실이 낫다고 본다.
