# Sources of the transliteration word lists

The lists in `words/` and `english-common.txt.xz` feed the dictionary rescoring
of Tark's on-device transliteration (D1). They are counts of words in a
public-domain corpus. AI4Bharat's own `word_prob_dicts` are **not** used: they
derive from CC BY-NC-SA data.

## Corpus: IndicCorp v2 (AI4Bharat), licence CC0

- Page: https://huggingface.co/datasets/ai4bharat/IndicCorpV2
- Revision used: `2d7285e6ce14fdb3fb2449c9f89427b9f582ac3f` (last modified
  2025-03-10). Files are fetched from
  `https://huggingface.co/datasets/ai4bharat/IndicCorpV2/resolve/<revision>/data/<file>.txt`.
- Access: the dataset is public (`"gated": false`, `"private": false` in the
  Hugging Face API). It is downloaded without an account, a login or any
  accepted terms.
- Licence, quoted from the dataset card (`README.md`, section "License"):

  > All the datasets created as part of this work will be released under a
  > CC-0 license and all models & code will be release under an MIT license

  Link on the card: https://creativecommons.org/publicdomain/zero/1.0
  The same sentence is in the IndicBERT repository README, section LICENSE
  (https://github.com/AI4Bharat/IndicBERT), whose code is MIT. CC0 allows
  redistributing derived data, including in a BSD-licensed repository.
  Note for the record: the card has no machine-readable `license:` field, and
  its wording is "will be released"; it is the only statement of the terms
  and it is CC0. The paper is Doddapaneni et al., ACL 2023, "Towards Leaving
  No Indic Language Behind".
- The corpus is crawled web text. What is stored here is only a list of
  words with counts (no sentences), so nothing of the text is reproduced.
- Wikipedia (CC BY-SA) was **not** needed: every language below came from
  IndicCorp v2.

## How the lists were made

Each file was streamed and never stored: the first 1 GiB (1,073,741,824
bytes) of the file, or the whole file when it is smaller, went through
`utils/xlit_wordlist.py count` on a pipe. Disk use stayed far below 4 GB.

    curl -sL "$BASE/<file>.txt" | head -c 1073741824 \
      | python3 -I utils/xlit_wordlist.py count --tag <tag> --top <N> \
      > <tag>.tsv          # then: xz -9e (Python lzma, preset 9|extreme)

- Tokens: runs of the script's letters and combining marks bounded by
  whitespace or punctuation; mixed-script and digit-bearing tokens dropped;
  NFC-normalised (see the module docstring).
- Top 50,000 words per language; 100,000 for `ta`, `te`, `kn`, `ml`
  (agglutinative). Ties are broken by the word, so the output is stable.
- `ks` and `mni` were counted with `--min-count 2`: their corpora are tiny
  (0.7 MB and 9 MB), and about a third of their words (36% and 31%) were seen
  once, which are mostly typos and would pass the dictionary filter as if they were words.
- The counter drops words seen only once whenever it holds more than six
  million distinct words. They cannot reach a top-100,000, and counts of the
  listed words are exact apart from a deficit of at most a few units for
  words that were dropped early and came back.
- Hindi: only `hi-1.txt` of the three Hindi parts (it already exceeds 1 GiB).
- `sd` data is in Arabic script (the card's split label says Devanagari, but
  the file is Perso-Arabic, matching IndicXlit's Sindhi output). `ks` and
  `ur` are Perso-Arabic; `mni` is Meetei Mayek; `brx`, `gom`, `mai`, `ne`,
  `sa`, `mr`, `hi` Devanagari; `as` and `bn` Bengali script.

| tag | IndicCorp v2 file | file size (bytes) | bytes streamed | words listed | .tsv.xz (bytes) |
|---|---|---|---|---|---|
| as | data/as.txt | 1,182,787,233 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 248,400 |
| bn | data/bn.txt | 15,992,871,652 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 248,980 |
| brx | data/bd.txt | 45,069,440 | 45,069,440 (whole file) | 50,000 | 205,824 |
| gom | data/gom.txt | 533,108,246 | 533,108,246 (whole file) | 50,000 | 234,904 |
| gu | data/gu.txt | 14,130,326,225 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 244,396 |
| hi | data/hi-1.txt | 26,661,096,882 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 241,376 |
| kn | data/kn.txt | 19,582,655,935 | 1,073,741,824 (cut at 1 GiB) | 100,000 | 496,792 |
| ks | data/ks.txt | 693,894 | 693,894 (whole file) | 7,309 | 28,008 |
| mai | data/mai.txt | 198,401,487 | 198,401,487 (whole file) | 50,000 | 214,936 |
| ml | data/ml.txt | 26,319,980,640 | 1,073,741,824 (cut at 1 GiB) | 100,000 | 510,408 |
| mni | data/mni.txt | 9,324,003 | 9,324,003 (whole file) | 21,708 | 80,800 |
| mr | data/mr.txt | 14,553,660,884 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 253,484 |
| ne | data/ne.txt | 14,773,136,386 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 251,676 |
| or | data/or.txt | 2,177,310,918 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 249,004 |
| pa | data/pa.txt | 9,480,517,356 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 229,416 |
| sa | data/sa.txt | 3,106,385,011 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 254,712 |
| sd | data/sd.txt | 111,526,244 | 111,526,244 (whole file) | 50,000 | 179,984 |
| ta | data/ta.txt | 11,790,368,869 | 1,073,741,824 (cut at 1 GiB) | 100,000 | 485,452 |
| te | data/te.txt | 15,760,603,733 | 1,073,741,824 (cut at 1 GiB) | 100,000 | 493,764 |
| ur | data/ur.txt | 5,589,070,760 | 1,073,741,824 (cut at 1 GiB) | 50,000 | 208,980 |

**`si` (Sinhala) has no list.** IndicCorp v2 has no Sinhala part. The model
still transliterates `si`; without a list it returns its own candidate order.

## English: `english-common.txt.xz`

IndicCorp v2 `data/en.txt` (the English part), first 1 GiB, counted with
`count --tag en --top 20000` (lower-cased, a-z only, apostrophe words
dropped). The 584 words in `english-exclude.txt` are removed (19,416 remain).
`english-exclude.txt` gives a one-line reason for each; the rule is at its top.
Rebuild:

    xlit_wordlist.py english en.tsv english-exclude.txt | xz -9e > english-common.txt.xz

The exclusions were found by transliterating every one of the 20,000 words to
Hindi with the reference implementation and keeping, after review, the ones
that are Indian-language words or names whose Devanagari form is among the
5,000 commonest Hindi words (1,640 words matched; most are English
loanwords such as `school` and were kept as English).

## Other files

- `golden-inputs.txt`, `golden.tsv`: generated by
  `utils/xlit_reference.py <model> --golden golden-inputs.txt`.
