/**
 * **현재 소스로 만든 빌드 산출물**. `no-service-worker.test.ts`와 격리 검사 (e)(`demo-isolation.test.ts`)가
 * 함께 쓴다(ADR-022 결정 2).
 *
 * 예전에는 `dist/`가 있으면 그대로 읽었다. 그러면 옛 번들을 검사하고도 초록이 된다 --- SW를 등록하는
 * 코드나 API 코드를 entry 청크로 합치는 설정을 방금 넣어도 산출물이 낡아 있으면 테스트가 통과한다.
 * "테스트는 초록인데 아무것도 검증하지 않는" 실패 방식이고, 이 helper를 쓰는 테스트가 막으려는 회귀가
 * 바로 그런 종류(빌드에만 드러나는 것)라서 특히 나쁘다.
 *
 * -   **가장 오래된 산출물이 가장 최근 소스보다 낡았으면 다시 빌드한다.** 실패로 끝내지 않는 이유는
 *     산출물이 git에 없기 때문이다 --- 새로 받은 저장소에서 `vitest`만 돌려도 검증할 산출물이 있어야 한다.
 *     비용은 낡았을 때만 든다. 최신이면 `stat`만 한다.
 * -   **산출물 위치는 `dist/`가 아니라 `node_modules/.cache/nc-unit-build/`다.** 설정은 `npm run build`
 *     그대로이고 `--outDir`만 바꾼다. e2e 하네스(`backend/tests/e2e/conftest.py`)는 `dist/`를 지우고
 *     `VITE_API_BASE_URL`을 넣어 다시 빌드한다. 같은 곳을 쓰면 e2e 뒤의 최신 `dist/`에는 기본 origin이
 *     없어서 (e)의 양성 대조군이 소스와 무관하게 흔들린다.
 * -   **`VITE_*` 없이 빌드한다**(ADR-022: unit 빌드는 `VITE_API_BASE_URL` 없이 돈다). 그래서 산출물에 박히는
 *     API base URL은 `env.ts`의 기본 origin이다.
 * -   vitest는 테스트 파일을 병렬 worker로 돌린다. 두 파일이 동시에 빌드하거나 한쪽이 비워지는 중인
 *     디렉터리를 읽지 않도록 **신선도 확인과 빌드를 잠금 파일 안에서** 한다.
 */
import { execFileSync } from 'node:child_process'
import { closeSync, existsSync, mkdirSync, openSync, readdirSync, statSync, unlinkSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('../..', import.meta.url))
const CACHE = join(ROOT, 'node_modules', '.cache')
export const BUILD_DIR = join(CACHE, 'nc-unit-build')
const LOCK = join(CACHE, 'nc-unit-build.lock')
const LOCK_LIMIT_MS = 10 * 60 * 1000

/** 산출물에 영향을 주는 입력 전부. 하나라도 빠지면 그만큼 낡은 것을 검증할 수 있다. */
const SOURCES = ['src', 'public', 'index.html', 'vite.config.ts', 'tsconfig.json', 'package.json']

export function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry)
    return statSync(path).isDirectory() ? walk(path) : [path]
  })
}

function newestSourceMtime(): number {
  const files = SOURCES.map((entry) => join(ROOT, entry))
    .filter((path) => existsSync(path))
    .flatMap((path) => (statSync(path).isDirectory() ? walk(path) : [path]))
  return Math.max(...files.map((path) => statSync(path).mtimeMs))
}

function isFresh(): boolean {
  if (!existsSync(join(BUILD_DIR, 'index.html'))) return false
  const outputs = walk(BUILD_DIR)
  return Math.min(...outputs.map((path) => statSync(path).mtimeMs)) >= newestSourceMtime()
}

function sleep(ms: number): void {
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms)
}

function withLock<T>(body: () => T): T {
  mkdirSync(CACHE, { recursive: true })
  const started = Date.now()
  for (;;) {
    try {
      closeSync(openSync(LOCK, 'wx'))
      break
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
      // 빌드 도중 죽은 프로세스가 남긴 잠금.
      if (existsSync(LOCK) && Date.now() - statSync(LOCK).mtimeMs > LOCK_LIMIT_MS) unlinkSync(LOCK)
      if (Date.now() - started > LOCK_LIMIT_MS) throw new Error(`build lock ${LOCK} is held too long`)
      sleep(200)
    }
  }
  try {
    return body()
  } finally {
    unlinkSync(LOCK)
  }
}

function buildEnv(): NodeJS.ProcessEnv {
  const env = { ...process.env }
  for (const key of Object.keys(env)) {
    if (key.startsWith('VITE_')) delete env[key]
  }
  // vitest가 넣는 NODE_ENV=test가 셸의 `npm run build`와 다른 빌드를 만들지 않게 한다.
  delete env.NODE_ENV
  return env
}

/** 현재 소스로 만든 산출물의 모든 파일(절대 경로). */
export function buildOutput(): { dir: string; files: string[] } {
  withLock(() => {
    if (isFresh()) return
    execFileSync('npm', ['run', 'build', '--', '--outDir', BUILD_DIR, '--emptyOutDir'], {
      cwd: ROOT,
      env: buildEnv(),
      stdio: 'inherit',
    })
  })
  return { dir: BUILD_DIR, files: walk(BUILD_DIR) }
}
