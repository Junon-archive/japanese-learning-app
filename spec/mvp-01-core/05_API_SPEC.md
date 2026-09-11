# API Specification

구체적인 URL naming은 구현 계획에서 확정할 수 있으나 기능 경계는 아래를
따른다.

## Auth

-   login
-   logout
-   current user/session

## Study Session

-   create/resume session
-   get next sentence
-   finish session
-   extend session +5 min

## Sentence

-   get sentence payload
-   reveal/record translation event
-   get precomputed item explanation

## Learning Event

-   record item click
-   record self-report
-   record mastery probe response
-   record audio event
-   record content flag

## History

-   basic recent sessions
-   basic learned/reviewed item summary

## Demo

-   get demo session/fixture
-   demo endpoints must not trigger paid LLM generation
-   demo endpoints must not expose private user data

## API Principles

-   Browser never receives OpenAI secret.
-   Normal item tap should not depend on live LLM response.
-   API response schema를 명확히 정의하고 frontend와 backend 사이에
    implicit state를 최소화한다.
-   idempotency가 필요한 event endpoint는 중복 저장 방지 전략을 가진다.
