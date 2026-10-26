"""M3d: Tark's page pattern, stated as facts a page must meet (spec
2026-10-18-tark-own-pages-design.md)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import page_audit  # noqa: E402

INDIGO = {False: 'rgb(67, 56, 202)', True: 'rgb(143, 136, 255)'}
CORAL = {False: '2px rgb(230, 62, 92)', True: '2px rgb(255, 107, 133)'}


def facts(dark=False, **overrides):
    clean = {
        'dark': dark,
        'label': 'History',
        'label_transform': 'uppercase',
        'label_color': INDIGO[dark],
        'sentence': 'Kept on this Mac only. 5 pages today.',
        'sentence_lines': 1,
        'row_shadows': 0,
        'sidebar_selected_border': CORAL[dark],
        'actions': [],
        'danger_row': None,
        'rows': 6,
    }
    clean.update(overrides)
    return clean


def test_clean_facts_have_no_problems():
    assert page_audit.problems('history', facts()) == []
    assert page_audit.problems('history', facts(dark=True)) == []


def test_header_label_must_be_uppercase_indigo():
    assert page_audit.problems('history', facts(label_transform='none'))
    assert page_audit.problems('history', facts(label_color='rgb(32, 33, 36)'))
    # Dark mode wants the dark indigo, not the light one.
    assert page_audit.problems('history', facts(dark=True, label_color=INDIGO[False]))


SENTENCES = {
    'downloads': (['3 files today, saved to your Downloads folder',
                   '1 file today, saved to your Downloads folder',
                   'Saved to your Downloads folder'],
                  ['Download history', '3 files today']),
    'extensions': (['1 extension on.',
                    '0 extensions on.'],
                   ['Extensions']),
    'history': (['Kept on this Mac only. 5 pages today.',
                 'Kept on this Mac only. 1 page today.'],
                ['History', 'Kept on this Mac only.']),
    'bookmarks': (['12 bookmarks in 3 folders, kept on this Mac.',
                   '1 bookmark in 1 folder, kept on this Mac.'],
                  ['Bookmarks']),
    'passwords': (['2 passwords saved on this Mac, locked with your Mac login.'],
                  ['Password Manager']),
    'version': (['Tark 155.0.8059.39, built on Chromium for this Mac.'],
                ['Tark 155.0.8059.39, built on Tark for this Mac.']),
}


def test_sentence_patterns():
    for page, (good, bad) in SENTENCES.items():
        for sentence in good:
            assert not page_audit.problems(page, facts(sentence=sentence)), (page, sentence)
        for sentence in bad:
            assert page_audit.problems(page, facts(sentence=sentence)), (page, sentence)
    assert page_audit.problems('history', facts(sentence=None))


def test_row_shadows_are_problems():
    assert page_audit.problems('history', facts(row_shadows=3))


def test_sidebar_line_is_coral():
    assert page_audit.problems('history', facts(sidebar_selected_border='0px rgb(0, 0, 0)'))
    assert page_audit.problems('history', facts(dark=True, sidebar_selected_border=CORAL[False]))
    # Pages without a sidebar pass with None.
    assert not page_audit.problems('downloads', facts(
        sentence='Saved to your Downloads folder', sidebar_selected_border=None))


def test_sentence_must_fit_one_line():
    assert page_audit.problems('history', facts(sentence_lines=2))


def test_pages_cover_the_spec():
    assert set(page_audit.PAGES) == {'downloads', 'extensions', 'history', 'bookmarks',
                                     'passwords', 'version', 'urls'}
    assert page_audit.PAGES['passwords'] == 'chrome://password-manager/passwords'


def test_downloads_danger_row_kept():
    sentence = 'Saved to your Downloads folder'
    kept = {'text': 'This file is dangerous, so Tark has blocked it.',
            'buttons': ['More actions']}
    assert not page_audit.problems('downloads', facts(
        sentence=sentence, sidebar_selected_border=None, danger_row=kept))
    lost = {'text': '', 'buttons': []}
    assert page_audit.problems('downloads', facts(
        sentence=sentence, sidebar_selected_border=None, danger_row=lost))


def test_downloads_zero_is_empty_state():
    assert page_audit.problems('downloads', facts(
        sentence='0 files today, saved to your Downloads folder',
        sidebar_selected_border=None))


def test_version_rows():
    version = dict(sentence='Tark 155.0.8059.39, built on Chromium for this Mac.',
                   sidebar_selected_border=None)
    assert page_audit.problems('version', facts(rows=6, **version)) == []
    assert page_audit.problems('version', facts(rows=0, **version))


def test_header_overflow_is_a_problem():
    # Review (M3d): in a narrow window a long sentence pushed the search icon
    # out of the toolbar; the toolbar must never be wider than its box.
    assert page_audit.problems('history', facts(header_overflow=True))
    assert not page_audit.problems('history', facts(header_overflow=False))
