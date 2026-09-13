# cloudflared --- API를 기존 터널로 공개하기

`infra/DEPLOY.md` 5절에서 온다. 설계 근거는 `docs/decisions/ADR-020-production-topology.md`
결정 4다. 자리표시자(`<API_HOST>`, `<TUNNEL_NAME>`, `<TUNNEL_SERVICE>` 등)의 뜻은 `infra/DEPLOY.md` 0절의 표에 있다.

이 호스트에는 `<TUNNEL_SERVICE>`(systemd)가 `~/.cloudflared/config.yml`을 읽어 돌리는 기존 터널이 있고,
그 터널에 다른 서비스가 있을 수 있다. 여기에 **규칙 한 줄**을 더한다.

## 1. 이 디렉터리에 두지 않는 것

-   tunnel credentials JSON (`<UUID>.json`)
-   origin 인증서 `cert.pem`
-   실제 설정 파일 `config.yml` / `config.yaml` (cloudflared는 두 이름을 모두 읽는다)

셋 다 `.gitignore`와 `backend/tests/test_git_hygiene.py`가 막는다. 이 디렉터리에는 자리표시자만 쓴
`config.example.yml`과 이 문서만 있다. **호스트의 `~/.cloudflared/config.yml`을 이리로 복사하지
않는다** --- 실제 호스트명이 들어 있다.

## 2. 전제

-   `<ZONE>`이 Cloudflare에 있고 Active다(`infra/DEPLOY.md` 1.2).
-   DNS에 `<API_HOST>` 이름의 레코드가 아직 없다.
-   `infra/DEPLOY.md` 4.7까지 끝나 `curl -s http://127.0.0.1:8000/api/health`가 응답한다.

``` sh
cloudflared --version
systemctl is-active <TUNNEL_SERVICE>     # active
systemctl cat <TUNNEL_SERVICE> | grep ExecStart
# ... --config <HOME>/.cloudflared/config.yml run   ← 이 파일을 고친다
```

`<TUNNEL_NAME>`은 그 설정 파일의 `tunnel:` 값(이름 또는 UUID)이다.

## 3. 기존 터널에 규칙 추가

### 3.1 백업

``` sh
cp -p ~/.cloudflared/config.yml ~/.cloudflared/config.yml.bak.$(date +%Y%m%d-%H%M%S)
ls -l ~/.cloudflared/config.yml.bak.*
```

### 3.2 규칙 한 줄 추가

`~/.cloudflared/config.yml`을 편집기로 연다. `ingress:` 목록의 **catch-all(`- service: http_status:404`)
바로 앞에** 아래 두 줄을 넣는다. 들여쓰기는 기존 항목과 같게 맞춘다.

``` yaml
  - hostname: <API_HOST>
    service: http://127.0.0.1:8000
```

결과는 이런 모양이다.

``` yaml
ingress:
  # ... 기존 서비스의 규칙 (있다면 그대로 둔다)
  - hostname: <API_HOST>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

-   **파일 전체를 `config.example.yml`로 교체하지 않는다.** 기존 서비스의 규칙이 사라진다.
-   **catch-all 뒤에 넣지 않는다.** cloudflared는 위에서부터 첫 매칭을 쓰므로 뒤에 넣은 규칙은
    매칭되지 않는다(`ingress validate`가 이 경우를 오류로 잡는다).
-   **`localhost`가 아니라 `127.0.0.1`이다.** `localhost`는 IPv6(`::1`)로 풀릴 수 있는데 compose는
    IPv4 loopback에만 port를 연다. 기존 규칙이 `localhost`를 쓰는 것은 건드리지 않는다.
-   **5432(PostgreSQL)는 절대 넣지 않는다.** frontend도 넣지 않는다(Workers가 서빙한다).

### 3.3 DNS 연결

``` sh
cloudflared tunnel route dns <TUNNEL_NAME> <API_HOST>
```

`<API_HOST>`에 터널을 가리키는 CNAME이 생긴다. 이미 같은 이름의 레코드가 있으면 실패한다.
이 명령은 origin 인증서(`cert.pem`)를 쓴다. 인증서 관련 오류가 나면 `cloudflared tunnel login`이
필요한 상태일 수 있다(확인 필요 --- 기존 터널을 만들 때의 로그인 상태에 달려 있다).

### 3.4 재시작 전에 검증 --- 둘 다 통과해야 재시작한다

``` sh
cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
# Validating rules from ...
# OK

cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://<API_HOST>/api/health
# Using rules from ...
# Matched rule #N
#     hostname: <API_HOST>
#     service: http://127.0.0.1:8000
```

-   `validate`가 `OK`가 아니면 재시작하지 않는다. YAML 들여쓰기나 규칙 순서를 고친다.
-   `ingress rule`의 결과가 `service: http_status:404`이면 새 규칙이 catch-all 뒤에 있거나
    hostname 오타다. (규칙 번호 `#N`은 0부터 센다.)

### 3.5 재시작

``` sh
sudo systemctl restart <TUNNEL_SERVICE>
systemctl is-active <TUNNEL_SERVICE>                  # active
sudo journalctl -u <TUNNEL_SERVICE> -n 30 --no-pager  # 연결 오류가 없는지
```

**재시작하는 동안 같은 터널의 다른 서비스도 잠깐 끊긴다.** 다른 서비스가 있다면 재시작 뒤 그
서비스들이 다시 응답하는지도 확인한다.

### 3.6 문제가 생기면 되돌리기

``` sh
cp -p ~/.cloudflared/config.yml.bak.<시각> ~/.cloudflared/config.yml
cloudflared tunnel --config ~/.cloudflared/config.yml ingress validate
sudo systemctl restart <TUNNEL_SERVICE>
```

3.3에서 만든 DNS 레코드는 남아 있어도 기존 서비스에 영향이 없다(그 이름이 catch-all 404로 간다).
지우려면 대시보드 DNS에서 `<API_HOST>` 레코드를 지운다.

## 4. 확인

``` sh
curl -s -o /dev/null -w '%{http_code}\n' https://<API_HOST>/api/health    # 200
curl -s -o /dev/null -w '%{http_code}\n' https://<API_HOST>/docs          # 404
```

**터널이 API만 노출하는지:**

``` sh
cloudflared tunnel --config ~/.cloudflared/config.yml ingress rule https://<FRONTEND_HOST>/
# service: http_status:404  ← frontend는 터널에 없다
grep -n '5432' ~/.cloudflared/config.yml
# 출력 없음                  ← DB는 터널에 없다
ss -ltn 'sport = :5432'
# Local Address가 127.0.0.1:5432 뿐 ← DB는 호스트 밖으로 열려 있지 않다
```

## 5. (참고) 새 터널을 만드는 대안

채택하지 않은 방법이다(ADR-020 결정 4의 `버린 대안`). 기존 서비스의 중단이 없다는 이점 대신
credentials 파일, 설정 파일, systemd unit, cloudflared 프로세스가 하나씩 더 생긴다.

형태만 적는다(세부 절차는 cloudflared 문서로 확인한다).

``` text
cloudflared tunnel create <새 터널 이름>          # credentials JSON이 ~/.cloudflared/ 에 생긴다
새 설정 파일 (저장소 밖)                          # tunnel, credentials-file, ingress
                                                  # (config.example.yml의 ingress 두 규칙과 같은 모양)
cloudflared tunnel route dns <새 터널 이름> <API_HOST>
새 systemd unit                                   # cloudflared tunnel --config <새 설정 파일> run
```
