# User Flow

## Private Learning

``` text
App Open
→ Authentication check
→ Today session create/resume
→ Sentence selected
→ Sentence displayed
→ User reads Japanese first
   ├─ item tap → explanation + reading
   │             └─ optional known/uncertain/unknown feedback
   ├─ translation reveal
   ├─ audio action if audio exists
   ├─ occasional mastery probe
   └─ next sentence
→ LearningEvent saved
→ mastery/review state updated
→ next sentence selected
→ ~12 min reached
→ session complete
→ optional +5 min
```

## Public Demo

``` text
Visitor opens app
→ Demo mode available immediately
→ prebuilt sentence fixture
→ item tap / explanation / probe / contextual review 체험
→ no private DB access
→ no paid LLM call
```

## UX Rules

-   다음 문장으로 가기 위해 self-report를 강제하지 않는다.
-   표현을 클릭하지 않았다는 사실만으로 Known 처리하지 않는다.
-   번역은 기본 hidden.
-   reading은 표현 설명을 열 때 노출.
-   mastery probe는 학습 흐름을 과도하게 방해하지 않도록 드물게
    삽입한다.
