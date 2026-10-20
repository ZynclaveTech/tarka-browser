# Copyright 2025 The Helium Authors
# Modifications Copyright 2026 The Tark Authors
# You can use, redistribute, and/or modify this source code under
# the terms of the GPL-3.0 license that can be found in the LICENSE.GPL-3.0 file.
# Adapted for Tark: product name is Tark and the chrome:// scheme is left alone.
"""Util library for name_substitution.py"""

import re
import sys
import xml.etree.ElementTree as xml

REPLACEMENT_REGEXES_STR = [
    # Tark: the copyright line (About, chrome://version) names the company.
    (r'(?:The )?Chromium Authors', r'Zynclave Tech Private Limited'),

    # stuff we don't want to replace
    (r'(\w+) Root Program', r'\1_unreplace Root Program'),
    (r'(\w+) Web( S|s)tore', r'\1_unreplace Web Store'),
    (r'(\w+) Remote Desktop', r'\1_unreplace Remote Desktop'),
    (r'(\w+) DevTools MCP', r'\1_unreplace DevTools MCP'),
    # Tark's own sentences name Chromium on purpose (M3d: tark://version).
    (r'built on (Chromium)', r'built on \1_unreplace'),

    # main replacement
    (r'(?:Google )?Chrom(e|ium)(?!\w)', r'Tark'),

    # post-replacement cleanup
    (r'((?:Google )?Chrom(e|ium))_unreplace', r'\1'),
    (r'_unreplace', r'')
]

REPLACEMENT_REGEXES = list(map(lambda line: (re.compile(line[0]), line[1]),
                               REPLACEMENT_REGEXES_STR))


def _private(match):
    """Tark calls Incognito "private" (spec 6.1). Capital P at the start of a
    sentence and in title case ("Open Link in Private Window"), lower case in
    running text ("New private window")."""
    word = match.group(0)
    if word[0] == 'i':
        return 'private'
    before = match.string[:match.start()]
    after = match.string[match.end():]
    starts_sentence = (not before.strip() or re.search(r'[.!?]\s+$', before)
                       or re.search(r'\{\s*$', before))  # an ICU plural branch
    title_case = re.match(r'\s+[A-Z]', after)
    return 'Private' if starts_sentence or title_case else 'private'


# English UI text only: translations keep their own word, which in several
# languages is "incognito" inside a native phrase ("Navigazione in incognito").
# URLs and identifiers (chrome://settings/incognito, IncognitoMode) are left
# alone.
ENGLISH_ONLY_REGEXES = [
    (re.compile(r'(?<![\w/.:-])[Ii]ncognito(?![\w/.-])'), _private),
    (re.compile(r'\bnon-incognito\b'), 'non-private'),
]


# Tark (A4, Android): plain words for whole messages, by message name:
# name -> (English, old id, new id, {language: Tark's wording}). The English
# text is replaced; translations stay under the old id (other messages can
# share the old English) and are copied to the new id, Hindi with Tark's
# wording, unless the new id already has a translation of its own. The ids
# are grit's fingerprints, pinned so the .xtb pass needs no grit
# (utils/tests/test_name_substitution.py checks them against grit).
MESSAGE_RENAMES = {
    'IDS_PASSWORD_MANAGER_SETTINGS_TITLE':
        ('Passwords', '6247557882553405851', '7029809446516969842', {'hi': 'पासवर्ड'}),
    'IDS_CLEAR_BROWSING_DATA_TITLE':
        ('Clear history and site data', '961856697154696964', '7602233293931907714',
         {'hi': 'इतिहास और साइट का डेटा मिटाएं'}),
    'IDS_PREFS_SITE_SETTINGS':
        ('Site permissions', '4165986682804962316', '523862956770478816',
         {'hi': 'साइट की अनुमतियां'}),
}


