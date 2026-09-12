/**
 * 실행 환경에서 오는 값. **frontend에서 origin을 아는 유일한 파일이다.**
 *
 * API origin을 다른 파일에 적으면 배포 도메인이 정해질 때 고쳐야 할 곳이 늘고,
 * 하나를 빠뜨리면 그 요청만 조용히 다른 곳으로 나간다. `tests/unit/no-hardcoded-origin.test.ts`
 * 가 `src/` 전체에서 origin 리터럴이 여기 하나뿐임을 강제한다.
 *
 * frontend origin과 cookie domain은 **어디에도 적지 않는다.** frontend는 자기
 * origin에서 서빙되고, 인증 cookie는 서버가 host-only로 내려준다.
 *
 * `VITE_*`는 빌드 시 번들에 그대로 박히므로 전부 공개값이다. secret을 넣지 않는다
 * (`spec/04_SECURITY_AND_DATA.md`: "PWA bundle에 secret 금지").
 */
export const API_BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
