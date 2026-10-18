"""Tests for utils/brand_audit.py's allowlist (spec 6.3's kept words)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import brand_audit  # noqa: E402


def hits(url, text):
    return brand_audit.find_hits(url, text)


def test_google_product_names_pass():
    assert hits('chrome://extensions/', 'Get more from the Chrome Web Store') == []
    assert hits('chrome://certificate-manager/', 'the Chrome Root Program') == []
    assert hits('chrome://inspect/', 'connecting to Chrome DevTools MCP') == []


def test_chromium_credit_passes_only_where_it_belongs():
    assert hits('chrome://credits/', 'Chromium') == []
    assert hits('chrome://settings/help',
                'Tark is made possible by the Chromium open source project') == []
    assert hits('chrome://history/', 'made possible by the Chromium open source project') != []


def test_user_agent_token_passes():
    assert hits('chrome://version/', 'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari') == []


def test_chrome_mobile_promo_label_passes_on_flags_only():
    assert hits('chrome://flags/', 'Enabled - Your Chrome with push notification') == []
    assert hits('chrome://settings/', 'Your Chrome') != []


def test_plain_product_word_fails():
    found = hits('chrome://downloads/', 'Open in Chrome when done')
    assert len(found) == 1 and 'Open in Chrome' in found[0]


def test_compound_and_lowercase_words_are_not_hits():
    assert hits('chrome://version/', 'ungoogled-chromium ChromeOS Chromebook chrome-extension://x') == []


# Found by the first runs: developer pages (internal debugging pages, off by
# default) naming Chromium internals, and the PDF viewer's web-visible name.
def test_developer_page_internals_pass():
    assert hits('chrome://histograms/', 'Histogram: Chrome.ProcessSingleton.TimeToCreate') == []
    assert hits('chrome://gpu/', 'prevent a Chromium renderer process from successfully') == []
    assert hits('chrome://color-pipeline-internals/', 'the core Chrome UX specification') == []
    assert hits('chrome://extensions-internals/', '"name": "Chromium PDF Viewer"') == []
    assert hits('chrome://settings/', 'Histogram: Chrome.ProcessSingleton') != []


def test_command_urls_are_not_audited():
    text = 'List of Tark URLs tark://about tark://version Command URLs for Debug tark://gpucrash tark://kill'
    assert brand_audit.listed_pages(text) == (['chrome://about/', 'chrome://version/'], [])


def test_internal_debugging_pages_are_listed_apart():
    text = ('List of Tark URLs tark://version Internal Debugging Page URLs '
            'tark://infobar-internals Command URLs for Debug tark://kill')
    assert brand_audit.listed_pages(text) == (['chrome://version/'], ['chrome://infobar-internals/'])


# Found by the user on a tab: a page without a title is named by its address.
def test_shown_chrome_addresses_are_hits():
    found = hits('chrome://terms/', 'TAB TITLE: chrome://terms')
    assert len(found) == 1 and 'chrome://terms' in found[0]
    assert hits('chrome://terms/', 'TAB TITLE: tark://terms') == []
    assert hits('chrome://extensions/', 'chrome-extension://abc') == []


# Spec 6.3 lists where shown addresses read tark://; prose on internal pages
# that mentions a chrome:// address (it still works when typed) is not one.
def test_addresses_count_in_titles_and_error_pages_only():
    assert hits('chrome://flags/', 'can be internal (e.g. chrome://new-tab-page)') == []
    assert hits('chrome://foo/', 'The webpage at chrome://foo/ might be temporarily down') != []
    assert hits('chrome://foo/', 'TAB TITLE: chrome://foo/') != []


# Release audit: third-party project names on the licence page and GPU
# diagnostics text are not Tark's own wording.
def test_credits_and_gpu_diagnostics_pass():
    assert hits('chrome://credits/', 'ARCore SDK client library for Chrome homepage') == []
    assert hits('chrome://credits/', 'Google Chrome Content Analysis Connector Agent SDK') == []
    assert hits('chrome://gpu/', 'will be log via EmitLog, thus printed in Chrome console') == []
    assert hits('chrome://policy/', 'Chrome Policies') != []