def is_android_strings(path):
    """Whether a .grd/.grdp/.xtb path holds Android UI strings, the only ones
    MESSAGE_RENAMES applies to (the Mac's strings stay as they are)."""
    return '/android/' in '/' + str(path)


def has_message_renames(text):
    """Whether a .grd/.grdp text holds a message MESSAGE_RENAMES renames."""
    return any(f'name="{name}"' in text for name in MESSAGE_RENAMES)


def rename_message(message):
    """Tark's plain word for a whole message (MESSAGE_RENAMES)."""
    rename = MESSAGE_RENAMES.get(message.get('name'))
    if rename and message.text and not len(message):
        message.text = message.text.replace(message.text.strip(), rename[0])


def copy_renamed_translations(xml_tree):
    """Adds each renamed message's translation under its new id (see
    MESSAGE_RENAMES); returns whether any was added."""
    lang = xml_tree.get('lang', '')
    by_id = {t.get('id'): t for t in xml_tree.findall('.//translation')}
    added = False
    for _, old_id, new_id, by_lang in MESSAGE_RENAMES.values():
        if new_id in by_id or old_id not in by_id:
            continue
        old = by_id[old_id]
        copy = xml.Element('translation', {'id': new_id})
        copy.text = by_lang.get(lang, old.text)
        if lang not in by_lang:
            copy.extend(list(old))
        copy.tail = old.tail
        xml_tree.append(copy)
        added = True
    return added


def add_grit_to_path(tree):
    """Inserts the grit/ folder into the module loading path."""
    grit_path = tree / 'tools' / 'grit'
    if not grit_path.exists():
        raise FileNotFoundError(f"grit directory not found at {grit_path}")
    sys.path.insert(0, str(grit_path))


def strip_message_text_for_fp(text):
    """
    Removes whitespace markers from GRIT text.
    See for example: IDS_EXTENSIONS_SETTINGS_API_SECOND_LINE_START_PAGES
    in //chrome/app/chromium_strings.grd.
    """
    text = text.strip()
    if text.startswith("'''"):
        text = text[3:]
    if text.endswith("'''"):
        text = text[:-3]
    return text.strip()


def compute_fp(message):
    """
    Computes the fingerprint for a particular .grd <message>, which is
    later used to replace the fingerprints used in .xtb l10n files.
    """
    # We need to import this here, because it only becomes
    # available after add_grit_to_path() is called.
    # pylint: disable=import-outside-toplevel,import-error
    import grit.extern.tclib

    text = message.text or ''
    for elem in message.findall('ph'):
        text = text + elem.get('name').upper() + (elem.tail or '')
    text = strip_message_text_for_fp(text)

    meaning = message.get('meaning', '')
    return grit.extern.tclib.GenerateMessageId(text, meaning)


def replace_text(text, translation=False):
    """Replaces instances of Chrom(e | ium) with Tark in strings, and in
    English text (not translations) Incognito with private."""
    had_match = False
    regexes = REPLACEMENT_REGEXES if translation else (
        REPLACEMENT_REGEXES + ENGLISH_ONLY_REGEXES)
    for regex, replacement in regexes:
        if regex.search(text):
            had_match = True
            text = regex.sub(replacement, text)

    return text, had_match


_STRING_LITERAL = re.compile(r'"((?:\\.|[^"\\\n])*)"')
_HTML_TEXT = re.compile(r'>([^<>]*)<')
_TEMPLATE_EXPRESSION = re.compile(r'(\$\{[^}]*\})')


def replace_string_literals(text):
    """Tark (M3b): the product rename inside double-quoted C++/TS string
    literals only, for UI text kept outside .grd files (chrome://flags
    descriptions). Identifiers such as kChromeRefreshName are untouched."""
    return _STRING_LITERAL.sub(
        lambda m: '"' + replace_text(m.group(1))[0] + '"', text)


def _replace_text_node(match):
    parts = _TEMPLATE_EXPRESSION.split(match.group(1))
    # Odd indexes are ${...} expressions: code, left alone.
    return '>' + ''.join(part if i % 2 else replace_text(part)[0]
                         for i, part in enumerate(parts)) + '<'


