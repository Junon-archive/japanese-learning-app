/**
 * 가나 정적 데이터 품질(`12_TEST_PLAN.md`의 `가나 학습`, 합격 기준 29·30).
 *
 * 단어의 로마자·한글은 사람이 적은 값이다. 글자 표와 `03_UI_UX_SPEC.md`의 표기 규칙으로 이
 * 파일 안에서 따로 계산해 대조한다. 규칙을 바꾸면 데이터와 이 계산이 함께 바뀌어야 한다.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import {
  KANA_CHAR_RANGES,
  KANA_ITEM_KEYS,
  KANA_ITEMS,
  KANA_RANGES,
  KANA_SCRIPTS,
  KANA_TABLES,
  type KanaItem,
} from '../../src/kana/data'

const WORD_RANGES = ['sokuon', 'choon', 'gairaigo'] as const

function allItems(): KanaItem[] {
  return KANA_SCRIPTS.flatMap((script) => KANA_RANGES.flatMap((range) => [...KANA_ITEMS[script][range]]))
}

function find(text: string): KanaItem {
  const item = allItems().find((candidate) => candidate.text === text)
  if (item === undefined) throw new Error(`missing ${text}`)
  return item
}

const HIRAGANA = /^[ぁ-ゖ]+$/u
const KATAKANA = /^[ァ-ヺー]+$/u
const HANGUL = /^[가-힣]+$/u

describe('kana data counts', () => {
  // 03_UI_UX_SPEC.md `정답 표기`의 글자 표.
  const EXPECTED = { seion: 46, dakuon: 20, handakuon: 5, yoon: 33 } as const

  for (const script of KANA_SCRIPTS) {
    for (const range of KANA_CHAR_RANGES) {
      it(`${script} ${range} has ${EXPECTED[range]} characters`, () => {
        expect(KANA_ITEMS[script][range]).toHaveLength(EXPECTED[range])
      })
    }
  }

  it('seion table keeps the gojuon layout with gaps', () => {
    const texts = KANA_TABLES.hiragana.seion.map((row) => row.map((cell) => cell?.text ?? null))
    expect(texts[7]).toEqual(['や', null, 'ゆ', null, 'よ'])
    expect(texts[9]).toEqual(['わ', null, null, null, 'を'])
    expect(texts[10]).toEqual(['ん', null, null, null, null])
  })

  it('sokuon and choon have at least 4 words with distinct romaji in each script', () => {
    for (const script of KANA_SCRIPTS) {
      for (const range of ['sokuon', 'choon'] as const) {
        const list = KANA_ITEMS[script][range]
        expect(list.length).toBeGreaterThanOrEqual(4)
        expect(new Set(list.map((item) => item.romaji)).size).toBe(list.length)
      }
    }
  })

  it('gairaigo has about 30 words, katakana only, with distinct romaji', () => {
    expect(KANA_ITEMS.hiragana.gairaigo).toEqual([])
    const list = KANA_ITEMS.katakana.gairaigo
    expect(list.length).toBeGreaterThanOrEqual(25)
    expect(list.length).toBeLessThanOrEqual(35)
    expect(new Set(list.map((item) => item.romaji)).size).toBe(list.length)
  })

  it('gairaigo includes extended spellings such as ティ and ファ', () => {
    const texts = KANA_ITEMS.katakana.gairaigo.map((item) => item.text)
    expect(texts.some((text) => text.includes('ティ'))).toBe(true)
    expect(texts.some((text) => text.includes('ファ'))).toBe(true)
  })
})

describe('kana data quality', () => {
  it('has no duplicate text or key anywhere', () => {
    const items = allItems()
    expect(new Set(items.map((item) => item.text)).size).toBe(items.length)
    expect(new Set(items.map((item) => item.key)).size).toBe(items.length)
    expect(KANA_ITEM_KEYS.size).toBe(items.length)
    for (const item of items) expect(item.key).toBe(item.text)
  })

  it('uses lowercase ASCII romaji without long-vowel marks', () => {
    for (const item of allItems()) expect(item.romaji, item.text).toMatch(/^[a-z]+$/)
  })

  it('has hangul for every item and meaning only for words', () => {
    for (const script of KANA_SCRIPTS) {
      for (const range of KANA_RANGES) {
        for (const item of KANA_ITEMS[script][range]) {
          expect(item.hangul, item.text).toMatch(HANGUL)
          if ((WORD_RANGES as readonly string[]).includes(range)) {
            expect(item.meaning?.trim(), item.text).toBeTruthy()
          } else {
            expect(item.meaning, item.text).toBeUndefined()
          }
        }
      }
    }
  })

  it('writes each script only in its own characters', () => {
    for (const range of KANA_RANGES) {
      for (const item of KANA_ITEMS.hiragana[range]) expect(item.text).toMatch(HIRAGANA)
      for (const item of KANA_ITEMS.katakana[range]) expect(item.text).toMatch(KATAKANA)
    }
  })

  it('katakana tables mirror hiragana with the same romaji and hangul', () => {
    for (const range of KANA_CHAR_RANGES) {
      const hira = KANA_ITEMS.hiragana[range]
      const kata = KANA_ITEMS.katakana[range]
      hira.forEach((item, index) => {
        const mirror = kata[index]!
        const shifted = [...item.text].map((ch) => String.fromCodePoint(ch.codePointAt(0)! + 0x60)).join('')
        expect(mirror.text).toBe(shifted)
        expect(mirror.romaji).toBe(item.romaji)
        expect(mirror.hangul).toBe(item.hangul)
      })
    }
  })

  it('sokuon words contain a small tsu and choon words follow the script rule', () => {
    for (const item of KANA_ITEMS.hiragana.sokuon) expect(item.text).toContain('っ')
    for (const item of KANA_ITEMS.katakana.sokuon) {
      expect(item.text).toContain('ッ')
      expect(item.text).not.toContain('ー')
    }
    for (const item of KANA_ITEMS.hiragana.choon) expect(item.text).not.toContain('っ')
    for (const item of KANA_ITEMS.katakana.choon) {
      expect(item.text).toContain('ー')
      expect(item.text).not.toContain('ッ')
    }
  })

  it('loads data through explicit imports only', () => {
    const source = readFileSync(fileURLToPath(new URL('../../src/kana/data.ts', import.meta.url)), 'utf8')
    expect(source).not.toMatch(/import\.meta\.glob/)
    expect(source).not.toMatch(/\bimport\s*\(/)
  })
})

describe('romaji rule examples from 03_UI_UX_SPEC.md', () => {
  it.each([
    ['ん', 'n'],
    ['を', 'o'],
    ['ヲ', 'o'],
    ['し', 'shi'],
    ['ち', 'chi'],
    ['つ', 'tsu'],
    ['ふ', 'fu'],
    ['じ', 'ji'],
    ['ぢ', 'ji'],
    ['づ', 'zu'],
    ['しゃ', 'sha'],
    ['ちゃ', 'cha'],
    ['じゃ', 'ja'],
    ['きゃ', 'kya'],
    ['きって', 'kitte'],
    ['こっち', 'kotchi'],
    ['ええ', 'ee'],
    ['ひこうき', 'hikouki'],
    ['コーヒー', 'koohii'],
  ])('%s is %s', (text, romaji) => {
    expect(find(text).romaji).toBe(romaji)
  })

  it('hangul examples', () => {
    expect(find('ん').hangul).toBe('응')
    expect(find('きって').hangul).toBe('킷테')
    expect(find('コーヒー').hangul).toBe('코오히이')
  })
})

// ---------------------------------------------------------------------------
// 단어 표기 재계산
// ---------------------------------------------------------------------------

type Sound = { romaji: string; hangul: string }

/** 외래어 확장 표기. 로마자는 03 명세(ティ ti · ファ fa)를 따른다. */
const EXTENDED: Record<string, Sound> = {
  ティ: { romaji: 'ti', hangul: '티' },
  ディ: { romaji: 'di', hangul: '디' },
  ファ: { romaji: 'fa', hangul: '파' },
  フィ: { romaji: 'fi', hangul: '피' },
  フェ: { romaji: 'fe', hangul: '페' },
  フォ: { romaji: 'fo', hangul: '포' },
  シェ: { romaji: 'she', hangul: '셰' },
  チェ: { romaji: 'che', hangul: '체' },
  ジェ: { romaji: 'je', hangul: '제' },
}

