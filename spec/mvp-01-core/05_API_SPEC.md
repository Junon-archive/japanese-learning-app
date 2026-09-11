# API Specification

기능 경계: - Auth: login/logout/me - Session:
create/resume/next/finish/extend - Sentence: payload, translation event,
item explanation - Events: click/self-report/probe/audio/flag - History:
recent sessions/basic summary - Demo: fixture only, no paid
generation/private data

Browser는 OpenAI secret을 받지 않는다. normal tap은 live LLM에 의존하지
않는다. 필요한 event endpoint는 idempotency를 고려한다.