def replace_html_text(text):
    """Tark (M3b): the product rename in HTML text between tags only; tag
    names, attributes (href="chrome://...") and ${...} expressions in Lit
    templates are untouched."""
    return _HTML_TEXT.sub(_replace_text_node, text)


def should_skip_tail(elem):
    """
    Whether the `tail` text should be left as-is on
    a particular element.
    """
    return elem.get('name') == 'BEGIN_LINK_CHROMIUM' \
        and elem.tail == 'Chromium'


def replace_grit_message(msg, translation=False):
    """
    Replaces instances of Chrom(e | ium) with Tark
    in a <message> or <translation> element (and its children).
    """
    had_any_match = False

    if msg.text:
        text, match = replace_text(msg.text, translation)
        msg.text = text
        had_any_match |= match

    if msg.tail and not should_skip_tail(msg):
        tail, match = replace_text(msg.tail, translation)
        msg.tail = tail
        had_any_match |= match

    for child in msg:
        had_any_match |= replace_grit_message(child, translation)

    return had_any_match


def replace_xtb_translation(msg, fp_map):
    """
    Replaces instances of Chrom(e | ium) with Tark in a
    .xtb <translation>.
    """
    had_match = replace_grit_message(msg, translation=True)

    # Tark: a translation follows its English message to the new id even when
    # the translation itself had nothing to replace ("Neues Inkognitofenster"
    # for "New private window"); otherwise the locale falls back to English.
    msg_id = msg.get('id')
    if msg_id in fp_map:
        msg.set('id', fp_map[msg_id])
        return True
    return had_match


def get_parser():
    """Returns a parser configured to preserve comments."""
    return xml.XMLParser(target=xml.TreeBuilder(insert_comments=True))


def replace_grit_tree(text, android=False):
    """Replaces instances of Chrom(e | ium) with Tark, where desired"""
    xml_tree = xml.fromstring(text, get_parser())
    fp_map = {}

    for message in xml_tree.findall('.//message'):
        old_fp = compute_fp(message)
        if android:
            rename_message(message)
        if replace_grit_message(message):
            new_fp = compute_fp(message)
            if old_fp != new_fp:
                fp_map[old_fp] = new_fp

    return xml.tostring(xml_tree, encoding='unicode', xml_declaration=True), fp_map


def dedup_translations_in_place(translation, seen):
    """
    Ensures the .xtb file never has duplicate fingerprints if two
    strings are the same.
    """

    # If there are colliding strings after name substitution, offset the
    # additional translations so that they don't error out the build.
    # This usually applies to strings that have one "Chromium" and one
    # "Chrome" variant. Since we substituted both of those with Tark,
    # their fingerprints collide and crash the build.
    translation_id = translation.get('id')
    while translation_id in seen and translation_id.isdigit():
        translation_id = str(int(translation_id) + 1)
    translation.set('id', translation_id)
    seen.add(translation_id)


def replace_xtb_tree(text, fp_map, android=False):
    """Same as replace_grit_tree(), but on .xtb translation files."""
    xml_tree = xml.fromstring(text, get_parser())
    changed = False
    ids_seen = set()

    if android:
        changed |= copy_renamed_translations(xml_tree)
    for translation in xml_tree.findall('.//translation'):
        assert translation.get('id')
        changed |= replace_xtb_translation(translation, fp_map)
        dedup_translations_in_place(translation, ids_seen)

    if changed:
        return xml.tostring(xml_tree, encoding='unicode', xml_declaration=True)

    return None


def merge_fp_maps(results):
    """
    Takes all the results from substitute_file() calls, and merges
    their fingerprint mappings.
    """
    merged_fp_map = {}
    for result in results:
        _, fp_map = result
        merged_fp_map.update(fp_map)
    return merged_fp_map
