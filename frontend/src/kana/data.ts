/**
 * 가나 학습 정적 데이터(`spec/mvp-01-core/03_UI_UX_SPEC.md`의 `가나 학습`).
 *
 * 로마자는 헵번식 소문자 ASCII이고 장음 부호를 쓰지 않는다. ん=n, を=o, 촉음은 다음 자음을
 * 겹치고(っち tchi), 장음은 가나대로(おう ou), 가타카나 ー는 앞 모음을 반복한다(コーヒー koohii).
 * 한글은 외래어 표기법이 아니라 학습자용 소리 근사다. 가타카나 글자는 대응하는 히라가나와 같은
 * 로마자·한글을 쓴다.
 *
 * 단어의 한글 표기 규칙(데이터 일관성, `kana-data.test.ts`가 대조한다):
 * - 촉음은 앞 음절의 받침이다. 다음 소리가 k·g면 ㄱ, p·b면 ㅂ, 그 밖은 ㅅ (きって 킷테, カップ 캅푸).
 * - 가타카나 ー는 앞 모음 소리를 한 번 더 적는다(コーヒー 코오히이).
 * - 히라가나 お단 뒤의 う는 소리대로 오로 적는다(ひこうき 히코오키).
 *
 * `key`는 진도 저장(`nc.kana.v1`)에 쓰는 식별자다. 글자·단어 표기는 데이터 전체에서 겹치지 않으므로
 * 표기 자체를 key로 쓴다.
 */

export const KANA_SCRIPTS = ['hiragana', 'katakana'] as const
export type KanaScript = (typeof KANA_SCRIPTS)[number]

export const KANA_RANGES = [
  'seion',
  'dakuon',
  'handakuon',
  'yoon',
  'sokuon',
  'choon',
  'gairaigo',
] as const
export type KanaRange = (typeof KANA_RANGES)[number]

/** 글자 단위로 묻고 표로 보여주는 범위. 나머지는 단어 단위다. */
export const KANA_CHAR_RANGES = ['seion', 'dakuon', 'handakuon', 'yoon'] as const
export type KanaCharRange = (typeof KANA_CHAR_RANGES)[number]

export type KanaItem = {
  readonly key: string
  readonly text: string
  readonly romaji: string
  readonly hangul: string
  /** 단어(촉음·장음·외래어)에만 있다. */
  readonly meaning?: string
}

/** 표의 한 줄. `null`은 빈 칸이다(や행·わ행·ん). */
export type KanaTableRow = readonly (KanaItem | null)[]

/** [히라가나, 가타카나, 로마자, 한글] */
type CharCell = readonly [string, string, string, string] | null

const SEION: readonly (readonly CharCell[])[] = [
  [['あ', 'ア', 'a', '아'], ['い', 'イ', 'i', '이'], ['う', 'ウ', 'u', '우'], ['え', 'エ', 'e', '에'], ['お', 'オ', 'o', '오']],
  [['か', 'カ', 'ka', '카'], ['き', 'キ', 'ki', '키'], ['く', 'ク', 'ku', '쿠'], ['け', 'ケ', 'ke', '케'], ['こ', 'コ', 'ko', '코']],
  [['さ', 'サ', 'sa', '사'], ['し', 'シ', 'shi', '시'], ['す', 'ス', 'su', '스'], ['せ', 'セ', 'se', '세'], ['そ', 'ソ', 'so', '소']],
  [['た', 'タ', 'ta', '타'], ['ち', 'チ', 'chi', '치'], ['つ', 'ツ', 'tsu', '츠'], ['て', 'テ', 'te', '테'], ['と', 'ト', 'to', '토']],
  [['な', 'ナ', 'na', '나'], ['に', 'ニ', 'ni', '니'], ['ぬ', 'ヌ', 'nu', '누'], ['ね', 'ネ', 'ne', '네'], ['の', 'ノ', 'no', '노']],
  [['は', 'ハ', 'ha', '하'], ['ひ', 'ヒ', 'hi', '히'], ['ふ', 'フ', 'fu', '후'], ['へ', 'ヘ', 'he', '헤'], ['ほ', 'ホ', 'ho', '호']],
  [['ま', 'マ', 'ma', '마'], ['み', 'ミ', 'mi', '미'], ['む', 'ム', 'mu', '무'], ['め', 'メ', 'me', '메'], ['も', 'モ', 'mo', '모']],
  [['や', 'ヤ', 'ya', '야'], null, ['ゆ', 'ユ', 'yu', '유'], null, ['よ', 'ヨ', 'yo', '요']],
  [['ら', 'ラ', 'ra', '라'], ['り', 'リ', 'ri', '리'], ['る', 'ル', 'ru', '루'], ['れ', 'レ', 're', '레'], ['ろ', 'ロ', 'ro', '로']],
  [['わ', 'ワ', 'wa', '와'], null, null, null, ['を', 'ヲ', 'o', '오']],
  [['ん', 'ン', 'n', '응'], null, null, null, null],
]