function soundTable(): Map<string, Sound> {
  const table = new Map<string, Sound>(Object.entries(EXTENDED))
  for (const script of KANA_SCRIPTS) {
    for (const range of KANA_CHAR_RANGES) {
      for (const item of KANA_ITEMS[script][range]) table.set(item.text, item)
    }
  }
  return table
}

const VOWEL_HANGUL: Record<string, string> = { a: '아', i: '이', u: '우', e: '에', o: '오' }
const HANGUL_BASE = 0xac00
const FINAL_K = 1 // ㄱ
const FINAL_P = 17 // ㅂ
const FINAL_S = 19 // ㅅ

function addFinal(syllable: string, final: number): string {
  const offset = syllable.codePointAt(0)! - HANGUL_BASE
  expect(offset % 28).toBe(0)
  return String.fromCodePoint(HANGUL_BASE + offset + final)
}

function spell(word: string): Sound {
  const table = soundTable()
  const units: Sound[] = []
  const chars = [...word]
  let pendingSokuon = false
  let index = 0

  while (index < chars.length) {
    const ch = chars[index]!
    if (ch === 'っ' || ch === 'ッ') {
      pendingSokuon = true
      index += 1
      continue
    }
    if (ch === 'ー') {
      const vowel = units.at(-1)!.romaji.at(-1)!
      units.push({ romaji: vowel, hangul: VOWEL_HANGUL[vowel]! })
      index += 1
      continue
    }

    const pair = chars.slice(index, index + 2).join('')
    const single = table.get(ch)
    let sound = table.get(pair)
    index += sound !== undefined && pair.length === 2 ? 2 : 1
    sound ??= single
    if (sound === undefined) throw new Error(`no sound for ${ch} in ${word}`)

    // 히라가나 お단 뒤의 う는 소리대로 오.
    if (ch === 'う' && units.length > 0 && units.at(-1)!.romaji.endsWith('o')) {
      sound = { romaji: 'u', hangul: '오' }
    }

    if (pendingSokuon) {
      const previous = units.at(-1)!
      const doubled = sound.romaji.startsWith('ch') ? 't' : sound.romaji[0]!
      const final = /^[kg]/.test(sound.romaji) ? FINAL_K : /^[pb]/.test(sound.romaji) ? FINAL_P : FINAL_S
      units[units.length - 1] = {
        romaji: previous.romaji + doubled,
        hangul: addFinal(previous.hangul, final),
      }
      pendingSokuon = false
    }
    units.push(sound)
  }

  return {
    romaji: units.map((unit) => unit.romaji).join(''),
    hangul: units.map((unit) => unit.hangul).join(''),
  }
}

describe('word spelling matches the rules', () => {
  for (const script of KANA_SCRIPTS) {
    for (const range of WORD_RANGES) {
      for (const item of KANA_ITEMS[script][range]) {
        it(`${item.text} -> ${item.romaji} ${item.hangul}`, () => {
          expect(spell(item.text)).toEqual({ romaji: item.romaji, hangul: item.hangul })
        })
      }
    }
  }

  it('the checker itself follows the spec examples', () => {
    expect(spell('がっこう')).toEqual({ romaji: 'gakkou', hangul: '각코오' })
    expect(spell('おう').romaji).toBe('ou')
    expect(spell('マッチ').romaji).toBe('matchi')
  })
})