const DAKUON: readonly (readonly CharCell[])[] = [
  [['が', 'ガ', 'ga', '가'], ['ぎ', 'ギ', 'gi', '기'], ['ぐ', 'グ', 'gu', '구'], ['げ', 'ゲ', 'ge', '게'], ['ご', 'ゴ', 'go', '고']],
  [['ざ', 'ザ', 'za', '자'], ['じ', 'ジ', 'ji', '지'], ['ず', 'ズ', 'zu', '즈'], ['ぜ', 'ゼ', 'ze', '제'], ['ぞ', 'ゾ', 'zo', '조']],
  [['だ', 'ダ', 'da', '다'], ['ぢ', 'ヂ', 'ji', '지'], ['づ', 'ヅ', 'zu', '즈'], ['で', 'デ', 'de', '데'], ['ど', 'ド', 'do', '도']],
  [['ば', 'バ', 'ba', '바'], ['び', 'ビ', 'bi', '비'], ['ぶ', 'ブ', 'bu', '부'], ['べ', 'ベ', 'be', '베'], ['ぼ', 'ボ', 'bo', '보']],
]

const HANDAKUON: readonly (readonly CharCell[])[] = [
  [['ぱ', 'パ', 'pa', '파'], ['ぴ', 'ピ', 'pi', '피'], ['ぷ', 'プ', 'pu', '푸'], ['ぺ', 'ペ', 'pe', '페'], ['ぽ', 'ポ', 'po', '포']],
]

const YOON: readonly (readonly CharCell[])[] = [
  [['きゃ', 'キャ', 'kya', '캬'], ['きゅ', 'キュ', 'kyu', '큐'], ['きょ', 'キョ', 'kyo', '쿄']],
  [['しゃ', 'シャ', 'sha', '샤'], ['しゅ', 'シュ', 'shu', '슈'], ['しょ', 'ショ', 'sho', '쇼']],
  [['ちゃ', 'チャ', 'cha', '차'], ['ちゅ', 'チュ', 'chu', '추'], ['ちょ', 'チョ', 'cho', '초']],
  [['にゃ', 'ニャ', 'nya', '냐'], ['にゅ', 'ニュ', 'nyu', '뉴'], ['にょ', 'ニョ', 'nyo', '뇨']],
  [['ひゃ', 'ヒャ', 'hya', '햐'], ['ひゅ', 'ヒュ', 'hyu', '휴'], ['ひょ', 'ヒョ', 'hyo', '효']],
  [['みゃ', 'ミャ', 'mya', '먀'], ['みゅ', 'ミュ', 'myu', '뮤'], ['みょ', 'ミョ', 'myo', '묘']],
  [['りゃ', 'リャ', 'rya', '랴'], ['りゅ', 'リュ', 'ryu', '류'], ['りょ', 'リョ', 'ryo', '료']],
  [['ぎゃ', 'ギャ', 'gya', '갸'], ['ぎゅ', 'ギュ', 'gyu', '규'], ['ぎょ', 'ギョ', 'gyo', '교']],
  [['じゃ', 'ジャ', 'ja', '자'], ['じゅ', 'ジュ', 'ju', '주'], ['じょ', 'ジョ', 'jo', '조']],
  [['びゃ', 'ビャ', 'bya', '뱌'], ['びゅ', 'ビュ', 'byu', '뷰'], ['びょ', 'ビョ', 'byo', '뵤']],
  [['ぴゃ', 'ピャ', 'pya', '퍄'], ['ぴゅ', 'ピュ', 'pyu', '퓨'], ['ぴょ', 'ピョ', 'pyo', '표']],
]

/** [표기, 로마자, 한글, 한국어 뜻] */
type WordRow = readonly [string, string, string, string]

const HIRAGANA_SOKUON: readonly WordRow[] = [
  ['きって', 'kitte', '킷테', '우표'],
  ['ざっし', 'zasshi', '잣시', '잡지'],
  ['きっぷ', 'kippu', '킵푸', '표(승차권)'],
  ['こっち', 'kotchi', '콧치', '이쪽'],
  ['まっちゃ', 'matcha', '맛차', '말차'],
  ['みっつ', 'mittsu', '밋츠', '세 개'],
  ['ちょっと', 'chotto', '촛토', '조금'],
]

const HIRAGANA_CHOON: readonly WordRow[] = [
  ['ええ', 'ee', '에에', '네(대답)'],
  ['いいえ', 'iie', '이이에', '아니요'],
  ['おおきい', 'ookii', '오오키이', '크다'],
  ['くうき', 'kuuki', '쿠우키', '공기'],
  ['ひこうき', 'hikouki', '히코오키', '비행기'],
  ['おとうと', 'otouto', '오토오토', '남동생'],
]

const KATAKANA_SOKUON: readonly WordRow[] = [
  ['ベッド', 'beddo', '벳도', '침대'],
  ['カップ', 'kappu', '캅푸', '컵'],
  ['バッグ', 'baggu', '박구', '가방'],
  ['ポケット', 'poketto', '포켓토', '주머니'],
  ['マッチ', 'matchi', '맛치', '성냥'],
  ['スリッパ', 'surippa', '스립파', '슬리퍼'],
]

const KATAKANA_CHOON: readonly WordRow[] = [
  ['コーヒー', 'koohii', '코오히이', '커피'],
  ['ケーキ', 'keeki', '케에키', '케이크'],
  ['ノート', 'nooto', '노오토', '공책'],
  ['スーパー', 'suupaa', '스우파아', '슈퍼마켓'],
  ['ビール', 'biiru', '비이루', '맥주'],
  ['タクシー', 'takushii', '타쿠시이', '택시'],
]

const KATAKANA_GAIRAIGO: readonly WordRow[] = [
  ['テレビ', 'terebi', '테레비', '텔레비전'],
  ['カメラ', 'kamera', '카메라', '카메라'],
  ['ホテル', 'hoteru', '호테루', '호텔'],
  ['トイレ', 'toire', '토이레', '화장실'],
  ['バス', 'basu', '바스', '버스'],
  ['ピアノ', 'piano', '피아노', '피아노'],
  ['シャツ', 'shatsu', '샤츠', '셔츠'],
  ['ゲーム', 'geemu', '게에무', '게임'],
  ['ニュース', 'nyuusu', '뉴우스', '뉴스'],
  ['メニュー', 'menyuu', '메뉴우', '메뉴'],
  ['ジュース', 'juusu', '주우스', '주스'],
  ['チーズ', 'chiizu', '치이즈', '치즈'],
  ['トマト', 'tomato', '토마토', '토마토'],
  ['タオル', 'taoru', '타오루', '수건'],
  ['シャワー', 'shawaa', '샤와아', '샤워'],
  ['サラダ', 'sarada', '사라다', '샐러드'],
  ['ギター', 'gitaa', '기타아', '기타(악기)'],
  ['カレー', 'karee', '카레에', '카레'],
  ['スカート', 'sukaato', '스카아토', '치마'],
  ['エレベーター', 'erebeetaa', '에레베에타아', '엘리베이터'],
  ['チケット', 'chiketto', '치켓토', '표, 티켓'],
  ['パーティー', 'paatii', '파아티이', '파티'],
  ['ティッシュ', 'tisshu', '팃슈', '티슈'],
  ['ファイル', 'fairu', '파이루', '파일'],
  ['ソファ', 'sofa', '소파', '소파'],
  ['フォーク', 'fooku', '포오쿠', '포크'],
  ['カフェ', 'kafe', '카페', '카페'],
  ['チェック', 'chekku', '첵쿠', '확인, 체크'],
  ['シェフ', 'shefu', '셰후', '요리사'],
  ['ディナー', 'dinaa', '디나아', '저녁 식사'],
]

function charTable(script: KanaScript, rows: readonly (readonly CharCell[])[]): readonly KanaTableRow[] {
  return rows.map((row) =>
    row.map((cell) => {
      if (cell === null) return null
      const [hiragana, katakana, romaji, hangul] = cell
      const text = script === 'hiragana' ? hiragana : katakana
      return { key: text, text, romaji, hangul }
    }),
  )
}

function words(rows: readonly WordRow[]): readonly KanaItem[] {
  return rows.map(([text, romaji, hangul, meaning]) => ({ key: text, text, romaji, hangul, meaning }))
}

function tables(script: KanaScript): Record<KanaCharRange, readonly KanaTableRow[]> {
  return {
    seion: charTable(script, SEION),
    dakuon: charTable(script, DAKUON),
    handakuon: charTable(script, HANDAKUON),
    yoon: charTable(script, YOON),
  }
}

/** 글자 범위의 표(빈 칸 포함). */
export const KANA_TABLES: Readonly<Record<KanaScript, Record<KanaCharRange, readonly KanaTableRow[]>>> = {
  hiragana: tables('hiragana'),
  katakana: tables('katakana'),
}

function flatten(rows: readonly KanaTableRow[]): readonly KanaItem[] {
  return rows.flat().filter((cell): cell is KanaItem => cell !== null)
}

function items(
  script: KanaScript,
  sokuon: readonly WordRow[],
  choon: readonly WordRow[],
  gairaigo: readonly WordRow[],
): Record<KanaRange, readonly KanaItem[]> {
  const table = KANA_TABLES[script]
  return {
    seion: flatten(table.seion),
    dakuon: flatten(table.dakuon),
    handakuon: flatten(table.handakuon),
    yoon: flatten(table.yoon),
    sokuon: words(sokuon),
    choon: words(choon),
    gairaigo: words(gairaigo),
  }
}

/** 문자 체계·범위별 문항 목록. 외래어는 가타카나에만 있고 히라가나 외래어는 비어 있다. */
export const KANA_ITEMS: Readonly<Record<KanaScript, Record<KanaRange, readonly KanaItem[]>>> = {
  hiragana: items('hiragana', HIRAGANA_SOKUON, HIRAGANA_CHOON, []),
  katakana: items('katakana', KATAKANA_SOKUON, KATAKANA_CHOON, KATAKANA_GAIRAIGO),
}

/** 진도 저장값 검증용. 데이터에 있는 모든 글자·단어 key. */
export const KANA_ITEM_KEYS: ReadonlySet<string> = new Set(
  KANA_SCRIPTS.flatMap((script) => KANA_RANGES.flatMap((range) => KANA_ITEMS[script][range].map((item) => item.key))),
)
